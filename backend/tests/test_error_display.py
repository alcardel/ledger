from types import SimpleNamespace
from app.db import serialize, now


def test_legacy_failure_display_preserves_original_record():
    raw='(psycopg.errors.RaiseException) Immutable history cannot be changed [SQL: UPDATE records]'
    record=SimpleNamespace(id='test',version=1,created_at=now(),updated_at=now(),kind='exception',data={'title':'Assess could not complete','job_id':'job','detail':raw,'status':'open'})
    result=serialize(record)
    assert 'SQL' not in result['detail']
    assert 'retry' in result['detail']
    assert result['title']=='Assessment could not complete'
    assert record.data['detail']==raw
    record.data.update(status='resolved',recovery_job_id='retry')
    assert 'completed successfully' in serialize(record)['detail']


def test_audit_nested_diagnostics_are_not_exposed():
    record=SimpleNamespace(id='test',version=1,created_at=now(),updated_at=now(),kind='audit',data={'before':{'detail':'Query-invoked autoflush [SQL: UPDATE records]'},'after':{'detail':'Business credit rank unavailable'}})
    result=serialize(record)
    assert 'SQL' not in result['before']['detail']
    assert result['after']['detail']=='Business credit rank unavailable'
