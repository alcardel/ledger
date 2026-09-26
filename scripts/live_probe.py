import httpx,uuid,json
from pathlib import Path
BASE='http://localhost:8000/api/v1'
h={'Authorization':'Bearer local-demo-change-me'}
with httpx.Client(timeout=20,headers=h) as c:
    d=c.get(BASE+'/applications/case-001').json()
    response=c.post(BASE+'/applications/case-001/assessments',json={'expected_version':d['application']['version']},headers={'Idempotency-Key':str(uuid.uuid4())});response.raise_for_status()
    j=response.json();Path('artifacts/live-job.json').write_text(json.dumps({'id':j['id']}));print('Live local decision assessment queued:',j['id'])
