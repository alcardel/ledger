from decimal import Decimal
from datetime import date
from .engine import decimal
DOCUMENTS=[
 {'key':'loan_application','label':'Loan application','purpose':'Requested amount, facility, tenure and loan purpose','product':'both'},
 {'key':'business_registration','label':'Business registration & KYC','purpose':'Entity identifiers and ownership; uploaded evidence is not live KYC verification','product':'both'},
 {'key':'bank_statement','label':'Bank statements / transaction CSV','purpose':'Cash flows, balances and repayment patterns','product':'both'},
 {'key':'financial_statement','label':'Financial statements','purpose':'Profit and loss, balance sheet and repayment capacity','product':'both'},
 {'key':'gst_return','label':'GST returns / turnover summary','purpose':'Turnover and period reconciliation','product':'both'},
 {'key':'debt_schedule','label':'Existing loan schedule','purpose':'Existing principal, interest and overdue obligations','product':'both'},
 {'key':'credit_bureau','label':'Credit bureau report','purpose':'Promoter personal score and business rank, report date and repayment history','product':'both'},
 {'key':'projected_cashflow','label':'Projected cash flow','purpose':'Proposed term-loan repayment capacity; projections are not historical facts','product':'term_loan'},
 {'key':'stock_statement','label':'Stock statement','purpose':'Eligible inventory and working-capital margins','product':'working_capital'},
 {'key':'receivables_ageing','label':'Receivables / payables ageing','purpose':'Debtor eligibility, operating cycle and creditor deductions','product':'working_capital'},
]
BUREAU_FIELDS=[
 {'key':'promoter_cibil_score','label':'Promoter personal CIBIL score','type':'number','unit':'score','product':'both','instruction':'Extract only the personal/individual bureau score (300–900). Do not substitute commercial rank. Missing/no-history stays absent.'},
 {'key':'commercial_cibil_rank','label':'Business CIBIL commercial rank','type':'number','unit':'rank','product':'both','instruction':'Extract commercial/business rank 1–10 only. Rank 1 is lowest risk. Never derive this from a personal score.'},
 {'key':'bureau_report_date','label':'Bureau report date','type':'date','unit':'date','product':'both','instruction':'Report issue date as YYYY-MM-DD; do not infer a missing date.'},
 {'key':'max_dpd','label':'Maximum days past due','type':'number','unit':'days','product':'both','instruction':'Maximum reported DPD from supplied bureau evidence.'},
 {'key':'overdue_amount','label':'Reported overdue amount','type':'number','unit':'INR','product':'both','instruction':'Total reported overdue amount, not total outstanding balance.'},
 {'key':'credit_utilisation','label':'Reported credit utilisation','type':'number','unit':'percent','product':'working_capital','instruction':'Utilisation percentage stated in the report; do not invent from incomplete limits.'},
]
BUREAU_RULES=[
 {'id':'personal_bureau_range','name':'Personal bureau score has a valid range','severity':'blocking','product':'both','condition':{'field':'promoter_cibil_score','op':'between','value':[300,900]}},
 {'id':'personal_bureau_threshold','name':'Promoter score meets sample 700 threshold','severity':'warning','product':'both','condition':{'field':'promoter_cibil_score','op':'gte','value':700}},
 {'id':'business_bureau_range','name':'Commercial rank has a valid range','severity':'blocking','product':'both','condition':{'field':'commercial_cibil_rank','op':'between','value':[1,10]}},
 {'id':'business_bureau_threshold','name':'Business rank within sample CMR 1–5 band','severity':'warning','product':'both','condition':{'field':'commercial_cibil_rank','op':'lte','value':5}},
 {'id':'bureau_freshness','name':'Bureau report within sample 90-day window','severity':'warning','product':'both','condition':{'field':'bureau_report_date','op':'age_lte','value':90}},
 {'id':'repayment_dpd','name':'Maximum DPD within sample 30-day limit','severity':'warning','product':'both','condition':{'field':'max_dpd','op':'lte','value':30}},
 {'id':'overdue','name':'No reported overdue amount','severity':'warning','product':'both','condition':{'field':'overdue_amount','op':'lte','value':0}},
]

def readiness(documents,policy,product,required=None):
    from .products import EXTRA_DOCS, DEFAULTS
    types={d.data['document_type'] for d in documents if d.data.get('status') not in ['locked','failed']}
    requirements=policy.get('documents',DOCUMENTS)
    if required is not None:
        definitions={d['key']:d for d in DOCUMENTS+EXTRA_DOCS}
        return [{**definitions.get(k,{'key':k,'label':k,'purpose':'Configured requirement'}),'received':k in types} for k in required]
    return [{**d,'received':d['key'] in types} for d in requirements if d.get('product','both') in ['both',product]]

def product_metrics(cases):
    out=[]
    for product in sorted({c['product'] for c in cases}):
        cohort=[c for c in cases if c['product']==product]
        rates=[decimal(c['rate']) for c in cohort if c.get('rate') is not None]
        priced=[c for c in cohort if c.get('rate') is not None and decimal(c['amount'])>0]
        approved=[c for c in cohort if c['status']=='approved'];decided=[c for c in cohort if c['status'] in ['approved','declined']]
        total=sum((decimal(c['amount']) for c in cohort),Decimal(0))
        priced_amount=sum((decimal(c['amount']) for c in priced),Decimal(0))
        weighted=sum((decimal(c['amount'])*decimal(c['rate']) for c in priced),Decimal(0))/priced_amount if priced_amount else None
        out.append({'product':product,'count':len(cohort),'requested':str(total),'sanctioned':str(sum((decimal(c.get('sanctioned_amount') or 0) for c in approved),Decimal(0))),'approved_count':len(approved),'decided_count':len(decided),'approval_rate':len(approved)/len(decided)*100 if decided else None,'mean_quoted_rate':float(sum(rates)/len(rates)) if rates else None,'weighted_quoted_rate':float(weighted) if weighted is not None else None,'min_quoted_rate':float(min(rates)) if rates else None,'max_quoted_rate':float(max(rates)) if rates else None,'approved_rate':None,'share':len(cohort)/len(cases)*100 if cases else 0})
    return out
