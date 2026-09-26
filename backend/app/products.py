"""Organization-configurable product terms. Defaults are illustrative, not market offers."""
import re
from decimal import Decimal, ROUND_HALF_UP
from .engine import decimal, emi
from .service import rows
BASE_DOCS=['loan_application','identity_income','bank_statement','credit_bureau']
SPECS=[('term_loan','MSME term loan','business',12,120,['business_registration','financial_statement','gst_return','debt_schedule','projected_cashflow']),('working_capital','Working capital','business',12,36,['business_registration','financial_statement','gst_return','debt_schedule','stock_statement','receivables_ageing']),('personal_loan','Personal loan','person',14,84,[]),('education_loan','Education / student loan','person',10,180,['admission_fees','coapplicant_income']),('two_wheeler_loan','Two-wheeler / bike loan','person',12,60,['vehicle_quotation']),('car_loan','Car loan','person',10,96,['vehicle_quotation']),('home_loan','Home loan','person',9,360,['property_title','property_valuation']),('gold_loan','Gold loan','person',12,36,['gold_valuation']),('loan_against_property','Loan against property','either',11,180,['property_title','property_valuation']),('equipment_loan','Equipment loan','business',12,84,['financial_statement','equipment_quotation']),('commercial_vehicle_loan','Commercial vehicle loan','business',12,84,['financial_statement','vehicle_quotation']),('agriculture_loan','Agriculture loan','either',10,120,['land_crop_records'])]
DEFAULTS=[dict(key=k,name=n,borrower_type=b,base_rate=str(r),spread='0',floor_rate='0',cap_rate='36',method='reducing',min_tenure=1,max_tenure=t,documents=list(dict.fromkeys(BASE_DOCS+d)),illustrative=True,revision=0) for k,n,b,r,t,d in SPECS]
EXTRA_DOCS=[dict(key=k,label=n,purpose=p,product='catalog') for k,n,p in [('identity_income','Identity & income evidence','Applicant identity, income and repayment capacity'),('admission_fees','Admission letter & fee schedule','Course, institution, fees and payment dates'),('coapplicant_income','Co-applicant income evidence','Co-applicant repayment capacity'),('vehicle_quotation','Vehicle quotation','Vehicle price and proposed financing'),('property_title','Property title documents','Ownership and legal review'),('property_valuation','Property valuation','Independent collateral valuation'),('gold_valuation','Gold appraisal','Purity, weight and eligible collateral value'),('equipment_quotation','Equipment quotation','Asset price and financing purpose'),('land_crop_records','Land & crop records','Land rights and seasonal cash-flow evidence')]]
ACTIVE_PRODUCTS={'term_loan','working_capital'}

def catalog(db,a):
    result={p['key']:dict(p) for p in DEFAULTS}
    for r in reversed(rows(db,a,'product')): result[r.data['key']]={**r.data,'revision':r.version}
    return [{**p,'name':('Business term loan' if p['key']=='term_loan' else 'Working capital'),'borrower_type':'business','segments':['msme','enterprise']} for p in result.values() if p['key'] in ACTIVE_PRODUCTS]
def validate(p):
    if not re.fullmatch('[a-z][a-z0-9_]{1,59}',p.get('key','')): raise ValueError('Product key must use lowercase letters, numbers and underscores')
    if not str(p.get('name','')).strip(): raise ValueError('Product name required')
    if p.get('borrower_type') not in ['person','business','either']: raise ValueError('Choose a borrower type')
    if p.get('method') not in ['reducing','flat']: raise ValueError('Choose reducing or flat interest')
    rates={k:decimal(p[k]) for k in ['base_rate','spread','floor_rate','cap_rate']}
    if not 0<=rates['floor_rate']<=rates['cap_rate']<=100: raise ValueError('Rate limits must satisfy 0 ≤ floor ≤ cap ≤ 100')
    if not 0<=rates['base_rate']<=100 or not -100<=rates['spread']<=100: raise ValueError('Invalid base rate or spread')
    if not 1<=int(p['min_tenure'])<=int(p['max_tenure'])<=600: raise ValueError('Tenure must be between 1 and 600 months')
    if not isinstance(p.get('documents'),list) or not p['documents']: raise ValueError('Select required documents')
    return p

def quote(p,amount,tenure):
    validate(p); principal=decimal(amount); n=int(tenure)
    if principal<=0 or principal>Decimal('1000000000000'): raise ValueError('Principal must be positive and at most one trillion INR')
    if not int(p['min_tenure'])<=n<=int(p['max_tenure']): raise ValueError('Tenure is outside this product’s configured limits')
    rate=max(decimal(p['floor_rate']),min(decimal(p['cap_rate']),decimal(p['base_rate'])+decimal(p['spread'])))
    payment=emi(principal,rate,n) if p['method']=='reducing' else (principal+principal*rate*n/1200)/n
    total=payment*n
    money=lambda v:str(v.quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
    return dict(rate=str(rate),method=p['method'],monthly_payment=money(payment),total_interest=money(total-principal),total_repayment=money(total),tenure=n,product_snapshot=p,notice='Illustrative equal-month instalments; excludes fees, taxes, moratorium and future rate resets. Flat and reducing rates are not directly comparable.')
