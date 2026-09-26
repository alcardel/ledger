"""Repeatable synthetic fixtures. No model-generated decisions are seeded."""
from pathlib import Path
from datetime import timedelta
from decimal import Decimal
import csv,hashlib
from reportlab.pdfgen import canvas
from .db import Session,Record,scope,now
from .auth import Actor
from .service import add,audit,rows
from .defaults import default_policy,FIELDS
from .config import ROOT

NAMES=['Aarav Precision Components','Suryodaya Textiles','Meridian Packaging','Kaveri Agro Foods','Prakash Engineering','Nila Healthcare Supplies','Vardhan Logistics','Sahyadri Auto Parts','Lotus Paper Products','Aranya Furniture','Deccan Electricals','Navya Food Processing','Triveni Industrial Tools','Indus Cold Storage','Saffron Homeware','Orion Fabrication','Veda Pharma Distributors','Coastal Marine Exports','Maitri Plastics','Aster Renewable Systems']
def seed():
    a=Actor('demo-org_admin','demo-bank','org_admin','Ananya Sharma')
    with Session() as db:
        scope(db,a.org)
        if rows(db,a,'application'): print('Synthetic cases already exist; preserving edits.'); return
        add(db,a,'policy',default_policy())
        for role,name in [('org_admin','Ananya Sharma'),('credit_analyst','Rohan Mehta'),('credit_approver','Priya Nair'),('policy_manager','Vikram Shah'),('relationship_manager','Aditi Rao'),('risk_reviewer','Ishaan Patel')]:
            add(db,a,'membership',{'user_id':'demo-'+role,'name':name,'role':role,'synthetic':True})
        statuses=['in_review','evidence_pending','pending_approval','approved','in_review','returned','approved','in_review','declined','draft']
        for i,name in enumerate(NAMES):
            product='term_loan' if i%2==0 else 'working_capital'; amount=(35+i*7)*100000; status=statuses[i%10]
            c=add(db,a,'application',{'reference':f'CR-2026-{1041+i}','borrower':name,'product':product,'amount':str(amount),'tenure':36 if product=='term_loan' else 12,'rate':'12','sector':['Manufacturing','Textiles','Packaging','Food & agriculture','Engineering'][i%5],'branch':['Mumbai','Pune','Ahmedabad','Bengaluru'][i%4],'status':status,'owner':'Rohan Mehta','owner_id':'demo-credit_analyst','created_by':'demo-relationship_manager','evidence_revision':1,'assessment_stale':True,'synthetic':True,'sanctioned_amount':str(amount*.9) if status=='approved' else None,'decision_at':(now()-timedelta(days=i%4)).isoformat() if status in ['approved','declined'] else None,'decision_by':'synthetic-historical-officer' if status in ['approved','declined'] else None},id=f'case-{i+1:03}')
            c.created_at=now()-timedelta(days=2+i%17)
            scale=Decimal(i+8)/8
            values={'revenue':120000000*scale,'prior_revenue':100000000*scale,'operating_profit':18000000*scale,'current_assets':45000000*scale,'current_liabilities':28000000*scale,'total_debt':30000000*scale,'equity':24000000*scale,'cash_available':11000000*scale,'debt_service':7000000*scale,'stock':18000000*scale,'receivables':22000000*scale,'creditors':10000000*scale,'bank_credits':115000000*scale,'gst_turnover':120000000*scale,'statement_months':6,'debtor_days':65,'inventory_days':42,'creditor_days':35,'interest_rate':12,'requested_amount':amount}
            if i%5==1: values['statement_months']=3
            if i%5==2: values['cash_available']=4000000*scale
            if i%5==3: values['debtor_days']=118
            if i%5==4: values['bank_credits']=65000000*scale
            folder=ROOT/'data/documents'/a.org/c.id; folder.mkdir(parents=True,exist_ok=True)
            path=folder/'financial-statement.pdf'; pdf=canvas.Canvas(str(path)); pdf.setTitle(f'{name} — synthetic financial statement')
            pdf.setFont('Helvetica-Bold',18); pdf.drawString(48,790,'SYNTHETIC FINANCIAL STATEMENT'); pdf.setFont('Helvetica',11); pdf.drawString(48,764,name); pdf.drawString(48,744,'Reporting period: FY 2025-26 | Currency: INR | Educational sample')
            y=710
            for key,label,unit in FIELDS:
                pdf.drawString(48,y,f'{label}: {values[key]} {unit}'); y-=24
            pdf.setFont('Helvetica',9); pdf.drawString(48,80,'All figures are invented for demonstration. This is not a real borrower.'); pdf.save()
            doc=add(db,a,'document',{'filename':'financial-statement.pdf','document_type':'financial_statement','path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size,'pages':1,'locked':False,'status':'reviewed','synthetic':True},c.id)
            for key,label,unit in FIELDS:
                if i==1 and key=='gst_turnover': continue
                add(db,a,'fact',{'key':key,'value':str(values[key]),'source_text':f'{label}: {values[key]} {unit}','document_id':doc.id,'page':1,'period':'FY 2025-26','verified':True,'reviewer':'Synthetic fixture preparation','synthetic':True},c.id)
            csvpath=folder/'bank-transactions.csv'
            transactions=[]
            for month in range(4,10):
                credit=int(7000000*scale*(Decimal(1)+Decimal(month-4)*Decimal('.035'))); debit=int(credit*.76)
                transactions += [{'date':f'2026-{month:02}-10','description':'Customer operating receipts','credit':str(credit),'debit':'0','balance':str(credit),'category':'operating'},{'date':f'2026-{month:02}-20','description':'Supplier payments','credit':'0','debit':str(debit),'balance':str(credit-debit),'category':'operating'}]
            with csvpath.open('w') as f:
                writer=csv.DictWriter(f,fieldnames=['date','description','credit','debit','balance']); writer.writeheader(); writer.writerows({k:v for k,v in t.items() if k!='category'} for t in transactions)
            bank=add(db,a,'document',{'filename':'bank-transactions.csv','document_type':'bank_statement','path':str(csvpath),'sha256':hashlib.sha256(csvpath.read_bytes()).hexdigest(),'size':csvpath.stat().st_size,'pages':1,'locked':False,'status':'reviewed','synthetic':True},c.id)
            for j,t in enumerate(transactions): add(db,a,'transaction',{**t,'row':j+2,'document_id':bank.id,'excluded':False,'synthetic':True},c.id)
            if i%5:
                title={1:'Incomplete statement coverage',2:'Repayment coverage below sample policy',3:'Receivables beyond policy ageing',4:'Turnover reconciliation required'}[i%5]
                add(db,a,'exception',{'title':title,'severity':'blocking' if i%5 in [1,2,3] else 'warning','status':'open','owner':'Rohan Mehta','detail':'Synthetic exception. Review the supporting figures and resolve or explicitly override.','synthetic':True},c.id)
            audit(db,a,'synthetic.application.seeded',c.id,after={'status':status,'note':'Synthetic historical state; no AI assessment has been run.'})
        db.commit(); print('Seeded 20 synthetic cases, source PDFs, transaction CSVs and an illustrative policy.')
if __name__=='__main__': seed()
