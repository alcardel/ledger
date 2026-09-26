"""Apply the requested 30/37/33 ownership mix to local business sample cases."""
from collections import Counter
from app.config import settings
from app.db import Session,scope
from app.auth import Actor
from app.service import rows,add,audit,override_case
from app.products import ACTIVE_PRODUCTS

TEAM=[('demo-relationship_manager','Aditi Rao','relationship_manager',30),('demo-credit_analyst','Rohan Mehta','credit_analyst',37),('demo-neha-kapoor','Neha Kapoor','relationship_manager',33)]
def run():
 if settings.auth_mode!='demo':raise SystemExit('Local sample setup requires demo mode.')
 actor=Actor('demo-org_admin','demo-bank','org_admin','Ananya Sharma')
 with Session() as db:
  scope(db,actor.org)
  members={r.data['user_id']:r for r in rows(db,actor,'membership')}
  for uid,name,role,_ in TEAM:
   if uid not in members:
    member=add(db,actor,'membership',{'user_id':uid,'name':name,'role':role,'synthetic':True})
    audit(db,actor,'membership.created',member.id,after=member.data,reason='Add named sample staff for requested ownership distribution')
   elif members[uid].data.get('name')!=name:
    member=members[uid];before=dict(member.data);member.data={**before,'name':name}
    audit(db,actor,'membership.updated',member.id,before=before,after=member.data,reason='Use the requested employee display name')
  cases=sorted([c for c in rows(db,actor,'application') if c.data.get('product') in ACTIVE_PRODUCTS],key=lambda c:c.id)
  total=len(cases);targets=[total*t[3]//100 for t in TEAM]
  order=sorted(range(3),key=lambda i:((total*TEAM[i][3])%100,-i),reverse=True)
  for i in order[:total-sum(targets)]:targets[i]+=1
  remaining=dict(zip([t[0] for t in TEAM],targets));assignment={};pending=[]
  # Retain current owners where possible, then fill the remaining workload quotas.
  for case in cases:
   owner=case.data.get('owner_id')
   if remaining.get(owner,0)>0:assignment[case.id]=owner;remaining[owner]-=1
   else:pending.append(case)
  for case in pending:
   owner=max(remaining,key=remaining.get);assignment[case.id]=owner;remaining[owner]-=1
  names={t[0]:t[1] for t in TEAM};changed=0
  for case in cases:
   uid=assignment[case.id];name=names[uid]
   if case.data.get('owner_id')!=uid or case.data.get('owner')!=name:
    override_case(db,actor,case,{'expected_version':case.version,'action':'reassign','owner_id':uid,'owner':name,'reason_category':'Workload distribution','justification':'User requested named owners Aditi Rao, Rohan Mehta and Neha Kapoor with an approximate 30% / 37% / 33% application allocation.'});changed+=1
   for ex in rows(db,actor,'exception',case.id):
    if ex.data.get('status')=='open' and (ex.data.get('owner')!=name or ex.data.get('owner_id')!=uid):
     before=dict(ex.data);ex.data={**before,'owner':name,'owner_id':uid}
     audit(db,actor,'exception.reassigned',case.id,before=before,after=ex.data,reason='Keep open exception ownership aligned with the requested customer assignment')
  counts=Counter(c.data['owner_id'] for c in cases)
  assert [counts[t[0]] for t in TEAM]==targets
  db.commit()
  for uid,name,_,target in TEAM:print(f'{name}: {counts[uid]} applications ({counts[uid]/total:.1%}); target {target}%')
  print(f'Updated {changed} assignments atomically with audit reasons; {total} active business applications checked.')
if __name__=='__main__':run()
