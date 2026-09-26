import logging
from celery import Celery
from sqlalchemy import select
from .config import settings
from .db import Session, Record, scope, now
from .auth import Actor
from .service import add, get, audit, facts_for, policy_current, assessment_job
from .engine import evaluate
from .appraisal import structured_appraisal
from .providers import assess, ProviderUnavailable
from .extraction import extract, csv_transactions

celery=Celery('credit',broker=settings.redis_url,backend=settings.redis_url)
celery.conf.update(task_track_started=True,worker_prefetch_multiplier=1,task_acks_late=True,broker_connection_retry_on_startup=True,task_routes={'credit.extract_job':{'queue':'extraction'},'credit.assess_job':{'queue':'assessment'}})

def run_job(job_id,org,kind):
    with Session() as db:
        scope(db,org); job=db.scalar(select(Record).where(Record.id==job_id,Record.org_id==org).with_for_update())
        if not job or job.data['status'] in ['completed','running']: return
        job.data={**job.data,'status':'running','progress':15}; db.commit()
        actor=Actor(job.data['actor_id'],org,job.data['role'],job.data['actor'])
        followup=None
        try:
            case=get(db,actor,job.parent_id,'application')
            if kind=='extract':
                doc=get(db,actor,job.data['document_id'],'document')
                policy=policy_current(db,actor)
                fields=policy.data['fields'] if policy else []
                if doc.data['filename'].lower().endswith('.csv'):
                    from pathlib import Path
                    extracted=[]; transactions=csv_transactions(Path(doc.data['path']).read_bytes(),doc.data.get('mapping'))
                else: extracted,transactions=extract(doc.data['path'],fields)
                case=get(db,actor,job.parent_id,'application',lock=True)
                for f in extracted:
                    add(db,actor,'fact',{**f,'document_id':doc.id,'extraction_model':settings.gemini_model if settings.gemini_api_key and settings.extraction_provider in ['auto','gemini'] else settings.ollama_model},case.id)
                for tx in transactions: add(db,actor,'transaction',{**tx,'document_id':doc.id,'excluded':False},case.id)
                doc.data={**doc.data,'status':'review_required','field_count':len(extracted),'transaction_count':len(transactions)}
                case.data={**case.data,'evidence_revision':case.data.get('evidence_revision',0)+1,'assessment_stale':True}
                if not extracted and not transactions: add(db,actor,'exception',{'title':'No matching fields extracted','severity':'warning','status':'open','owner':case.data['owner'],'detail':'Review the document type and field definitions, or enter a source-linked correction.'},case.id)
                for tx in transactions:
                    if tx['duplicate_candidate']: add(db,actor,'exception',{'title':'Possible duplicate transaction','severity':'warning','status':'open','owner':case.data['owner'],'detail':f"Review CSV row {tx['row']} before excluding it."},case.id)
                audit(db,actor,'document.extracted',doc.id,after={'fields':len(extracted),'transactions':len(transactions)})
                followup=assessment_job(db,actor,case,'extraction_completed')
                result={'document_id':doc.id,'fields':len(extracted),'transactions':len(transactions)}
            else:
                # Input snapshot was captured atomically when the job was submitted.
                snapshot=job.data['snapshot']; policy=snapshot['policy']; facts=snapshot['facts']
                calculation=evaluate(policy,facts,snapshot['product'],snapshot.get('periods'))
                provider_error=None; decision=None
                try: decision=assess({'evidence_explanations':snapshot.get('evidence_explanations',[]),'bureau_report_history':snapshot.get('bureau_reports',[]),'facts':facts,'metrics':calculation['metrics'],'rules':calculation['rules'],'unverified_fields':snapshot['unverified'],'missing_documents':snapshot.get('missing_documents',[]),'product':snapshot['product']},policy)
                except ProviderUnavailable as e: provider_error=str(e)
                gates=[]
                if snapshot.get('product_policy_covered') is False: gates.append('No product-specific credit policy configured; configure and publish applicable rules')
                if calculation['blocking']: gates.append(f"{calculation['blocking']} blocking policy checks")
                if snapshot['unverified']: gates.append('Unverified extracted facts')
                if snapshot.get('missing_documents'): gates.append('Missing required documents: '+', '.join(snapshot['missing_documents']))
                if not decision: gates.append('Decision model unavailable')
                elif decision.get('confidence') is not None and decision['confidence']<policy.get('confidence_threshold',.7): gates.append('Jev requires human review at configured confidence threshold')
                assessment_data={'snapshot':snapshot,**calculation,'decision':decision,'provider_error':provider_error,'gates':gates,'recommendation':decision['recommendation'] if decision else None,'synthetic':case.data.get('synthetic',False)}
                assessment=add(db,actor,'assessment',{**assessment_data,'structured_output':structured_appraisal(assessment_data)},case.id)
                case=get(db,actor,job.parent_id,'application',lock=True)
                stale=case.data.get('evidence_revision',0)!=snapshot['evidence_revision']
                if not stale: case.data={**case.data,'latest_assessment_id':assessment.id,'assessment_stale':stale,'blocking':calculation['blocking'],'status':case.data['status'] if job.data.get('trigger','manual')!='manual' or case.data['status'] in ['approved','declined','withdrawn'] else 'in_review','last_assessed_at':now().isoformat()}
                audit(db,actor,'assessment.completed',case.id,after={'assessment_id':assessment.id,'model_available':bool(decision),'stale':stale})
                result={'assessment_id':assessment.id}
            job.data={**job.data,'status':'completed','progress':100,'result':result}; db.commit()
            dispatch_assessment(db,actor,followup)
        except Exception as e:
            db.rollback(); job=get(db,actor,job_id,'job',lock=True)
            logging.getLogger(__name__).error('Processing failed: job=%s error_type=%s', job_id, type(e).__name__)
            operation='Assessment' if kind=='assess' else 'Document processing'
            message=f'{operation} was interrupted by a system error. Please retry or contact your administrator. This is not a credit policy finding.'
            job.data={**job.data,'status':'failed','progress':0,'error':message,'error_type':type(e).__name__}
            add(db,actor,'exception',{'title':f'{operation} could not complete','severity':'warning','status':'open','owner':actor.name,'detail':message,'job_id':job_id},job.parent_id)
            db.commit()

@celery.task(name='credit.extract_job')
def extract_job(job_id,org): run_job(job_id,org,'extract')
@celery.task(name='credit.assess_job')
def assess_job(job_id,org): run_job(job_id,org,'assess')


def dispatch_assessment(db, actor, job):
    if job is None: return
    try: assess_job.delay(job.id,actor.org)
    except Exception:
        job.data={**job.data,'status':'failed','error':'Automatic assessment could not be queued. Restore Redis and use Run assessment to retry.'}
        add(db,actor,'exception',{'title':'Automatic assessment unavailable','severity':'warning','status':'open','owner':actor.name,'detail':job.data['error'],'job_id':job.id},job.parent_id)
        db.commit()
