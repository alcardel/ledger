from decimal import Decimal
import pytest
from app.engine import expression, Missing, evaluate, emi, validate_policy, condition
from app.defaults import default_policy

def test_financial_precision_and_zero_rate():
    assert expression({'op':'add','args':['0.1','0.2']},{})==Decimal('.3')
    assert emi('120000','0',12)==Decimal('10000.00')
    assert emi('1000000','12',12)==Decimal('88848.79')

def test_missing_is_not_zero_and_division_is_guarded():
    with pytest.raises(Missing): expression({'field':'revenue'},{})
    with pytest.raises(Missing): expression({'op':'div','args':[100,0]}, {})
    p=default_policy(); result=evaluate(p,{},'term_loan')
    assert all(r['result'] in ['unable_to_assess','not_applicable'] for r in result['rules'])
    assert all(m['value'] is None for m in result['metrics'])

def test_product_applicability_and_nested_conditions():
    p=default_policy();r=evaluate(p,{'cash_available':'150','debt_service':'100','statement_months':6,'current_assets':150,'current_liabilities':100},'term_loan')
    assert next(x for x in r['rules'] if x['id']=='repayment')['result']=='pass'
    assert next(x for x in r['rules'] if x['id']=='ageing')['result']=='not_applicable'
    assert condition({'any':[{'field':'x','op':'gte','value':3},{'field':'missing','op':'gt','value':0}]},{'x':4}) is True
    assert condition({'all':[{'field':'x','op':'gte','value':3},{'field':'missing','op':'gt','value':0}]},{'x':2}) is False

def test_circular_unknown_and_code_expressions_rejected():
    p=default_policy();p['metrics'].append({'key':'bad','formula':{'field':'bad'}})
    with pytest.raises(ValueError,match='circular'):validate_policy(p)
    p=default_policy();p['rules'][0]['condition']['field']='unknown'
    with pytest.raises(ValueError,match='Unknown'):validate_policy(p)
    p=default_policy();p['metrics'][0]['formula']={'op':'__import__','args':['os']}
    with pytest.raises(ValueError,match='Unsupported'):validate_policy(p)

def test_working_capital_formula_and_invalid_number():
    r=evaluate(default_policy(),{'stock':100,'receivables':100,'creditors':20},'working_capital')
    assert next(m for m in r['metrics'] if m['key']=='eligible_limit')['value']=='130.0000'
    with pytest.raises(ValueError):expression('NaN',{})

def test_mismatched_periods_prevent_ratio_calculation():
    r=evaluate(default_policy(),{'cash_available':150,'debt_service':100},'term_loan',{'cash_available':'FY2026','debt_service':'FY2025'})
    m=next(m for m in r['metrics'] if m['key']=='dscr')
    assert m['value'] is None
    assert 'periods do not match' in m['reason']
