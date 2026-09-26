from decimal import Decimal
import pytest
from app.products import DEFAULTS,quote

def test_flat_and_zero_rate_hand_calculations():
    p={**DEFAULTS[2],'method':'flat','base_rate':'12'}
    q=quote(p,'100000',12)
    assert q['total_interest']=='12000.00'
    assert q['total_repayment']=='112000.00'
    assert q['monthly_payment']=='9333.33'
    q=quote({**p,'base_rate':'0'},'120000',12)
    assert q['monthly_payment']=='10000.00' and q['total_interest']=='0.00'

def test_reducing_rate_bounds_and_invalid_terms():
    p={**DEFAULTS[2],'base_rate':'10','spread':'5','cap_rate':'12'}
    q=quote(p,'100000',12)
    assert q['rate']=='12'
    assert abs(Decimal(q['monthly_payment'])-Decimal('8884.88'))<Decimal('.01')
    assert Decimal(q['total_interest'])<Decimal('12000')
    for amount,n in [('0',12),('100',601),('NaN',12)]:
        with pytest.raises(ValueError):quote(p,amount,n)
