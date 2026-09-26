import asyncio, hashlib, json, secrets
from pathlib import Path
from urllib.parse import urlencode
from datetime import datetime, timezone
import httpx
from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from .config import settings, ROOT
from .db import Session, Record, scope, serialize, now
from .auth import Actor, actor, ROLES
from .service import rows, get, add, audit, case_access, check_version, idempotent, policy_current, facts_for, latest_assessment, override_case, assessment_job
from .engine import evaluate, validate_policy, decimal, emi
from .extraction import inspect_file
from .providers import ollama, ProviderUnavailable
from .appraisal import structured_appraisal
from .tasks import extract_job, assess_job, dispatch_assessment
from .analytics import DOCUMENTS, readiness, product_metrics
from .products import catalog, validate as validate_product, quote, EXTRA_DOCS, ACTIVE_PRODUCTS
from datetime import date

app=FastAPI(title='Credit Appraisal Workbench',version='1.0.0')
app.add_middleware(CORSMiddleware,allow_origins=[settings.frontend_url],allow_credentials=True,allow_methods=['GET','POST','PATCH'],allow_headers=['Authorization','Content-Type','Idempotency-Key','X-Demo-Role'])
app.add_middleware(SessionMiddleware,secret_key=settings.session_secret or secrets.token_hex(32),same_site='lax',https_only=settings.frontend_url.startswith('https://'))

def db_for(a:Actor=Depends(actor)):
    with Session() as db:
        scope(db,a.org)
        try: yield db
        except (StaleDataError,IntegrityError):
            db.rollback(); raise HTTPException(409,'Conflicting change or duplicate request. Refresh and retry.')
        except Exception: db.rollback(); raise

@app.exception_handler(ValueError)
async def value_error(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422,content={'detail':str(exc)})

@app.get('/health')
def health(): return {'status':'ok'}

@app.get('/api/v1/auth/config')
def auth_config(): return {'mode':settings.auth_mode,'workos_configured':bool(settings.workos_client_id and settings.workos_api_key)}

@app.get('/api/v1/auth/login')
def login(request:Request):
    if not settings.workos_client_id or not settings.workos_api_key: raise HTTPException(503,'WorkOS credentials not configured')
    state=secrets.token_urlsafe(32); request.session['oauth_state']=state
    return RedirectResponse('https://api.workos.com/user_management/authorize?'+urlencode({'client_id':settings.workos_client_id,'redirect_uri':settings.workos_redirect_uri,'response_type':'code','provider':'authkit','state':state}))

@app.get('/api/v1/auth/callback')
async def callback(request:Request,code:str,state:str):
    expected=request.session.pop('oauth_state',None)
    if not expected or not secrets.compare_digest(expected,state): raise HTTPException(400,'Invalid login state')
    async with httpx.AsyncClient(timeout=20) as client:
        r=await client.post('https://api.workos.com/user_management/authenticate',json={'client_id':settings.workos_client_id,'client_secret':settings.workos_api_key,'grant_type':'authorization_code','code':code})
    if r.status_code!=200: raise HTTPException(401,'WorkOS authentication failed')
    data=r.json(); user=data['user']; request.session.clear()
    request.session.update({'access_token':data['access_token'],'name':' '.join(filter(None,[user.get('first_name'),user.get('last_name')])) or user['email']})
    return RedirectResponse(settings.frontend_url)

@app.post('/api/v1/auth/logout')
def logout(request:Request): request.session.clear(); return {'ok':True}

@app.get('/api/v1/me')
def me(a:Actor=Depends(actor)): return {'id':a.id,'org':a.org,'role':a.role,'name':a.name,'mode':settings.auth_mode}

@app.get('/api/v1/integrations')
async def integrations(a:Actor=Depends(actor)):
    ollama_status='unavailable'; models=[]
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r=await client.get(settings.ollama_url+'/api/tags'); r.raise_for_status(); models=[m['name'] for m in r.json()['models']]
        ollama_status='ready' if settings.ollama_model in models else 'model_missing'
    except Exception: pass
    return {'roopya':{'status':'manual_entry_available','model':'API onboarding pending · No live bureau pulls','url':'https://roopya.money/free-credit-bureaus-api-integration/'},'qwen':{'status':ollama_status,'model':settings.ollama_model},'decision':{'status':'ready' if settings.decision_model in models else 'model_missing','model':settings.decision_model,'provider':settings.decision_provider},'gemini':{'status':'configured_unverified' if settings.gemini_api_key else 'not_configured','model':settings.gemini_model},'jev':{'status':'configured_unverified' if settings.jev_api_key else 'not_configured','model':settings.jev_model},'workos':{'status':'configured' if settings.workos_api_key and settings.workos_client_id else 'not_configured','mode':settings.auth_mode}}

@app.get('/api/v1/applications')
def applications(a:Actor=Depends(actor),db=Depends(db_for)):
    result=[]
    p=policy_current(db,a)
    for r in rows(db,a,'application'):
        if r.data.get('product') not in ACTIVE_PRODUCTS: continue
        if a.role in ['relationship_manager','credit_analyst'] and a.id not in [r.data.get('owner_id'),r.data.get('created_by')]: continue
        facts,sources,_=facts_for(db,a,r.id)
        checklist=readiness(rows(db,a,'document',r.id),p.data if p else {},r.data['product'],r.data.get('required_documents'))
        bureau={k:facts.get(k) for k in ['promoter_cibil_score','commercial_cibil_rank','bureau_report_date','max_dpd','overdue_amount','credit_utilisation']}
        bureau['verification']='manual_entry_not_bureau_verified' if sources.get('bureau_report_date',{}).get('entry_method')=='manual' else 'synthetic_report' if r.data.get('synthetic') and bureau.get('bureau_report_date') else 'uploaded_not_bureau_verified' if bureau.get('bureau_report_date') else 'not_available'
        result.append(serialize(r)|{'business_segment':r.data.get('business_segment','msme'),'bureau':bureau,'documents_received':sum(x['received'] for x in checklist),'documents_required':len(checklist)})
    return result

# Module queues reuse the same tenant and case visibility rules as origination.
@app.get('/api/v1/approval-workbench/applications', tags=['Approval Workbench'])
def approval_queue(a:Actor=Depends(actor),db=Depends(db_for)):
    return sorted(applications(a,db),key=lambda c:(c['status']!='pending_approval',c['created_at']))

@app.get('/api/v1/document-review/applications', tags=['Document Review'])
def document_queue(a:Actor=Depends(actor),db=Depends(db_for)):
    return applications(a,db)

@app.get('/api/v1/financial-spreading/applications', tags=['Financial Spreading'])
def financial_queue(a:Actor=Depends(actor),db=Depends(db_for)):
    return applications(a,db)

@app.get('/api/v1/cash-flow/applications', tags=['Cash Flow'])
def cashflow_queue(a:Actor=Depends(actor),db=Depends(db_for)):
    return applications(a,db)

@app.get('/api/v1/employee-assignments', tags=['Employee Assignments'])
def assignment_queue(a:Actor=Depends(actor),db=Depends(db_for)):
    return applications(a,db)

class ApplicationInput(BaseModel):
    business_segment: str=Field(default='msme',pattern='^(msme|enterprise)$')
    borrower: str=Field(min_length=2,max_length=180)
    product: str
    amount: str
    tenure: int=Field(default=36,ge=1,le=600)
    rate: str='12'
    sector: str='Manufacturing'
    branch: str='Mumbai'

@app.post('/api/v1/applications')
def create_application(body:ApplicationInput,a:Actor=Depends(actor),db=Depends(db_for),idempotency_key:str=Header()):
    a.require('originate')
    product=next((p for p in catalog(db,a) if p['key']==body.product),None)
    if not product: raise HTTPException(422,'Unknown product; add it in Loan Products & Pricing')
    pricing=quote(product,body.amount,body.tenure)
    if decimal(body.amount)<=0: raise HTTPException(422,'Amount must be positive')
    emi(body.amount,body.rate,body.tenure)
    idem,replay=idempotent(db,a,idempotency_key,{'operation':'create_application',**body.model_dump()})
    if replay: return idem.data['result']
    r=add(db,a,'application',{**body.model_dump(),'rate':pricing['rate'],'pricing':pricing,'required_documents':product['documents'],'borrower_type':product['borrower_type'],'reference':'CR-'+secrets.token_hex(3).upper(),'status':'draft','owner':a.name,'owner_id':a.id,'created_by':a.id,'evidence_revision':0,'assessment_stale':True,'synthetic':settings.auth_mode=='demo','sanctioned_amount':None})
    audit(db,a,'application.created',r.id,after=r.data); result=serialize(r); idem.data={**idem.data,'result':result}; db.commit(); return result

@app.get('/api/v1/applications/{id}')
def application(id:str,a:Actor=Depends(actor),db=Depends(db_for)):
    r=get(db,a,id,'application'); case_access(a,r)
    related={k:[serialize(x) for x in rows(db,a,k,id)] for k in ['document','fact','assessment','exception','override','approval','audit','job','transaction','bureau_report','debt_schedule','evidence_explanation']}
    for doc in related['document']: doc.pop('path',None)
    facts,sources,unverified=facts_for(db,a,id)
    policy=policy_current(db,a)
    financial=evaluate(policy.data,facts,r.data['product'],{k:v.get('period') for k,v in sources.items()}) if policy else {'metrics':[],'rules':[],'blocking':0,'facts':facts}
    application_data=serialize(r)
    for assessment in related['assessment']:
        assessment['structured_output']=structured_appraisal(assessment)
    latest=related['assessment'][0] if related['assessment'] else None
    if latest and policy and latest.get('snapshot',{}).get('policy_id')!=policy.id: application_data['assessment_stale']=True
    return {'application':application_data,**related,'facts':facts,'sources':sources,'unverified':unverified,'financial':financial,'policy_id':policy.id if policy else None,'document_checklist':readiness(rows(db,a,'document',id),policy.data if policy else {},r.data['product'],r.data.get('required_documents')),'proposed_emi':str(emi(r.data['amount'],r.data.get('rate','0'),r.data.get('tenure',36))) if r.data['product']=='term_loan' else None}

@app.get('/api/v1/dashboard')
def dashboard(a:Actor=Depends(actor),db=Depends(db_for)):
    cases=applications(a,db); ids={c['id'] for c in cases}
    exceptions=[serialize(r)|{'application_id':r.parent_id} for r in rows(db,a,'exception') if r.parent_id in ids and r.data['status']=='open']
    overrides=[serialize(r) for r in rows(db,a,'override') if r.parent_id in ids]
    return {'applications':cases,'product_metrics':product_metrics(cases),'products':catalog(db,a),'document_catalog':DOCUMENTS+EXTRA_DOCS,'exceptions':exceptions,'overrides':overrides,'audit':[serialize(r) for r in rows(db,a,'audit') if r.parent_id in ids or a.role not in ['relationship_manager','credit_analyst']][:30]}

@app.post('/api/v1/applications/{id}/documents')
async def upload(id:str,file:UploadFile=File(),document_type:str=Form('financial_statement'),a:Actor=Depends(actor),db=Depends(db_for),idempotency_key:str=Header()):
    a.require('upload'); case=get(db,a,id,'application',True); case_access(a,case)
    content=await file.read(25*1024*1024+1); name=Path(file.filename or 'document').name
    info=inspect_file(content,name); sha=hashlib.sha256(content).hexdigest()
    idem,replay=idempotent(db,a,idempotency_key,{'operation':'upload','case':id,'hash':sha})
    if replay: return idem.data['result']
    duplicate=next((x for x in rows(db,a,'document',id) if x.data.get('sha256')==sha),None)
    if duplicate: raise HTTPException(409,'Identical document already exists. Retry extraction from the existing document.')
    folder=Path(settings.storage_dir); folder=folder if folder.is_absolute() else ROOT/folder
    target=folder/a.org/(secrets.token_hex(16)+Path(name).suffix.lower()); target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(content)
    doc=add(db,a,'document',{'filename':name,'document_type':document_type,'path':str(target),'sha256':sha,'size':len(content),'status':'locked' if info['locked'] else 'uploaded',**info},id)
    case.data={**case.data,'evidence_revision':case.data.get('evidence_revision',0)+1,'assessment_stale':True,'status':'evidence_pending' if case.data['status']=='draft' else case.data['status']}
    automatic_job=assessment_job(db,a,case,'evidence_updated')
    audit(db,a,'document.uploaded',id,after={'document_id':doc.id,'filename':name}); result=serialize(doc); result.pop('path',None)
    idem.data={**idem.data,'result':result}; db.commit(); dispatch_assessment(db,a,automatic_job); return result

@app.get('/api/v1/documents/{id}/content')
def content(id:str,a:Actor=Depends(actor),db=Depends(db_for)):
    doc=get(db,a,id,'document'); case_access(a,get(db,a,doc.parent_id,'application'))
    return FileResponse(doc.data['path'],filename=doc.data['filename'],content_disposition_type='inline')

@app.post('/api/v1/documents/{id}/extract')
def start_extract(id:str,body:dict,a:Actor=Depends(actor),db=Depends(db_for),idempotency_key:str=Header()):
    a.require('upload'); doc=get(db,a,id,'document',True); case=get(db,a,doc.parent_id,'application'); case_access(a,case)
    idem,replay=idempotent(db,a,idempotency_key,{'operation':'extract','document':id,**body})
    if replay: return idem.data['result']
    if doc.data.get('locked'): raise HTTPException(422,'Upload an unlocked copy of this PDF')
    if body.get('mapping'): doc.data={**doc.data,'mapping':body['mapping']}
    job=add(db,a,'job',{'type':'extraction','status':'queued','progress':0,'document_id':id,'actor_id':a.id,'actor':a.name,'role':a.role},case.id)
    result=serialize(job); idem.data={**idem.data,'result':result}; db.commit()
    try: extract_job.delay(job.id,a.org)
    except Exception:
        job.data={**job.data,'status':'failed','error':'Queue unavailable. Start Redis and retry.'}; db.commit()
    return serialize(job)

@app.post('/api/v1/applications/{id}/facts')
def review_fact(id:str,body:dict,a:Actor=Depends(actor),db=Depends(db_for),idempotency_key:str=Header()):
    a.require('review'); case=get(db,a,id,'application',True); case_access(a,case)
    idem,replay=idempotent(db,a,idempotency_key,{'operation':'review_fact','case':id,**body})
    if replay: return idem.data['result']
    check_version(case,body['expected_version']); p=policy_current(db,a)
    field=next((f for f in p.data['fields'] if f['key']==body.get('key')),None) if p else None
    if not field: raise HTTPException(422,'Define this field in a published policy first')
    if not body.get('source_text'): raise HTTPException(422,'Source reference or explanation required')
    if body.get('document_id'):
        doc=get(db,a,body['document_id'],'document')
        if doc.parent_id!=id: raise HTTPException(422,'Document belongs to a different application')
    if field.get('type','number')=='number' and body.get('value') is not None: decimal(body['value'])
    f=add(db,a,'fact',{k:v for k,v in body.items() if k!='expected_version'}|{'verified':True,'reviewer':a.name,'reviewer_id':a.id},id)
    case.data={**case.data,'evidence_revision':case.data.get('evidence_revision',0)+1,'assessment_stale':True}
    automatic_job=assessment_job(db,a,case,'evidence_updated')
    audit(db,a,'fact.reviewed',id,after=f.data); result=serialize(f); idem.data={**idem.data,'result':result}; db.commit(); dispatch_assessment(db,a,automatic_job); return result

@app.post('/api/v1/applications/{id}/assessments')
def start_assessment(id:str,body:dict,a:Actor=Depends(actor),db=Depends(db_for),idempotency_key:str=Header()):
    a.require('assess'); case=get(db,a,id,'application',True); case_access(a,case)
    idem,replay=idempotent(db,a,idempotency_key,{'operation':'assess','case':id,**body})
    if replay: return idem.data['result']
    check_version(case,body['expected_version']); policy=policy_current(db,a)
    if not policy: raise HTTPException(422,'Publish a policy before assessment')
    job=assessment_job(db,a,case)
    result=serialize(job); result.pop('snapshot',None); idem.data={**idem.data,'result':result}; db.commit()
    try: assess_job.delay(job.id,a.org)
    except Exception:
        job.data={**job.data,'status':'failed','error':'Queue unavailable. Start Redis and retry.'}; db.commit()
    return serialize(job)

@app.post('/api/v1/applications/{id}/decisions')
def decide(id:str,body:dict,a:Actor=Depends(actor),db=Depends(db_for),idempotency_key:str=Header()):
    a.require('decide'); case=get(db,a,id,'application',True)
    idem,replay=idempotent(db,a,idempotency_key,{'operation':'decision','case':id,**body})
    if replay: return idem.data['result']
    check_version(case,body['expected_version'])
    if a.id in [case.data.get('created_by'),case.data.get('owner_id')]: raise HTTPException(403,'Self-approval requires an explicit administrator override')
    if case.data['status'] in ['approved','declined','withdrawn']: raise HTTPException(409,'Revising a completed decision requires an administrator override')
    if body.get('disposition') not in ['approved','declined','returned','pending_approval']: raise HTTPException(422,'Invalid disposition')
    if len(body.get('justification','').strip())<10: raise HTTPException(422,'Decision reason required (at least 10 characters)')
    assessment=latest_assessment(db,a,id)
    if body['disposition']=='approved':
        if not assessment or case.data.get('assessment_stale') or assessment.data.get('gates') or (policy_current(db,a) and assessment.data.get('snapshot',{}).get('policy_id')!=policy_current(db,a).id): raise HTTPException(422,'Resolve appraisal gates or use an explicit administrator override')
        if assessment.data.get('recommendation')!='approve': raise HTTPException(422,'Contrary recommendation requires administrator override')
        if decimal(body.get('sanctioned_amount',case.data['amount']))<=0: raise HTTPException(422,'Sanction amount must be positive')
    before=dict(case.data); case.data={**before,'status':body['disposition'],'decision_by':a.id,'decision_at':now().isoformat(),'sanctioned_amount':str(body.get('sanctioned_amount',case.data['amount'])) if body['disposition']=='approved' else None}
    approval=add(db,a,'approval',{'actor':a.name,'actor_id':a.id,**body,'assessment_id':assessment.id if assessment else None},id)
    audit(db,a,'credit.decision',id,before,case.data,body['justification']); result=serialize(approval); idem.data={**idem.data,'result':result}; db.commit(); return result

@app.post('/api/v1/applications/{id}/overrides')
def override(id:str,body:dict,a:Actor=Depends(actor),db=Depends(db_for),idempotency_key:str=Header()):
    a.require('override'); case=get(db,a,id,'application',True)
    idem,replay=idempotent(db,a,idempotency_key,{'operation':'override','case':id,**body})
    if replay: return idem.data['result']
    event=override_case(db,a,case,body); result=serialize(event); idem.data={**idem.data,'result':result}; db.commit(); return result

@app.get('/api/v1/policies')
def policies(a:Actor=Depends(actor),db=Depends(db_for)): return [serialize(r) for r in rows(db,a,'policy')]

@app.post('/api/v1/policies')
def policy_save(body:dict,a:Actor=Depends(actor),db=Depends(db_for),idempotency_key:str=Header()):
    a.require('policy'); validate_policy(body)
    idem,replay=idempotent(db,a,idempotency_key,{'operation':'policy_save',**body})
    if replay: return idem.data['result']
    data={k:v for k,v in body.items() if k not in ['id','created_at','updated_at','version','published_by','test_results']}
    data.update({'status':'draft','created_by':a.id,'author':a.name,'revision':len(rows(db,a,'policy'))+1})
    r=add(db,a,'policy',data); audit(db,a,'policy.drafted',r.id,after={'name':data['name']}); result=serialize(r); idem.data={**idem.data,'result':result}; db.commit(); return result

@app.post('/api/v1/policies/{id}/test')
def policy_test(id:str,body:dict,a:Actor=Depends(actor),db=Depends(db_for)):
    a.require('policy'); p=get(db,a,id,'policy',True)
    if p.data['status']=='published': raise HTTPException(422,'Create a draft to test changes')
    results=[]
    for c in rows(db,a,'application'):
        facts,sources,_=facts_for(db,a,c.id); outcome=evaluate(p.data,facts,c.data['product'],{k:v.get('period') for k,v in sources.items()})
        results.append({'id':c.id,'reference':c.data['reference'],'borrower':c.data['borrower'],'blocking':outcome['blocking'],'rules':outcome['rules']})
    p.data={**p.data,'status':'tested','test_results':results,'tested_at':now().isoformat()}; audit(db,a,'policy.tested',p.id,after={'cases':len(results)}); db.commit(); return serialize(p)

@app.post('/api/v1/policies/{id}/publish')
def policy_publish(id:str,body:dict,a:Actor=Depends(actor),db=Depends(db_for),idempotency_key:str=Header()):
    a.require('publish'); p=get(db,a,id,'policy',True)
    idem,replay=idempotent(db,a,idempotency_key,{'operation':'publish','policy':id,**body})
    if replay: return idem.data['result']
    check_version(p,body['expected_version'])
    if p.data['status']!='tested': raise HTTPException(422,'Test the draft before publication')
    own=p.data['created_by']==a.id
    if own:
        a.require('override')
        if len(body.get('justification','').strip())<10 or not body.get('reason_category'): raise HTTPException(422,'Administrator publishing override requires reason and justification')
        add(db,a,'override',{'actor':a.name,'actor_id':a.id,'action':'policy_publish','before':{'status':p.data['status']},'after':{'status':'published'},'reason_category':body['reason_category'],'justification':body['justification']},p.id)
    p.data={**p.data,'status':'published','published_by':a.id,'published_at':now().isoformat()}
    audit(db,a,'policy.published',p.id,after={'revision':p.data['revision'],'admin_override':own},reason=body.get('justification'))
    result=serialize(p); idem.data={**idem.data,'result':result}; db.commit(); return result

@app.post('/api/v1/policies/ai-draft')
def ai_draft(body:dict,a:Actor=Depends(actor)):
    a.require('policy')
    try:
        result=ollama('Draft ONE validation rule in JSON. A true condition means PASS. Keys: id,name,product (both/term_loan/working_capital),severity (blocking/warning/info),condition {field,op (gte/lte/eq/present),value}. Only use supplied fields. Request: '+body.get('instruction','')+'\nFields: '+json.dumps(body.get('fields',[])))
        from .engine import validate_condition
        validate_condition(result['condition'],{f['key'] for f in body.get('fields',[])})
        return result
    except ProviderUnavailable as e: raise HTTPException(503,str(e))

@app.get('/api/v1/exceptions')
def exceptions(a:Actor=Depends(actor),db=Depends(db_for)):
    ids={c['id'] for c in applications(a,db)}
    return [serialize(r)|{'application_id':r.parent_id} for r in rows(db,a,'exception') if r.parent_id in ids]

@app.post('/api/v1/exceptions/{id}/resolve')
def resolve_exception(id:str,body:dict,a:Actor=Depends(actor),db=Depends(db_for),idempotency_key:str=Header()):
    a.require('resolve'); ex=get(db,a,id,'exception',True); case=get(db,a,ex.parent_id,'application'); case_access(a,case)
    idem,replay=idempotent(db,a,idempotency_key,{'operation':'resolve','exception':id,**body})
    if replay: return idem.data['result']
    check_version(ex,body['expected_version'])
    if len(body.get('justification','').strip())<10: raise HTTPException(422,'Resolution explanation required')
    before=dict(ex.data)
    if body.get('override'):
        a.require('override')
        if not body.get('reason_category'): raise HTTPException(422,'Override reason category required')
        add(db,a,'override',{'actor':a.name,'actor_id':a.id,'action':'exception_accept','reason_category':body['reason_category'],'justification':body['justification'],'before':before,'after':{'status':'accepted'}},case.id)
    ex.data={**before,'status':'accepted' if body.get('override') else 'resolved','resolution':body['justification'],'resolved_by':a.name}
    audit(db,a,'exception.resolved',case.id,before,ex.data,body['justification']); result=serialize(ex); idem.data={**idem.data,'result':result}; db.commit(); return result

@app.get('/api/v1/audit')
def audit_list(a:Actor=Depends(actor),db=Depends(db_for)):
    if a.role in ['relationship_manager','credit_analyst']: raise HTTPException(403,'Organization-wide audit access required')
    return {'events':[serialize(r) for r in rows(db,a,'audit')],'overrides':[serialize(r) for r in rows(db,a,'override')],'memberships':[serialize(r) for r in rows(db,a,'membership')],'notifications':[serialize(r) for r in rows(db,a,'notification') if r.data.get('user_id')==a.id]}

@app.get('/api/v1/jobs/{id}')
def job_status(id:str,a:Actor=Depends(actor),db=Depends(db_for)):
    r=get(db,a,id,'job'); case_access(a,get(db,a,r.parent_id,'application')); d=serialize(r); d.pop('snapshot',None); return d

@app.get('/api/v1/jobs/{id}/events')
async def job_events(id:str,a:Actor=Depends(actor)):
    async def stream():
        for _ in range(120):
            with Session() as db:
                scope(db,a.org); data=job_status(id,a,db)
            yield 'data: '+json.dumps(data,default=str)+'\n\n'
            if data['status'] in ['completed','failed']: return
            await asyncio.sleep(2)
    return StreamingResponse(stream(),media_type='text/event-stream')

@app.post('/api/v1/transactions/{id}/review')
def transaction_review(id:str,body:dict,a:Actor=Depends(actor),db=Depends(db_for)):
    a.require('review'); tx=get(db,a,id,'transaction',True); c=get(db,a,tx.parent_id,'application',True); case_access(a,c); check_version(tx,body['expected_version'])
    if body.get('category') not in ['operating','transfer','financing','tax','debt_service','unclassified']: raise HTTPException(422,'Invalid transaction category')
    before=dict(tx.data); tx.data={**before,'category':body['category'],'excluded':bool(body.get('excluded')),'reviewer':a.name}
    c.data={**c.data,'evidence_revision':c.data.get('evidence_revision',0)+1,'assessment_stale':True}
    automatic_job=assessment_job(db,a,c,'evidence_updated')
    audit(db,a,'transaction.reviewed',c.id,before,tx.data); db.commit(); dispatch_assessment(db,a,automatic_job); return serialize(tx)


@app.get('/api/v1/products')
def products(a:Actor=Depends(actor),db=Depends(db_for)): return catalog(db,a)

@app.post('/api/v1/products')
def save_product(body:dict,a:Actor=Depends(actor),db=Depends(db_for),idempotency_key:str=Header()):
    a.require('override')
    idem,replay=idempotent(db,a,idempotency_key,{'operation':'save_product',**body})
    if replay: return idem.data['result']
    p=validate_product(body.get('product',{}))
    if p['key'] not in ACTIVE_PRODUCTS or p['borrower_type']!='business': raise HTTPException(422,'Only MSME and Enterprise business facilities are available')
    allowed={d['key'] for d in DOCUMENTS+EXTRA_DOCS}
    if not set(p['documents'])<=allowed: raise HTTPException(422,'Unknown document requirement')
    old=next((x for x in catalog(db,a) if x['key']==p['key']),None)
    if body.get('expected_version',0)!=(old or {}).get('revision',0): raise HTTPException(409,'Product changed; reload before saving')
    if len(body.get('reason','').strip())<10: raise HTTPException(422,'Explain the product terms change in at least 10 characters')
    existing=next((r for r in rows(db,a,'product') if r.data['key']==p['key']),None)
    if existing:
        existing=get(db,a,existing.id,'product',True); check_version(existing,body['expected_version']); existing.data=dict(p); db.flush(); r=existing
    else: r=add(db,a,'product',dict(p),id='product-'+a.org+'-'+p['key'])
    audit(db,a,'product.terms_changed',r.id,before=old,after=p,reason=body['reason'])
    result={**r.data,'revision':r.version};idem.data={**idem.data,'result':result};db.commit();return result

@app.post('/api/v1/products/quote')
def product_quote(body:dict,a:Actor=Depends(actor),db=Depends(db_for)):
    p=next((p for p in catalog(db,a) if p['key']==body.get('product')),None)
    if not p: raise HTTPException(422,'Unknown product')
    return quote(p,body.get('amount'),body.get('tenure'))

@app.post('/api/v1/applications/{id}/bureau')
def manual_bureau(id:str,body:dict,a:Actor=Depends(actor),db=Depends(db_for),idempotency_key:str=Header()):
    a.require('review');case=get(db,a,id,'application',True);case_access(a,case)
    idem,replay=idempotent(db,a,idempotency_key,{'operation':'manual_bureau','case':id,**body})
    if replay:return idem.data['result']
    check_version(case,body.get('expected_version'))
    if len(body.get('source_text','').strip())<10: raise HTTPException(422,'Provide the report reference and source explanation')
    if not body.get('subject_name','').strip() or body.get('subject_role') not in ['applicant','coapplicant','guarantor','promoter','business']: raise HTTPException(422,'Identify whose credit report this is')
    report_date=date.fromisoformat(body.get('bureau_report_date',''))
    if report_date>date.today(): raise HTTPException(422,'Report date cannot be in the future')
    if body.get('document_id'):
        doc=get(db,a,body['document_id'],'document')
        if doc.parent_id!=id: raise HTTPException(422,'Source document belongs to another application')
    values={'bureau_report_date':report_date.isoformat()}
    for key,lo,hi in [('promoter_cibil_score',300,900),('commercial_cibil_rank',1,10),('max_dpd',0,99999),('overdue_amount',0,1000000000000)]:
        v=body.get(key)
        if v in [None,'']: values[key]=None; continue
        d=decimal(v)
        if not lo<=d<=hi or (key!='overdue_amount' and d!=d.to_integral_value()): raise HTTPException(422,'Invalid '+key.replace('_',' '))
        values[key]=str(d)
    if body['subject_role']=='business' and values['promoter_cibil_score'] is not None: raise HTTPException(422,'A business report uses commercial rank, not a personal score')
    if body['subject_role']!='business' and values['commercial_cibil_rank'] is not None: raise HTTPException(422,'Commercial rank belongs to a business report')
    # Separate subjects remain in report history; only applicant/promoter/business feed primary case checks.
    report=add(db,a,'bureau_report',{**values,'subject_name':body['subject_name'],'subject_role':body['subject_role'],'source_text':body['source_text'],'document_id':body.get('document_id'),'entry_method':'manual','reviewer':a.name,'reviewer_id':a.id},id)
    if body['subject_role'] in ['applicant','promoter','business']:
        for key,value in values.items():
            if key=='commercial_cibil_rank' and body['subject_role']!='business': continue
            if key=='promoter_cibil_score' and body['subject_role']=='business': continue
            add(db,a,'fact',{'key':('commercial_'+key if body['subject_role']=='business' and key!='commercial_cibil_rank' else key),'value':value,'verified':True,'entry_method':'manual','reviewer':a.name,'reviewer_id':a.id,'source_text':body['source_text'],'document_id':body.get('document_id'),'bureau_report_id':report.id,'subject_role':body['subject_role']},id)
    case.data={**case.data,'evidence_revision':case.data.get('evidence_revision',0)+1,'assessment_stale':True}
    automatic_job=assessment_job(db,a,case,'evidence_updated')
    audit(db,a,'bureau.manually_recorded',id,after=report.data)
    result=serialize(report);idem.data={**idem.data,'result':result};db.commit(); dispatch_assessment(db,a,automatic_job);return result

@app.get('/api/v1/notifications')
def notifications(a:Actor=Depends(actor),db=Depends(db_for)):
    visible=[]
    for r in rows(db,a,'notification'):
        if r.data.get('user_id')!=a.id: continue
        case=get(db,a,r.parent_id,'application')
        if a.role in ['relationship_manager','credit_analyst'] and a.id not in [case.data.get('owner_id'),case.data.get('created_by')]: continue
        visible.append({**serialize(r),'application_id':r.parent_id,'reference':case.data['reference']})
    return visible

@app.post('/api/v1/notifications/{id}/read')
def read_notification(id:str,a:Actor=Depends(actor),db=Depends(db_for)):
    r=get(db,a,id,'notification',True)
    if r.data.get('user_id')!=a.id: raise HTTPException(404,'Notification not found')
    case_access(a,get(db,a,r.parent_id,'application'))
    if not r.data.get('read'): r.data={**r.data,'read':True,'read_at':now().isoformat()}
    db.commit();return serialize(r)

@app.post('/api/v1/applications/{id}/debt-schedule')
def review_debt_schedule(id:str,body:dict,a:Actor=Depends(actor),db=Depends(db_for),idempotency_key:str=Header()):
    a.require('review');case=get(db,a,id,'application',True);case_access(a,case)
    idem,replay=idempotent(db,a,idempotency_key,{'operation':'review_debt_schedule','case':id,**body})
    if replay:return idem.data['result']
    check_version(case,body.get('expected_version'))
    if body.get('complete') is not True or len(body.get('source_text','').strip())<10: raise HTTPException(422,'Confirm the complete debt schedule and provide its source')
    report_date=date.fromisoformat(body.get('report_date',''))
    if report_date>date.today():raise HTTPException(422,'Report date cannot be in the future')
    loans=body.get('loans')
    if not isinstance(loans,list) or len(loans)>100:raise HTTPException(422,'Provide at most 100 loans')
    if not loans and body.get('no_existing_loans') is not True:raise HTTPException(422,'Explicitly confirm no existing loans')
    total=decimal(0);normalized=[]
    for loan in loans:
        if not str(loan.get('lender','')).strip() or loan.get('status') not in ['active','closed']:raise HTTPException(422,'Lender and loan status required')
        payment=decimal(loan.get('monthly_emi'));outstanding=decimal(loan.get('outstanding'))
        if payment<0 or outstanding<0:raise HTTPException(422,'EMI and outstanding must be non-negative')
        dpd=loan.get('dpd');dpd=None if dpd in ['',None] else decimal(dpd)
        if dpd is not None and (dpd<0 or dpd!=dpd.to_integral_value()):raise HTTPException(422,'Days past due must be a non-negative whole number')
        if loan['status']=='active':total+=payment
        normalized.append({'lender':str(loan['lender'])[:180],'loan_type':str(loan.get('loan_type',''))[:100],'monthly_emi':str(payment),'outstanding':str(outstanding),'dpd':str(dpd) if dpd is not None else None,'status':loan['status'],'repayment_history':str(loan.get('repayment_history',''))[:3000]})
    doc_id=body.get('document_id') or None
    if doc_id and get(db,a,doc_id,'document').parent_id!=id:raise HTTPException(422,'Source belongs to another application')
    schedule=add(db,a,'debt_schedule',{'loans':normalized,'total_monthly_emi':str(total),'report_date':report_date.isoformat(),'source_text':body['source_text'],'document_id':doc_id,'complete':True,'reviewer':a.name,'reviewer_id':a.id},id)
    add(db,a,'fact',{'key':'existing_emi','value':str(total),'verified':True,'reviewer':a.name,'reviewer_id':a.id,'document_id':doc_id,'source_text':body['source_text'],'debt_schedule_id':schedule.id,'source_kind':'reviewed_debt_schedule','as_of':report_date.isoformat()},id)
    case.data={**case.data,'evidence_revision':case.data.get('evidence_revision',0)+1,'assessment_stale':True}
    automatic_job=assessment_job(db,a,case,'evidence_updated')
    audit(db,a,'debt_schedule.reviewed',id,after=schedule.data);result=serialize(schedule);idem.data={**idem.data,'result':result};db.commit(); dispatch_assessment(db,a,automatic_job);return result


@app.post('/api/v1/applications/{id}/evidence-explanations')
def explain_evidence(id:str,body:dict,a:Actor=Depends(actor),db=Depends(db_for),idempotency_key:str=Header()):
    a.require('upload'); case=get(db,a,id,'application',True); case_access(a,case)
    idem,replay=idempotent(db,a,idempotency_key,{'operation':'evidence_explanation','case':id,**body})
    if replay: return idem.data['result']
    check_version(case,body.get('expected_version'))
    policy=policy_current(db,a)
    checklist=readiness(rows(db,a,'document',id),policy.data if policy else {},case.data['product'],case.data.get('required_documents'))
    if body.get('document_type') not in {d['key'] for d in checklist}: raise HTTPException(422,'Choose a required document')
    if body.get('availability') not in ['available','not_yet_available','not_applicable']: raise HTTPException(422,'Choose an availability status')
    reason=str(body.get('reason','')).strip()
    if len(reason)<10: raise HTTPException(422,'Explain the document availability in at least 10 characters')
    entry=add(db,a,'evidence_explanation',{'document_type':body['document_type'],'availability':body['availability'],'reason':reason,'recorded_by':a.name,'recorded_by_id':a.id,'review_status':'pending_review'},id)
    case.data={**case.data,'evidence_revision':case.data.get('evidence_revision',0)+1,'assessment_stale':True}
    audit(db,a,'evidence.availability_recorded',id,after=entry.data)
    job=assessment_job(db,a,case,'evidence_updated')
    result=serialize(entry);idem.data={**idem.data,'result':result};db.commit();dispatch_assessment(db,a,job)
    return result
