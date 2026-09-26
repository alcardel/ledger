FIELDS=[
('revenue','Revenue','INR'),('prior_revenue','Prior-year revenue','INR'),('operating_profit','Operating profit','INR'),('current_assets','Current assets','INR'),('current_liabilities','Current liabilities','INR'),('total_debt','Total debt','INR'),('equity','Net worth','INR'),('cash_available','Cash available for debt service','INR'),('debt_service','Annual debt service','INR'),('stock','Eligible inventory','INR'),('receivables','Eligible receivables','INR'),('creditors','Trade creditors','INR'),('bank_credits','Adjusted bank credits','INR'),('gst_turnover','GST turnover','INR'),('statement_months','Statement coverage','months'),('debtor_days','Receivable days','days'),('inventory_days','Inventory days','days'),('creditor_days','Payable days','days'),('interest_rate','Interest rate','percent'),('requested_amount','Requested facility','INR')]
def f(key): return {'field':key}
def op(name,*args): return {'op':name,'args':list(args)}
def default_policy():
    from .analytics import DOCUMENTS, BUREAU_FIELDS, BUREAU_RULES
    return {'name':'MSME Credit Framework','description':'Illustrative synthetic policy. Not a regulatory lending standard.','status':'published','revision':1,'created_by':'seed-policy-manager','author':'Synthetic policy team','confidence_threshold':.7,'documents':DOCUMENTS,'fields':[{'key':k,'label':l,'type':'number','unit':u,'instruction':f'Extract the explicitly stated {l.lower()}; retain the reporting period.','product':'both'} for k,l,u in FIELDS]+BUREAU_FIELDS, 'metrics':[
        {'key':'revenue_growth','label':'Revenue growth','unit':'percent','formula':op('mul',op('div',op('sub',f('revenue'),f('prior_revenue')),f('prior_revenue')),100)},
        {'key':'operating_margin','label':'Operating margin','unit':'percent','formula':op('mul',op('div',f('operating_profit'),f('revenue')),100)},
        {'key':'current_ratio','label':'Current ratio','unit':'ratio','formula':op('div',f('current_assets'),f('current_liabilities'))},
        {'key':'debt_equity','label':'Debt / equity','unit':'ratio','formula':op('div',f('total_debt'),f('equity'))},
        {'key':'dscr','label':'Debt service coverage','unit':'ratio','formula':op('div',f('cash_available'),f('debt_service'))},
        {'key':'eligible_limit','label':'Indicative eligible limit','unit':'INR','formula':op('max',0,op('sub',op('mul',op('add',f('stock'),f('receivables')),.75),f('creditors')))},
        {'key':'operating_cycle','label':'Operating cycle','unit':'days','formula':op('sub',op('add',f('debtor_days'),f('inventory_days')),f('creditor_days'))},
        {'key':'turnover_variance','label':'Turnover variance','unit':'percent','formula':op('mul',op('div',op('max',op('sub',f('bank_credits'),f('gst_turnover')),op('sub',f('gst_turnover'),f('bank_credits'))),f('gst_turnover')),100)}], 'rules':[
        {'id':'coverage','name':'At least 6 months of statements','product':'both','severity':'blocking','condition':{'field':'statement_months','op':'gte','value':6}},
        {'id':'liquidity','name':'Current ratio at least 1.20×','product':'both','severity':'blocking','condition':{'field':'current_ratio','op':'gte','value':1.2}},
        {'id':'repayment','name':'DSCR at least 1.25×','product':'term_loan','severity':'blocking','condition':{'field':'dscr','op':'gte','value':1.25}},
        {'id':'leverage','name':'Debt / equity at most 3.00×','product':'both','severity':'warning','condition':{'field':'debt_equity','op':'lte','value':3}},
        {'id':'turnover','name':'Turnover variance within 20%','product':'both','severity':'warning','condition':{'field':'turnover_variance','op':'lte','value':20}},
        {'id':'ageing','name':'Receivables within 90 days','product':'working_capital','severity':'blocking','condition':{'field':'debtor_days','op':'lte','value':90}}]+BUREAU_RULES, 'jev_questions':{}}
