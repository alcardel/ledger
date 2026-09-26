"""Idempotently onboard five fictional enterprise applications in the local demo."""
import uuid
import httpx
from app.config import settings

CASES=[
 ('Asterion Industrial Systems','term_loan','250000000',60,'Industrial manufacturing','Mumbai'),
 ('Northvale Logistics','working_capital','150000000',12,'Logistics & warehousing','Pune'),
 ('Cresthaven Healthcare','term_loan','200000000',84,'Healthcare services','Bengaluru'),
 ('Bluecrest Packaging','working_capital','100000000',12,'Packaging & materials','Ahmedabad'),
 ('Everline Energy Systems','term_loan','300000000',84,'Energy infrastructure','Mumbai'),
]
def run():
 if settings.auth_mode!='demo': raise SystemExit('This sample onboarding script requires local demo mode.')
 with httpx.Client(base_url='http://localhost:8000/api/v1',headers={'Authorization':'Bearer '+settings.demo_token,'X-Demo-Role':'relationship_manager'},timeout=30) as client:
  me=client.get('/me');me.raise_for_status()
  existing=client.get('/applications');existing.raise_for_status()
  existing={x['borrower']:x for x in existing.json() if x.get('business_segment')=='enterprise'}
  for name,product,amount,tenure,sector,branch in CASES:
   if name in existing:
    case=existing[name]
   else:
    response=client.post('/applications',headers={'Idempotency-Key':str(uuid.uuid5(uuid.NAMESPACE_URL,'ledger/enterprise-onboarding/v1/'+name))},json={'borrower':name,'business_segment':'enterprise','product':product,'amount':amount,'tenure':tenure,'sector':sector,'branch':branch})
    response.raise_for_status();case=response.json()
   detail=client.get('/applications/'+case['id']);detail.raise_for_status();detail=detail.json()
   assert detail['application']['business_segment']=='enterprise'
   assert detail['application']['owner_id']==me.json()['id']
   print(name+' | '+product+' | INR '+amount+' | '+detail['application']['status']+' | '+str(len(detail['document_checklist']))+' required documents')
  dashboard=client.get('/dashboard');dashboard.raise_for_status()
  names={c['borrower'] for c in dashboard.json()['applications'] if c.get('business_segment')=='enterprise'}
  assert {c[0] for c in CASES}<=names
  print('Verified all five enterprise applications appear in the owner dashboard.')
if __name__=='__main__':run()
