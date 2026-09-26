"""Idempotent, demo-only evidence pack for the Harbour Components pitch scenario."""
from pathlib import Path
from decimal import Decimal
import csv,hashlib
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer
from xml.sax.saxutils import escape
from app.config import settings,ROOT
from app.db import Session,scope,now
from app.auth import Actor
from app.service import add,audit,rows,assessment_job
from app.products import catalog,quote
from app.tasks import dispatch_assessment
from app.engine import evaluate

CASE='case-harbour-components';PERIOD='2026-06-01 to 2026-09-26'
a=Actor('demo-relationship_manager','demo-bank','relationship_manager','Aditi Rao')
folder=ROOT/'data/documents'/a.org/CASE

def pdf(name,title,lines):
 path=folder/(name+'.pdf');style=getSampleStyleSheet();style['Title'].textColor=colors.HexColor('#17283d');style['BodyText'].fontSize=11;style['BodyText'].leading=17
 story=[Paragraph('Harbour Components',style['Title']),Paragraph(escape(title),style['Heading2']),Paragraph('Fictional demonstration evidence. Not a bank, tax authority or bureau-issued document.',style['BodyText']),Spacer(1,18)]
 for line in lines:story.extend([Paragraph(escape(line),style['BodyText']),Spacer(1,10)])
 SimpleDocTemplate(str(path),title=title,pagesize=(595,842),leftMargin=44,rightMargin=44,topMargin=40,bottomMargin=44).build(story)
 return path

def run():
 if settings.auth_mode!='demo':raise SystemExit('Requires local demo mode')
 folder.mkdir(parents=True,exist_ok=True)
 with Session() as db:
  scope(db,a.org)
  if any(c.id==CASE for c in rows(db,a,'application')):
   print('Harbour Components already exists; preserved all changes.');return
  product=next(p for p in catalog(db,a) if p['key']=='working_capital')
  pricing=quote(product,'30000000',12)
  case=add(db,a,'application',{'borrower':'Harbour Components','business_segment':'msme','product':'working_capital','amount':'30000000','tenure':12,'rate':pricing['rate'],'pricing':pricing,'sector':'Precision component manufacturing','branch':'Mumbai','reference':'CR-HARBOUR-001','status':'in_review','owner':a.name,'owner_id':a.id,'created_by':a.id,'required_documents':product['documents'],'borrower_type':'business','evidence_revision':1,'assessment_stale':True,'synthetic':True,'is_startup':True,'incorporation_date':'2026-06-01','sanctioned_amount':None,'scenario':'Fictional presentation example: INR 3 crore request and INR 80 lakh indicative limit'},id=CASE)
  audit(db,a,'demo.application.seeded',CASE,after={'borrower':'Harbour Components','requested_amount':'30000000','purpose':'Seed the user-requested fictional complex case with original and reviewed evidence.'})
  docs={}
  def document(kind,name,title,lines):
   path=pdf(name,title,lines)
   doc=add(db,a,'document',{'filename':path.name,'document_type':kind,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size,'pages':1,'locked':False,'status':'reviewed','synthetic':True},CASE)
   docs[name]=doc;audit(db,a,'document.uploaded',CASE,after={'document_id':doc.id,'filename':path.name,'fixture':True});return doc
  def fact(key,value,doc,text,period=PERIOD,verified=True):
   return add(db,a,'fact',{'key':key,'value':value,'document_id':doc.id,'source_text':text,'page':1,'period':period,'verified':verified,'reviewer':'Rohan Mehta (sample evidence preparation)','reviewer_id':'demo-credit_analyst','synthetic':True},CASE)
  appdoc=document('loan_application','application','Working-capital application',[
   'Applicant: Harbour Components, a fictional Mumbai MSME startup.','Owner: Aditi Rao. Analyst: Rohan Mehta. Proposed approver: Priya Nair.',
   'Requested amount: INR 30,000,000 (3 crore). Facility: working capital. Review tenure: 12 months.',f'Quoted annual rate: {pricing["rate"]}%. This is an illustrative saved quote, not a sanction.',
   'Purpose: buy components, hold stock and pay suppliers while waiting for customer payments.',
   'Operating history: June 2026 to September 2026. There is no prior-year operating history.'])
  registration=document('business_registration','registration','Business registration sample',['Business: Harbour Components. Location: Mumbai.','Illustrative incorporation date: 1 June 2026.','Fixture identifier: DEMO-HARBOUR-REGISTRATION. No real PAN, GSTIN or registration number.','No live identity or company-registry verification has been performed.'])
  identity=document('identity_income','promoter-profile','Promoter identity and income declaration',['Promoter: Kavya Desai (fictional). Owner contribution to the business: INR 3,000,000.','The promoter declares personal credit history. Personal repayment capacity requires independent verification.','No salary income figure or authentic identity number is fabricated. This document is a demonstration declaration only.'])
  gst=document('gst_return','gst-summary','GST turnover summary',['Reporting period: '+PERIOD,'Turnover: INR 9,000,000 (90 lakh).','June: INR 1,800,000. July: INR 2,100,000. August: INR 2,400,000. September to 26th: INR 2,700,000.','Four months of available records. Earlier periods do not exist for this fictional new business.','Sample turnover summary only; no GST portal verification.'])
  financial=document('financial_statement','financials','Management financial statements',['Reporting period: '+PERIOD,'Revenue: INR 9,000,000. Operating profit: INR 1,350,000.','Current assets: INR 24,000,000. Current liabilities: INR 15,000,000.','Total debt: INR 9,000,000. Net worth: INR 6,000,000.','Receivable days: 72. Inventory days: 35. Payable days: 45.','No prior-year revenue, annual debt-service figure or term-loan DSCR input is supplied.','Unaudited fictional management accounts. Financial amounts do not establish a lending approval.'])
  bureau=document('credit_bureau','bureau-summary','Recorded credit evidence',['Promoter: Kavya Desai. Illustrative personal score: 760. Report date: 26 September 2026.','Personal maximum days past due: 0. Reported personal overdue: INR 0.','Business commercial rank: unavailable / no history. No numerical business score is supplied.','This is NOT a live CIBIL report, bureau-issued report or endorsement. All numbers are fixture values.'])
  add(db,a,'bureau_report',{'subject_name':'Kavya Desai','subject_role':'promoter','promoter_cibil_score':'760','bureau_report_date':'2026-09-26','max_dpd':'0','overdue_amount':'0','document_id':bureau.id,'source_text':'Fictional promoter bureau summary; not bureau verified','entry_method':'manual','reviewer':a.name,'synthetic':True},CASE)
  entries=[]
  for month,amount in [(6,1800000),(7,2100000),(8,2400000),(9,2700000)]:
   entries.append({'date':f'2026-{month:02}-10','description':'Customer receipts','credit':str(amount),'debit':'0','category':'operating'})
   entries.append({'date':f'2026-{month:02}-18','description':'Supplier payment','credit':'0','debit':'1200000','category':'operating'})
  entries.extend([{'date':'2026-06-02','description':'Promoter capital contribution','credit':'3000000','debit':'0','category':'financing'},{'date':'2026-08-05','description':'Transfer from another company account','credit':'2000000','debit':'0','category':'transfer'},{'date':'2026-09-20','description':'Existing lender instalment','credit':'0','debit':'180000','category':'debt_service'}])
  entries.sort(key=lambda x:x['date']);balance=Decimal('0')
  for t in entries:balance+=Decimal(t['credit'])-Decimal(t['debit']);t['balance']=str(balance)
  path=folder/'bank-transactions.csv'
  with path.open('w') as f:
   writer=csv.DictWriter(f,fieldnames=['date','description','credit','debit','balance']);writer.writeheader();writer.writerows({k:v for k,v in t.items() if k!='category'} for t in entries)
  bank=add(db,a,'document',{'filename':path.name,'document_type':'bank_statement','path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size,'pages':1,'locked':False,'status':'reviewed','synthetic':True},CASE)
  for i,t in enumerate(entries):add(db,a,'transaction',{**t,'row':i+2,'document_id':bank.id,'excluded':False,'duplicate_candidate':False,'synthetic':True},CASE)
  for key,value in {'revenue':'9000000','operating_profit':'1350000','current_assets':'24000000','current_liabilities':'15000000','total_debt':'9000000','equity':'6000000','debtor_days':'72','inventory_days':'35','creditor_days':'45'}.items():fact(key,value,financial,key+': '+value)
  fact('statement_months','4',bank,'Four available statement months: June to September 2026')
  fact('gst_turnover','9000000',gst,'Turnover INR 9,000,000 across matching four-month period')
  fact('bank_credits','14000000',bank,'Initial unadjusted total credits INR 14,000,000. Pending reconciliation.',verified=False)
  for key,value in {'promoter_cibil_score':'760','bureau_report_date':'2026-09-26','max_dpd':'0','overdue_amount':'0'}.items():fact(key,value,bureau,key+': '+value,period=None)
  first=assessment_job(db,a,case,'initial_demo_submission')
  # Capture the initial state before adding the later documents and corrections.
  debt=document('debt_schedule','existing-loans','Existing loan schedule',['As of 26 September 2026. Borrower: Harbour Components.','Lender: Demonstration Equipment Finance. Facility: machinery loan. Status: active.','Outstanding: INR 9,000,000. Monthly EMI: INR 180,000 (1.8 lakh).','Maximum DPD: 0. June, July and August paid on time per fictional schedule.','September instalment of INR 180,000 matches the bank CSV entry. Earlier instalments are recorded from the loan schedule, not invented CSV transactions.'])
  schedule=add(db,a,'debt_schedule',{'loans':[{'lender':'Demonstration Equipment Finance','loan_type':'Machinery loan','monthly_emi':'180000','outstanding':'9000000','dpd':'0','status':'active','repayment_history':'June to September 2026: on time in fictional lender schedule; September matches supplied CSV.'}],'total_monthly_emi':'180000','report_date':'2026-09-26','source_text':'Fictional existing loan schedule','document_id':debt.id,'complete':True,'reviewer':'Rohan Mehta','synthetic':True},CASE)
  fact('existing_emi','180000',debt,'Existing monthly EMI INR 180,000; see fictional lender schedule',period=None)
  stock=document('stock_statement','stock','Stock statement',['As of 26 September 2026.','Eligible inventory at reviewed value: INR 6,000,000 (60 lakh).','Raw materials: INR 3,500,000. Finished goods: INR 2,500,000.','Excluded or obsolete inventory: INR 0 in this fixture. The reviewer accepts the eligible stock amount for the sample calculation.'])
  ageing=document('receivables_ageing','receivables-payables','Receivables and payables ageing',['As of 26 September 2026.','Total customer dues: INR 14,000,000.','Due within 90 days: INR 10,000,000. Older than 90 days: INR 4,000,000.','Eligible receivables after the reviewer excludes older balances: INR 10,000,000.','Trade creditors / money owed to suppliers: INR 4,000,000.','The exclusion follows this fictional example policy, not a universal banking rule.'])
  reconciliation=document('financial_statement','turnover-reconciliation','Turnover reconciliation and limit calculation',['Matching period: '+PERIOD,'Raw bank credits: INR 14,000,000.','Less promoter capital contribution: INR 3,000,000. Less internal account transfer: INR 2,000,000.','Adjusted operating credits: INR 9,000,000. GST turnover: INR 9,000,000. Reconciled difference: INR 0.','Original bank transactions and original unverified field remain in evidence history.','Indicative eligible limit: 75% x (INR 6,000,000 eligible stock + INR 10,000,000 eligible receivables) - INR 4,000,000 creditors = INR 8,000,000.','Requested amount: INR 30,000,000. Indicative limit: INR 8,000,000. Difference: INR 22,000,000.','This is a formula result, not a sanctioned loan. Short history, no business rank and repayment affordability still require review.'])
  fact('bank_credits','9000000',reconciliation,'Adjusted bank credits = 14,000,000 - 3,000,000 promoter funds - 2,000,000 internal transfer = 9,000,000')
  for key,value,doc in [('stock','6000000',stock),('receivables','10000000',ageing),('creditors','4000000',ageing)]:fact(key,value,doc,key+': '+value+'; reviewed eligibility basis as of 26 September 2026')
  document('loan_application','case-walkthrough','Officer case walkthrough',['Initial submission: INR 3 crore request, four months of statements, unclear turnover, absent loan and stock schedules.','Later evidence: turnover reconciles to INR 90 lakh; existing EMI is INR 1.8 lakh/month; reviewed eligible stock and receivables yield INR 80 lakh.','Aditi Rao: relationship owner. Rohan Mehta: sample analyst. Priya Nair: proposed approver.','Open concerns: short operating history, business bureau rank unavailable, requested amount above indicative support and repayment affordability.','The two assessment snapshots preserve initial and updated evidence. Live local Qwen runs supply their recommendations.','The user may inspect documents, financial inputs, cash-flow entries, previous EMIs and the exception register. No loan has been sanctioned.'])
  for kind,reason in [('credit_bureau','The new business has no commercial rank yet. A promoter score is available but does not replace the business rank.'),('bank_statement','Business commenced in June 2026. Only four months exist; the six-month coverage requirement remains open.')]:
   add(db,a,'evidence_explanation',{'document_type':kind,'availability':'not_yet_available','reason':reason,'recorded_by':a.name,'recorded_by_id':a.id,'review_status':'pending_review','synthetic':True},CASE)
  for title,severity,detail in [
   ('Short operating history','blocking','Four months of statements against the sample six-month requirement. Startup explanation does not waive the gate.'),
   ('Business credit rank unavailable','blocking','Obtain business credit evidence or an authorized policy exception. No commercial rank is fabricated.'),
   ('Request exceeds indicative working-capital limit','warning','INR 3 crore requested versus INR 80 lakh supported by the current sample formula. Reconsider amount and terms.'),
   ('Existing EMI affordability review','warning','Verify capacity to service INR 1.8 lakh per month alongside the requested working-capital facility.')]:
   add(db,a,'exception',{'title':title,'severity':severity,'status':'open','owner':a.name,'owner_id':a.id,'detail':detail,'synthetic':True},CASE)
  add(db,a,'exception',{'title':'Turnover mismatch reconciled','severity':'warning','status':'resolved','owner':'Rohan Mehta','owner_id':'demo-credit_analyst','detail':'Original INR 50 lakh difference explained by owner funds and an internal transfer.','resolution':'INR 30 lakh capital plus INR 20 lakh internal transfers excluded from operating credits. Original statement retained.','resolved_by':'Rohan Mehta','synthetic':True},CASE)
  case.data={**case.data,'evidence_revision':2,'assessment_stale':True}
  audit(db,a,'evidence.reconciled',CASE,after={'raw_bank_credits':'14000000','adjusted_bank_credits':'9000000','eligible_limit':'8000000','existing_emi':'180000','reviewer':'Rohan Mehta'})
  last=assessment_job(db,a,case,'updated_demo_submission')
  calculation=evaluate(last.data['snapshot']['policy'],last.data['snapshot']['facts'],'working_capital',last.data['snapshot']['periods'])
  assert next(m['value'] for m in calculation['metrics'] if m['key']=='eligible_limit')=='8000000.0000'
  assert next(m['value'] for m in calculation['metrics'] if m['key']=='turnover_variance')=='0.0000'
  assert not last.data['snapshot']['missing_documents']
  assert 'commercial_cibil_rank' not in last.data['snapshot']['facts']
  db.commit()
  dispatch_assessment(db,a,first);dispatch_assessment(db,a,last)
  print('Seeded Harbour Components:',CASE,'documents',len(rows(db,a,'document',CASE)),'jobs',first.id,last.id)
if __name__=='__main__':run()
