import hashlib, json
from fastapi import HTTPException
from sqlalchemy import select
from .db import Record, serialize, now
from .auth import Actor

def rows(db, actor, kind, parent=None):
    q=select(Record).where(Record.org_id==actor.org,Record.kind==kind)
    if parent: q=q.where(Record.parent_id==parent)
    return list(db.scalars(q.order_by(Record.created_at.desc())))

def get(db, actor, id, kind=None, lock=False):
    q=select(Record).where(Record.id==id,Record.org_id==actor.org)
    if kind: q=q.where(Record.kind==kind)
    if lock: q=q.with_for_update()
    r=db.scalar(q)
    if not r: raise HTTPException(404,'Record not found')
    return r

def case_access(actor, case):
    if actor.role in ['relationship_manager','credit_analyst'] and actor.id not in [case.data.get('owner_id'),case.data.get('created_by')]:
        raise HTTPException(403,'This application is assigned to another staff member')

def check_version(r, version):
    if r.version!=version: raise HTTPException(409,'This record changed. Refresh before submitting again.')

def add(db,actor,kind,data,parent=None,id=None):
    r=Record(org_id=actor.org,kind=kind,parent_id=parent,data=data)
    if id: r.id=id
    db.add(r); db.flush(); return r

def audit(db,actor,action,target,before=None,after=None,reason=None):
    return add(db,actor,'audit',{'actor_id':actor.id,'actor':actor.name,'role':actor.role,'action':action,'target':target,'before':before,'after':after,'reason':reason},target)

def idempotent(db,actor,key,payload):
    if not key or len(key)>150: raise HTTPException(400,'Idempotency-Key required (maximum 150 characters)')
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()
    id='idem-'+hashlib.sha256(f'{actor.org}:{actor.id}:{key}'.encode()).hexdigest()
    old=db.scalar(select(Record).where(Record.id==id,Record.org_id==actor.org))
    if old:
        if old.data['digest']!=digest: raise HTTPException(409,'Idempotency key already used with different input')
        return old,True
    return add(db,actor,'idempotency',{'digest':digest,'result':None},id=id),False

def policy_current(db,actor):
    published=[r for r in rows(db,actor,'policy') if r.data.get('status')=='published']
    return max(published,key=lambda r:r.data.get('published_at',r.created_at.isoformat()),default=None)

def facts_for(db,actor,case_id):
    facts={}; sources={}; unverified=[]
    # Ascending date means most recent review wins, with original kept as history.
    for r in reversed(rows(db,actor,'fact',case_id)):
        key=r.data['key']; facts[key]=r.data.get('value'); sources[key]=serialize(r)
    # Application terms are available without fabricating customer obligations/income.
    case=get(db,actor,case_id,'application')
    derived={'requested_amount':case.data.get('amount')}
    pricing=case.data.get('pricing',{})
    if pricing.get('monthly_payment') is not None: derived['proposed_emi']=pricing['monthly_payment']
    elif case.data.get('product')=='term_loan' and case.data.get('rate') is not None:
        from .engine import emi
        derived['proposed_emi']=str(emi(case.data['amount'],case.data['rate'],case.data.get('tenure',36)))
    for key,value in derived.items():
        if key not in facts and value is not None:
            facts[key]=value;sources[key]={'id':'application:'+case.id+':'+str(case.version),'value':value,'verified':True,'source_text':'Application terms / saved repayment quote','source_kind':'application_terms'}
    for k,v in sources.items():
        if not v.get('verified'): unverified.append(k)
    return facts,sources,unverified

def latest_assessment(db,actor,case_id):
    rs=rows(db,actor,'assessment',case_id)
    return rs[0] if rs else None

def override_case(db,actor,case,body):
    actor.require('override'); check_version(case,body['expected_version'])
    if len(body.get('justification','').strip())<10 or not body.get('reason_category'): raise HTTPException(422,'Choose a reason and provide at least 10 characters of justification')
    for evidence_id in body.get('supporting_evidence',[]):
        document=get(db,actor,evidence_id,'document')
        if document.parent_id!=case.id: raise HTTPException(422,'Supporting document belongs to another application')
    action=body.get('action','decision'); before=dict(case.data)
    if action=='decision':
        if body.get('disposition') not in ['approved','declined','returned','withdrawn','pending_approval','in_review']: raise HTTPException(422,'Invalid disposition')
        change={'status':body['disposition'],'decision_by':actor.id,'decision_at':now().isoformat()}
        if body['disposition']=='approved':
            amount=body.get('sanctioned_amount',case.data['amount'])
            from .engine import decimal
            if decimal(amount)<=0: raise HTTPException(422,'Sanctioned amount must be positive')
            change['sanctioned_amount']=str(amount)
        else: change['sanctioned_amount']=None
    elif action=='reassign':
        if not body.get('owner_id'): raise HTTPException(422,'Owner required')
        members=rows(db,actor,'membership')
        if not any(m.data.get('user_id')==body['owner_id'] for m in members): raise HTTPException(422,'Choose a member of this organization')
        change={'owner_id':body['owner_id'],'owner':body.get('owner',body['owner_id'])}
    else: raise HTTPException(422,'Invalid override action')
    assessment=latest_assessment(db,actor,case.id)
    event=add(db,actor,'override',{'actor':actor.name,'actor_id':actor.id,'action':action,'reason_category':body['reason_category'],'justification':body['justification'],'before':before,'after':{**before,**change},'assessment_id':assessment.id if assessment else None,'supporting_evidence':body.get('supporting_evidence',[])},case.id)
    case.data={**before,**change,'override_id':event.id}
    audit(db,actor,'administrator.override',case.id,before,case.data,body['justification'])
    add(db,actor,'notification',{'user_id':case.data.get('owner_id'),'message':f"Administrator override on {case.data['reference']}",'read':False},case.id)
    return event


def assessment_job(db, actor, case, trigger='manual'):
    from .analytics import readiness
    policy=policy_current(db,actor)
    if not policy:
        case.data={**case.data,'auto_assessment_error':'Publish a credit policy to enable automatic assessment.'}
        return None
    facts,sources,unverified=facts_for(db,actor,case.id)
    coverage=any(r.get('product')==case.data['product'] or case.data['product'] in policy.data.get('product_groups',{}).get(r.get('product'),[]) for r in policy.data.get('rules',[]))
    snapshot={'evidence_explanations':[serialize(r) for r in rows(db,actor,'evidence_explanation',case.id)],'product_policy_covered':coverage,'bureau_reports':[serialize(r) for r in rows(db,actor,'bureau_report',case.id)],'policy_id':policy.id,'policy':policy.data,'facts':facts,'source_ids':{k:v['id'] for k,v in sources.items()},'missing_documents':[d['label'] for d in readiness(rows(db,actor,'document',case.id),policy.data,case.data['product'],case.data.get('required_documents')) if not d['received']],'unverified':unverified,'periods':{k:v.get('period') for k,v in sources.items()},'product':case.data['product'],'evidence_revision':case.data.get('evidence_revision',0)}
    job=add(db,actor,'job',{'type':'assessment','status':'queued','progress':0,'actor_id':actor.id,'actor':actor.name,'role':actor.role,'snapshot':snapshot,'trigger':trigger},case.id)
    case.data={**case.data,'auto_assessment_error':None}
    audit(db,actor,'assessment.queued',case.id,after={'job_id':job.id,'trigger':trigger,'evidence_revision':snapshot['evidence_revision']})
    return job
