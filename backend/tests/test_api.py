import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app,db_for
from app.auth import actor,Actor
from app.db import Base,Record
from app.defaults import default_policy

@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr("app.tasks.assess_job.delay",lambda *args: None)
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine); Session=sessionmaker(engine,expire_on_commit=False)
    current={'actor':Actor('admin','bank-a','org_admin','Admin')}
    def db_dep():
        with Session() as db:
            try:yield db
            except:db.rollback();raise
    app.dependency_overrides[db_for]=db_dep
    app.dependency_overrides[actor]=lambda:current['actor']
    with Session() as db:
        db.add(Record(id='case',org_id='bank-a',kind='application',data={'borrower':'Test Business','reference':'CR-1','product':'term_loan','amount':'1000','status':'in_review','created_by':'admin','owner_id':'admin','owner':'Admin','evidence_revision':1,'assessment_stale':True}))
        db.add(Record(id='other',org_id='bank-b',kind='application',data={'borrower':'Private','status':'draft'}))
        db.add(Record(id='policy',org_id='bank-a',kind='policy',data=default_policy()))
        db.add(Record(id='assessment',org_id='bank-a',kind='assessment',parent_id='case',data={'rules':[{'result':'fail','id':'coverage'}],'gates':['missing evidence'],'recommendation':'request_information'}))
        db.commit()
    yield TestClient(app),Session,current
    app.dependency_overrides.clear()

def post(client,url,body,key=None):return client.post('/api/v1'+url,json=body,headers={'Idempotency-Key':key or str(uuid.uuid4())})
def override_body():return {'expected_version':1,'action':'decision','disposition':'approved','reason_category':'Evidence reviewed','justification':'Additional source reviewed by administrator','sanctioned_amount':'900'}

def test_admin_override_preserves_failed_checks_and_is_idempotent(env):
    client,S,current=env;b=override_body();r=post(client,'/applications/case/overrides',b,'same')
    assert r.status_code==200,r.text
    second=post(client,'/applications/case/overrides',b,'same');assert second.json()['id']==r.json()['id']
    with S() as db:
        assert db.get(Record,'case').data['status']=='approved'
        assert db.get(Record,'assessment').data['rules'][0]['result']=='fail'
        assert len(list(db.scalars(select(Record).where(Record.kind=='override'))))==1
        assert len(list(db.scalars(select(Record).where(Record.kind=='audit'))))==1
        assert len(list(db.scalars(select(Record).where(Record.kind=='notification'))))==1

def test_override_requires_reason_and_current_version(env):
    c,S,a=env;b=override_body();b['justification']=''
    assert post(c,'/applications/case/overrides',b).status_code==422
    b=override_body();b['expected_version']=42
    assert post(c,'/applications/case/overrides',b).status_code==409
    with S() as db: assert db.get(Record,'case').data['status']=='in_review'

def test_cross_tenant_and_ordinary_role_denied(env):
    c,S,current=env
    assert c.get('/api/v1/applications/other').status_code==404
    assert post(c,'/applications/other/overrides',override_body()).status_code==404
    current['actor']=Actor('analyst','bank-a','credit_analyst','Analyst')
    assert post(c,'/applications/case/overrides',override_body()).status_code==403
    assert c.get('/api/v1/applications/case').status_code==403

def test_self_approval_uses_explicit_override_and_policy_publication(env):
    c,S,a=env
    assert post(c,'/applications/case/decisions',override_body()).status_code==403
    r=post(c,'/policies',default_policy());assert r.status_code==200,r.text
    id=r.json()['id'];t=post(c,f'/policies/{id}/test',{});assert t.status_code==200,t.text
    version=t.json()['version']
    assert post(c,f'/policies/{id}/publish',{'expected_version':version}).status_code==422
    result=post(c,f'/policies/{id}/publish',{'expected_version':version,'reason_category':'Policy review','justification':'Reviewed synthetic portfolio simulation'})
    assert result.status_code==200,result.text

def test_idempotency_payload_mismatch_and_unresolved_gates(env):
    c,S,current=env;b=override_body();post(c,'/applications/case/overrides',b,'key')
    b['disposition']='declined';assert post(c,'/applications/case/overrides',b,'key').status_code==409
    current['actor']=Actor('approver','bank-a','credit_approver','Approver')
    with S() as db:
        cse=db.get(Record,'case');cse.data={**cse.data,'status':'in_review'};db.commit();version=cse.version
    assert post(c,'/applications/case/decisions',{'expected_version':version,'disposition':'approved','justification':'Reviewed credit application'}).status_code==422

def test_catalog_pricing_and_snapshot(env):
    c,S,current=env
    ps=c.get('/api/v1/products').json(); assert len(ps)==2
    p=next(p for p in ps if p['key']=='term_loan')
    p['base_rate']='8';p['method']='flat'
    r=post(c,'/products',{'product':p,'expected_version':0,'reason':'Set illustrative business pricing'})
    assert r.status_code==200,r.text
    r=post(c,'/applications',{'borrower':'Sample Enterprise','product':'term_loan','amount':'100000','tenure':12,'rate':'99'})
    assert r.status_code==200,r.text
    assert r.json()['rate']=='8' and r.json()['pricing']['total_interest']=='8000.00'
    assert 'projected_cashflow' in r.json()['required_documents']
    assert post(c,'/products',{'product':p,'expected_version':0,'reason':'Stale settings must not replace current terms'}).status_code==409
    current['actor']=Actor('officer','bank-a','credit_analyst','Officer')
    assert post(c,'/products',{'product':p,'expected_version':1,'reason':'Officer cannot alter interest terms'}).status_code==403

def test_manual_bureau_history_missing_and_replay(env):
    c,S,current=env
    body={'expected_version':1,'subject_name':'Borrower','subject_role':'applicant','source_text':'Manually reviewed report reference ABC123','bureau_report_date':'2026-09-01','promoter_cibil_score':'740','max_dpd':'0','overdue_amount':'0'}
    r=post(c,'/applications/case/bureau',body,'bureau-key');assert r.status_code==200,r.text
    assert post(c,'/applications/case/bureau',body,'bureau-key').json()['id']==r.json()['id']
    assert post(c,'/applications/case/bureau',body).status_code==409
    detail=c.get('/api/v1/applications/case').json()
    assert detail['facts']['promoter_cibil_score']=='740'
    assert detail['sources']['promoter_cibil_score']['entry_method']=='manual'
    body['expected_version']=detail['application']['version'];body['promoter_cibil_score']=''
    assert post(c,'/applications/case/bureau',body).status_code==200
    detail=c.get('/api/v1/applications/case').json()
    assert detail['facts']['promoter_cibil_score'] is None
    assert len(detail['bureau_report'])==2 and detail['application']['assessment_stale']

def test_business_bureau_does_not_replace_personal_report(env):
    c,S,current=env
    personal={'expected_version':1,'subject_name':'Promoter','subject_role':'promoter','source_text':'Personal credit report PERSONAL123','bureau_report_date':'2026-08-01','promoter_cibil_score':'730','max_dpd':'20'}
    assert post(c,'/applications/case/bureau',personal).status_code==200
    detail=c.get('/api/v1/applications/case').json()
    business={'expected_version':detail['application']['version'],'subject_name':'Test Business','subject_role':'business','source_text':'Commercial report BUSINESS123','bureau_report_date':'2026-09-01','commercial_cibil_rank':'3','max_dpd':'0'}
    assert post(c,'/applications/case/bureau',business).status_code==200
    facts=c.get('/api/v1/applications/case').json()['facts']
    assert facts['promoter_cibil_score']=='730' and facts['max_dpd']=='20'
    assert facts['bureau_report_date']=='2026-08-01'
    assert facts['commercial_cibil_rank']=='3' and facts['commercial_bureau_report_date']=='2026-09-01'

def test_notifications_are_personal_and_reads_persist(env):
    c,S,current=env
    with S() as db:
        db.add(Record(id='mine',org_id='bank-a',kind='notification',parent_id='case',data={'user_id':'admin','message':'An assigned application changed','read':False}))
        db.add(Record(id='theirs',org_id='bank-a',kind='notification',parent_id='case',data={'user_id':'another-user','message':'Private notification','read':False}))
        db.add(Record(id='foreign-note',org_id='bank-b',kind='notification',parent_id='other',data={'user_id':'admin','message':'Other organization','read':False}))
        db.commit()
    assert [n['id'] for n in c.get('/api/v1/notifications').json()]==['mine']
    assert post(c,'/notifications/theirs/read',{}).status_code==404
    assert post(c,'/notifications/foreign-note/read',{}).status_code==404
    first=post(c,'/notifications/mine/read',{});assert first.status_code==200
    second=post(c,'/notifications/mine/read',{});assert second.json()['read_at']==first.json()['read_at']
    assert c.get('/api/v1/notifications').json()[0]['read'] is True

def test_debt_schedule_updates_emi_without_inventing_history(env):
    c,S,current=env
    body={'expected_version':1,'report_date':'2026-09-01','complete':True,'source_text':'Reviewed lender statements for all existing loans','loans':[{'lender':'Lender A','monthly_emi':'12000','outstanding':'250000','status':'active','dpd':'0','repayment_history':'August instalment paid on time per report'},{'lender':'Lender B','monthly_emi':'5000','outstanding':'0','status':'closed','dpd':None}]}
    first=post(c,'/applications/case/debt-schedule',body,'debt-idem');assert first.status_code==200,first.text
    assert first.json()['total_monthly_emi']=='12000'
    assert post(c,'/applications/case/debt-schedule',body,'debt-idem').json()['id']==first.json()['id']
    detail=c.get('/api/v1/applications/case').json();assert detail['facts']['existing_emi']=='12000'
    assert detail['debt_schedule'][0]['loans'][1]['dpd'] is None
    assert detail['application']['assessment_stale']
    empty={**body,'expected_version':detail['application']['version'],'loans':[]}
    assert post(c,'/applications/case/debt-schedule',empty).status_code==422
    empty['no_existing_loans']=True
    assert post(c,'/applications/case/debt-schedule',empty).status_code==200
    detail=c.get('/api/v1/applications/case').json();assert detail['facts']['existing_emi']=='0'
    assert len(detail['debt_schedule'])==2

def test_proposed_emi_uses_saved_quote_not_assumed_existing_debt(env):
    c,S,current=env
    created=post(c,'/applications',{'borrower':'Repayment fixture','product':'term_loan','amount':'100000','tenure':12}).json()
    detail=c.get('/api/v1/applications/'+created['id']).json()
    assert detail['facts']['proposed_emi']==created['pricing']['monthly_payment']
    assert detail['facts']['requested_amount']=='100000'
    assert 'existing_emi' not in detail['facts'] and 'monthly_income' not in detail['facts']
    assert detail['sources']['proposed_emi']['source_kind']=='application_terms'

@pytest.mark.parametrize('path',['approval-workbench/applications','document-review/applications','financial-spreading/applications','cash-flow/applications','employee-assignments'])
def test_module_queues_keep_case_visibility(env,path):
    client,S,current=env
    result=client.get('/api/v1/'+path)
    assert result.status_code==200,result.text
    assert [r['id'] for r in result.json()]==['case']
    current['actor']=Actor('unassigned','bank-a','credit_analyst','Analyst')
    assert client.get('/api/v1/'+path).json()==[]

def test_business_only_scope_keeps_history_and_enterprise_segment(env):
    c,S,current=env
    with S() as db:
        db.add(Record(id='retired-retail',org_id='bank-a',kind='application',data={'borrower':'Historical retail','product':'car_loan','status':'draft','amount':'100000','owner_id':'admin'}));db.commit()
    assert {p['key'] for p in c.get('/api/v1/products').json()}=={'term_loan','working_capital'}
    assert all(r['id']!='retired-retail' for r in c.get('/api/v1/applications').json())
    with S() as db: assert db.get(Record,'retired-retail') is not None
    assert post(c,'/applications',{'borrower':'Retail blocked','product':'personal_loan','amount':'100000','tenure':12}).status_code==422
    result=post(c,'/applications',{'borrower':'Enterprise fixture','product':'term_loan','business_segment':'enterprise','amount':'100000','tenure':12})
    assert result.status_code==200,result.text
    assert result.json()['business_segment']=='enterprise'
    assert post(c,'/applications',{'borrower':'Invalid segment','product':'term_loan','business_segment':'retail','amount':'100000','tenure':12}).status_code==422


def test_document_update_automatically_snapshots_once(env,monkeypatch):
    c,S,current=env
    sent=[]
    monkeypatch.setattr('app.tasks.assess_job.delay',lambda *args:sent.append(args))
    monkeypatch.setattr('app.main.inspect_file',lambda *args:{'locked':False})
    response=c.post('/api/v1/applications/case/documents',files={'file':('statement.csv',b'date,amount\n2026-01-01,100')},data={'document_type':'bank_statement'},headers={'Idempotency-Key':'upload-auto'})
    assert response.status_code==200,response.text
    replay=c.post('/api/v1/applications/case/documents',files={'file':('statement.csv',b'date,amount\n2026-01-01,100')},data={'document_type':'bank_statement'},headers={'Idempotency-Key':'upload-auto'})
    assert replay.status_code==200
    assert len(sent)==1
    with S() as db:
        jobs=list(db.scalars(select(Record).where(Record.kind=='job')))
        assert len(jobs)==1
        assert jobs[0].data['snapshot']['evidence_revision']==2
        assert jobs[0].data['trigger']=='evidence_updated'
        assert db.get(Record,'assessment').data['gates']==['missing evidence']


def test_automatic_completion_preserves_draft_and_history(env,monkeypatch):
    from app import tasks
    from app.service import assessment_job
    c,S,current=env
    monkeypatch.setattr(tasks,'Session',S)
    monkeypatch.setattr(tasks,'assess',lambda *args:{'recommendation':'refer','confidence':0.9})
    with S() as db:
        case=db.get(Record,'case');case.data={**case.data,'status':'draft'}
        job=assessment_job(db,current['actor'],case,'evidence_updated');db.commit();jid=job.id
    tasks.run_job(jid,'bank-a','assess')
    with S() as db:
        assert db.get(Record,jid).data['status']=='completed'
        assert db.get(Record,'case').data['status']=='draft'
        assert len(list(db.scalars(select(Record).where(Record.kind=='assessment'))))==2


def test_stale_automatic_run_cannot_replace_current_assessment(env,monkeypatch):
    from app import tasks
    from app.service import assessment_job
    c,S,current=env
    monkeypatch.setattr(tasks,'Session',S)
    monkeypatch.setattr(tasks,'assess',lambda *args:{'recommendation':'refer','confidence':0.9})
    with S() as db:
        case=db.get(Record,'case')
        job=assessment_job(db,current['actor'],case,'evidence_updated');db.commit();jid=job.id
        case.data={**case.data,'evidence_revision':2,'latest_assessment_id':'newer'};db.commit()
    tasks.run_job(jid,'bank-a','assess')
    with S() as db:
        assert db.get(Record,jid).data['status']=='completed'
        assert db.get(Record,'case').data['latest_assessment_id']=='newer'
        assert db.get(Record,'case').data['assessment_stale'] is True


def test_extraction_completion_queues_fresh_snapshot(env,monkeypatch):
    from app import tasks
    from app.service import add
    c,S,current=env
    monkeypatch.setattr(tasks,'Session',S)
    monkeypatch.setattr(tasks,'extract',lambda *args:([{'key':'revenue','value':'123','verified':False}],[]))
    sent=[]
    monkeypatch.setattr(tasks.assess_job,'delay',lambda *args:sent.append(args))
    with S() as db:
        doc=add(db,current['actor'],'document',{'filename':'test.pdf','path':'unused','status':'uploaded','document_type':'financial_statement'},'case')
        job=add(db,current['actor'],'job',{'type':'extraction','status':'queued','document_id':doc.id,'actor_id':'admin','actor':'Admin','role':'org_admin'},'case');db.commit();jid=job.id
    tasks.run_job(jid,'bank-a','extract')
    with S() as db:
        assert db.get(Record,jid).data['status']=='completed',db.get(Record,jid).data.get('error')
    assert len(sent)==1
    with S() as db:
        snapshot=db.get(Record,sent[0][0]).data['snapshot']
        assert snapshot['facts']['revenue']=='123'
        assert 'revenue' in snapshot['unverified']
        assert snapshot['evidence_revision']==2


def test_availability_explanation_keeps_document_gate_and_history(env):
    c,S,current=env
    b={'expected_version':1,'document_type':'gst_return','availability':'not_yet_available','reason':'New business has not completed its first filing period.'}
    response=post(c,'/applications/case/evidence-explanations',b,'explain')
    assert response.status_code==200,response.text
    assert post(c,'/applications/case/evidence-explanations',b,'explain').json()['id']==response.json()['id']
    with S() as db:
        jobs=list(db.scalars(select(Record).where(Record.kind=='job')))
        assert len(jobs)==1
        assert 'GST returns / turnover summary' in jobs[0].data['snapshot']['missing_documents']
        assert jobs[0].data['snapshot']['evidence_explanations'][0]['review_status']=='pending_review'
        assert db.get(Record,'assessment').data['gates']==['missing evidence']
    b['expected_version']=1
    assert post(c,'/applications/case/evidence-explanations',b).status_code==409
    assert post(c,'/applications/other/evidence-explanations',b).status_code==404
