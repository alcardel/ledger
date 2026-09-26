"""Checks against the local, least-privilege PostgreSQL role. All writes roll back."""
import pytest
from sqlalchemy import text
from app.db import engine

def test_database_role_cannot_bypass_rls():
    with engine.connect() as c:
        role=c.execute(text('SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()
        assert role==(False,False)
        c.execute(text("SELECT set_config('app.org_id','unrelated-test-tenant',true)"))
        assert c.scalar(text('SELECT count(*) FROM records'))==0

def test_database_rejects_cross_tenant_insert():
    with engine.connect() as c:
        t=c.begin();c.execute(text("SELECT set_config('app.org_id','test-a',true)"))
        with pytest.raises(Exception,match='row-level security'):
            c.execute(text("INSERT INTO records (id,org_id,kind,version,data,created_at,updated_at) VALUES ('test-cross-tenant','test-b','audit',1,'{}',now(),now())"))
        t.rollback()

def test_audit_is_immutable_in_database():
    with engine.connect() as c:
        t=c.begin();c.execute(text("SELECT set_config('app.org_id','test-a',true)"))
        c.execute(text("INSERT INTO records (id,org_id,kind,version,data,created_at,updated_at) VALUES ('test-audit','test-a','audit',1,'{}',now(),now())"))
        with pytest.raises(Exception,match='Immutable history'):
            c.execute(text("UPDATE records SET data='{}' WHERE id='test-audit'"))
        t.rollback()


def test_assessment_structured_output_is_inserted_atomically(monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app import tasks
    from app.db import Record,scope
    from app.auth import Actor
    from app.service import add,assessment_job
    from app.defaults import default_policy
    with engine.connect() as connection:
        transaction=connection.begin()
        S=sessionmaker(bind=connection,expire_on_commit=False,join_transaction_mode='create_savepoint')
        a=Actor('test-admin','test-assessment-atomic','org_admin','Test')
        try:
            with S() as db:
                scope(db,a.org)
                add(db,a,'policy',default_policy())
                case=add(db,a,'application',{'product':'working_capital','amount':'30000000','status':'in_review','evidence_revision':1})
                job=assessment_job(db,a,case,'test');db.commit();jobid=job.id
            monkeypatch.setattr(tasks,'Session',S)
            monkeypatch.setattr(tasks,'assess',lambda *args:{'recommendation':'request_information','confidence':None,'model':'test-stub'})
            tasks.run_job(jobid,a.org,'assess')
            with S() as db:
                scope(db,a.org);job=db.get(Record,jobid)
                assert job.data['status']=='completed',job.data.get('error')
                assessment=db.get(Record,job.data['result']['assessment_id'])
                assert assessment.data['structured_output']['unable_to_assess']
        finally:
            transaction.rollback()
