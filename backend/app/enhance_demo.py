"""Add explicitly synthetic bureau evidence and per-product document packs, once."""
from datetime import date,timedelta
from pathlib import Path
import hashlib
from reportlab.pdfgen import canvas
from .db import Session,scope,now
from .auth import Actor
from .service import rows,add,audit,policy_current
from .analytics import DOCUMENTS,BUREAU_FIELDS,BUREAU_RULES
from .defaults import default_policy
from .config import ROOT

def enhance():
 a=Actor('demo-org_admin','demo-bank','org_admin','Ananya Sharma')
 with Session() as db:
  scope(db,a.org)
  if any(r.data.get('name')=='bureau-and-documents-v1' for r in rows(db,a,'demo_extension')): return
  current=policy_current(db,a);p=default_policy();p.update({'revision':max([r.data.get('revision',0) for r in rows(db,a,'policy')]+[0])+1,'published_at':now().isoformat(),'created_by':a.id,'author':'Synthetic scenario setup','published_by':a.id})
  new=add(db,a,'policy',p)
  add(db,a,'override',{'actor':a.name,'actor_id':a.id,'action':'policy_publish','reason_category':'Synthetic scenario setup','justification':'Extend demonstration policy with borrower bureau checks and product-specific document requirements as requested.','before':{'policy_id':current.id if current else None},'after':{'policy_id':new.id}},new.id)
  audit(db,a,'policy.published',new.id,after={'revision':p['revision'],'synthetic':True})
  for c in rows(db,a,'application'):
   if not c.data.get('synthetic') or not c.id.startswith('case-'): continue
   i=int(c.id[-3:])-1
   c.data={**c.data,'rate':str(round(10.25+(i%8)*.55+(1.1 if c.data['product']=='working_capital' else 0),2)),'assessment_stale':True,'evidence_revision':c.data.get('evidence_revision',0)+1}
   values={'promoter_cibil_score':str(655+(i*13)%165),'commercial_cibil_rank':str(1+i%8),'bureau_report_date':(date.today()-timedelta(days=15 if i%5==0 else 20+i*6)).isoformat(),'max_dpd':str(0 if i%4 else 45),'overdue_amount':str(150000 if i%4==0 else 0),'credit_utilisation':str(40+(i*7)%55)}
   if i%7==0: values['max_dpd']='0';values['overdue_amount']='0'
   # Some synthetic thin-file borrowers have no personal score; never invent one.
   if i in [6,13]: values.pop('promoter_cibil_score')
   folder=ROOT/'data/documents'/a.org/c.id;folder.mkdir(parents=True,exist_ok=True)
   catalog=[d for d in DOCUMENTS if d['product'] in ['both',c.data['product']]]
   existing={d.data['document_type'] for d in rows(db,a,'document',c.id)}
   for definition in catalog:
    kind=definition['key']
    if kind in existing: continue
    if i%3!=0 and kind in ['gst_return','debt_schedule','projected_cashflow','stock_statement']: continue
    path=folder/(kind+'.pdf');pdf=canvas.Canvas(str(path));pdf.setTitle('Synthetic '+definition['label'])
    pdf.setFont('Helvetica-Bold',17);pdf.drawString(44,795,'SYNTHETIC '+definition['label'].upper()[:55]);pdf.setFont('Helvetica',11);pdf.drawString(44,767,c.data['borrower']);pdf.drawString(44,745,'Educational example. Not issued or verified by a credit bureau.');y=707
    if kind=='credit_bureau':
     for f in BUREAU_FIELDS:
      pdf.drawString(44,y,f["label"]+': '+values.get(f['key'],'Not scored / no history'));y-=26
     pdf.drawString(44,y-15,'Personal score and company rank describe different subjects.');pdf.drawString(44,y-40,'This invented report is not a TransUnion CIBIL product or endorsement.')
    else:
     content={'loan_application':[f"Requested facility: {c.data['product']}",f"Requested amount: INR {c.data['amount']}",f"Quoted interest rate: {c.data['rate']}% per annum",f"Tenure: {c.data['tenure']} months"], 'business_registration':['Entity name: '+c.data['borrower'],'Registration ID: DEMO-ENTITY-'+str(i+1),'KYC verification: Not performed (synthetic fixture)'], 'gst_return':['GST turnover: see consolidated synthetic financial statement','Reporting period: FY 2025-26'], 'debt_schedule':['Annual debt service: see consolidated synthetic financial statement','Reporting period: FY 2025-26'],'projected_cashflow':['Projection scenario: illustrative base case','Projection is not an audited historical result'],'stock_statement':['Eligible stock: see consolidated synthetic financial statement','As-of period: FY 2025-26'],'receivables_ageing':['Receivable and payable days: see consolidated synthetic financial statement','As-of period: FY 2025-26']}.get(kind,[])
     for line in content:pdf.drawString(44,y,line);y-=26
    pdf.save()
    doc=add(db,a,'document',{'filename':path.name,'document_type':kind,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size,'pages':1,'locked':False,'status':'reviewed','synthetic':True},c.id)
    if kind=='credit_bureau':
     for f in BUREAU_FIELDS:
      if f['key'] in values:add(db,a,'fact',{'key':f['key'],'value':values[f['key']],'source_text':f['label']+': '+values[f['key']],'document_id':doc.id,'page':1,'period':None,'verified':True,'reviewer':'Synthetic fixture preparation','synthetic':True},c.id)
   audit(db,a,'synthetic.bureau_and_documents.added',c.id,after={'note':'Synthetic reports; no live bureau verification','quoted_rate':c.data['rate']})
  add(db,a,'demo_extension',{'name':'bureau-and-documents-v1'});db.commit();print('Added synthetic bureau profiles, varied quoted rates and product document packs. Preserved prior policies and appraisals.')
if __name__=='__main__':enhance()
