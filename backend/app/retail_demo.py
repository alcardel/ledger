"""Add sample retail products, a versioned illustrative policy, and synthetic evidence."""
from copy import deepcopy
from datetime import date
import hashlib
from reportlab.pdfgen import canvas
from .db import Session,scope,now
from .auth import Actor
from .service import rows,add,audit,policy_current
from .products import DEFAULTS,quote,EXTRA_DOCS
from .analytics import DOCUMENTS
from .defaults import f,op
from .config import ROOT

def run():
 a=Actor('demo-org_admin','demo-bank','org_admin','Ananya Sharma')
 with Session() as db:
  scope(db,a.org)
  if any(r.data.get('name')=='retail-products-v1' for r in rows(db,a,'demo_extension')):return
  current=policy_current(db,a);p=deepcopy(current.data)
  groups={'business':[x['key'] for x in DEFAULTS if x['borrower_type']=='business'],'retail':[x['key'] for x in DEFAULTS if x['borrower_type']!='business']}
  p.update(name='Retail & MSME Credit Framework',product_groups=groups,revision=p.get('revision',1)+1,published_at=now().isoformat(),created_by=a.id,author='Synthetic policy team')
  for m in p['metrics']:m['product']='business'
  for r in p['rules']:
   if r['id'] in ['liquidity','leverage','turnover','business_bureau_range','business_bureau_threshold']:r['product']='business'
  for key,name in [('monthly_income','Verified net monthly income'),('existing_emi','Existing monthly instalments'),('proposed_emi','Proposed monthly instalment'),('collateral_value','Verified collateral value')]:
   p['fields'].append(dict(key=key,label=name,type='number',unit='INR',product='both',instruction='Extract explicitly stated '+name.lower()+'; do not infer missing amounts.'))
  p['metrics'] += [dict(key='foir',label='Fixed obligations / income',unit='percent',product='retail',formula=op('mul',op('div',op('add',f('existing_emi'),f('proposed_emi')),f('monthly_income')),100)),dict(key='ltv',label='Loan / collateral value',unit='percent',product='retail',formula=op('mul',op('div',f('requested_amount'),f('collateral_value')),100))]
  p['rules'] += [dict(id='retail_affordability',name='Sample fixed obligations within 50% of income',product='retail',severity='blocking',condition={'field':'foir','op':'lte','value':50})]
  for product in ['car_loan','two_wheeler_loan','home_loan','gold_loan','loan_against_property']:
   p['rules'].append(dict(id='ltv_'+product,name='Sample collateral coverage for '+product.replace('_',' '),product=product,severity='blocking',condition={'field':'ltv','op':'lte','value':80}))
  new=add(db,a,'policy',p)
  add(db,a,'override',dict(actor=a.name,actor_id=a.id,action='policy_publish',reason_category='Synthetic scenario setup',justification='Add illustrative retail affordability checks and separate business-specific ratios for the expanded loan catalog.',before={'policy_id':current.id},after={'policy_id':new.id}),new.id)
  audit(db,a,'policy.published',new.id,after={'revision':p['revision'],'synthetic':True})
  for c in rows(db,a,'application'):c.data={**c.data,'assessment_stale':True}
  definitions={d['key']:d for d in DOCUMENTS+EXTRA_DOCS}
  for i,product in enumerate(DEFAULTS[2:]):
   amount='750000' if product['key']!='home_loan' else '6500000';tenure=min(60,product['max_tenure']);pricing=quote(product,amount,tenure)
   c=add(db,a,'application',dict(borrower=['Aarav Shah','Meera Nair','Rohan Patel','Isha Rao','Dev Sharma','Kavya Iyer','Arjun Mehta','Vertex Equipment LLP','Metro Transport LLP','Sana Farms'][i],reference=f'CR-RETAIL-{i+1:03}',product=product['key'],amount=amount,rate=pricing['rate'],pricing=pricing,tenure=tenure,required_documents=product['documents'],borrower_type=product['borrower_type'],status='in_review',sector='Retail' if product['borrower_type']=='person' else 'Services',branch='Mumbai',owner=a.name,owner_id=a.id,created_by=a.id,evidence_revision=1,assessment_stale=True,synthetic=True,sanctioned_amount=None))
   folder=ROOT/'data/documents'/a.org/c.id;folder.mkdir(parents=True,exist_ok=True)
   values={'monthly_income':'175000','existing_emi':'12000','proposed_emi':pricing['monthly_payment'],'requested_amount':amount,'collateral_value':str(int(amount)*1.4),'promoter_cibil_score':str(710+i*7),'bureau_report_date':date.today().isoformat(),'max_dpd':'0','overdue_amount':'0','statement_months':'6'}
   for j,key in enumerate(product['documents']):
    if i%3==0 and j==len(product['documents'])-1:continue
    path=folder/(key+'.pdf');pdf=canvas.Canvas(str(path));pdf.setFont('Helvetica-Bold',17);pdf.drawString(45,795,'SYNTHETIC DEMONSTRATION EVIDENCE');pdf.setFont('Helvetica',11);pdf.drawString(45,766,c.data['borrower']+' / '+definitions[key]['label']);y=735
    if key=='identity_income':
     for k,v in values.items():pdf.drawString(45,y,k+': '+v);y-=22
    else:pdf.drawString(45,y,'Sample placeholder for document checklist demonstration; requires analyst review.')
    pdf.save();raw=path.read_bytes();doc=add(db,a,'document',dict(filename=path.name,path=str(path),document_type=key,status='uploaded',pages=1,size=len(raw),sha256=hashlib.sha256(raw).hexdigest(),mime='application/pdf',synthetic=True),c.id)
    if key=='identity_income':
     for k,v in values.items():add(db,a,'fact',dict(key=k,value=v,document_id=doc.id,page=1,verified=True,reviewer='Synthetic fixture',reviewer_id='seed',source_text='Synthetic example '+k+': '+v),c.id)
   audit(db,a,'application.synthetic_seeded',c.id,after={'product':product['key']})
  add(db,a,'demo_extension',{'name':'retail-products-v1'});db.commit()
if __name__=='__main__':run()
