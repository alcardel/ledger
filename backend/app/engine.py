"""Bounded expression interpreter: no eval, attribute access, or user code."""
from decimal import Decimal, InvalidOperation
from datetime import date
import operator

class Missing(ValueError): pass
OPS = {'gt':operator.gt,'gte':operator.ge,'lt':operator.lt,'lte':operator.le,'eq':operator.eq,'ne':operator.ne}

def decimal(value):
    if value is None or isinstance(value, bool): raise Missing('Required amount unavailable')
    try:
        n = Decimal(str(value).replace(',', ''))
        if not n.is_finite(): raise ValueError('Non-finite amount')
        return n
    except InvalidOperation: raise ValueError('Invalid amount')

def expression(node, facts, depth=0):
    if depth > 20: raise ValueError('Expression too deep')
    if not isinstance(node, dict): return decimal(node)
    if 'field' in node:
        if facts.get(node['field']) is None: raise Missing(f"Missing {node['field']}")
        return decimal(facts[node['field']])
    op = node.get('op')
    if op == 'days_between':
        keys = node.get('fields', [])
        if len(keys) != 2 or any(not facts.get(k) for k in keys): raise Missing('Dates unavailable')
        return Decimal((date.fromisoformat(str(facts[keys[1]]))-date.fromisoformat(str(facts[keys[0]]))).days)
    args = [expression(x, facts, depth+1) for x in node.get('args', [])]
    if not args: raise ValueError('Arguments required')
    if op == 'sum': return sum(args, Decimal(0))
    if op == 'avg': return sum(args, Decimal(0))/len(args)
    if op == 'min': return min(args)
    if op == 'max': return max(args)
    if len(args) != 2: raise ValueError('Two arguments required')
    a,b = args
    if op == 'add': return a+b
    if op == 'sub': return a-b
    if op == 'mul': return a*b
    if op == 'div':
        if b == 0: raise Missing('Denominator is zero')
        return a/b
    raise ValueError('Unsupported calculation')

def references(node):
    if isinstance(node, dict):
        out = {node['field']} if 'field' in node else set(node.get('fields', []))
        for v in node.values(): out |= references(v)
        return out
    if isinstance(node, list): return set().union(*(references(v) for v in node)) if node else set()
    return set()

def validate_policy(policy):
    fields = policy.get('fields', [])
    ids = [f['key'] for f in fields]
    if len(ids) != len(set(ids)): raise ValueError('Duplicate field key')
    known = set(ids)
    metrics = policy.get('metrics', [])
    pending = {m['key']:m for m in metrics}
    if len(pending)!=len(metrics) or known & set(pending): raise ValueError('Duplicate metric key')
    while pending:
        ready = [k for k,m in pending.items() if references(m['formula']) <= known]
        if not ready: raise ValueError('Unknown field or circular formula dependency')
        for k in ready:
            validate_expression(pending[k]['formula'])
            known.add(k); del pending[k]
    units = {f['key']:f.get('unit','number') for f in fields} | {m['key']:m.get('unit','number') for m in metrics}
    for rule in policy.get('rules', []):
        if rule.get('severity') not in ['blocking','warning','info']: raise ValueError('Invalid severity')
        validate_condition(rule['condition'], known)
        if rule.get('unit') and rule.get('field') and units.get(rule['field']) != rule['unit']: raise ValueError('Rule unit mismatch')
    if not 0<=float(policy.get('confidence_threshold',.7))<=1: raise ValueError('Confidence threshold must be 0–1')

def validate_expression(n, depth=0):
    if depth>20: raise ValueError('Expression too deep')
    if not isinstance(n,dict): decimal(n); return
    if 'field' in n: return
    if n.get('op') not in ['add','sub','mul','div','sum','avg','min','max','days_between']: raise ValueError('Unsupported operator')
    if n['op']=='days_between':
        if len(n.get('fields',[]))!=2: raise ValueError('Two date fields required')
        return
    args=n.get('args',[])
    if not args or (n['op'] in ['add','sub','mul','div'] and len(args)!=2): raise ValueError('Invalid argument count')
    for a in args: validate_expression(a,depth+1)

def validate_condition(c, known, depth=0):
    if depth>10: raise ValueError('Condition nesting limit reached')
    if 'all' in c or 'any' in c:
        children=c.get('all',c.get('any'))
        if not children: raise ValueError('Empty condition group')
        for child in children: validate_condition(child,known,depth+1)
        return
    if c.get('field') not in known: raise ValueError('Unknown condition field')
    if c.get('op') not in [*OPS,'present','between','age_lte']: raise ValueError('Unsupported condition')
    if c['op']!='present':
        for v in c.get('value',[]) if c['op']=='between' else [c.get('value')]: decimal(v)
        if c['op']=='between' and (len(c.get('value',[]))!=2 or decimal(c['value'][0])>decimal(c['value'][1])): raise ValueError('Invalid range')

def condition(c, facts):
    if 'all' in c or 'any' in c:
        values=[]
        for child in c.get('all',c.get('any')):
            try: values.append(condition(child,facts))
            except Missing: values.append(None)
        if 'all' in c and False in values: return False
        if 'any' in c and True in values: return True
        if None in values: raise Missing('Some condition inputs are missing')
        return all(values) if 'all' in c else any(values)
    v = facts.get(c['field'])
    if c['op']=='present': return v is not None and v!=''
    if c['op']=='age_lte':
        if not v: raise Missing('Report date missing')
        try: age=(date.today()-date.fromisoformat(str(v))).days
        except ValueError: raise Missing('Invalid report date')
        return 0<=age<=int(c['value'])
    a = decimal(v)
    if c['op']=='between': return decimal(c['value'][0])<=a<=decimal(c['value'][1])
    return OPS[c['op']](a, decimal(c['value']))

def evaluate(policy, facts, product, periods=None):
    validate_policy(policy)
    def applies(item):
        scope=item.get('product','both')
        return scope in ['both',product] or product in policy.get('product_groups',{}).get(scope,[])
    values=dict(facts); metrics=[]; pending=[m for m in policy.get('metrics',[]) if applies(m)]; periods=dict(periods or {})
    while pending:
        ready=[m for m in pending if not (references(m['formula']) & {x['key'] for x in pending})]
        if not ready: break
        for m in ready:
            try:
                relevant_periods={periods[k] for k in references(m['formula']) if periods.get(k)}
                if len(relevant_periods)>1: raise Missing('Reporting periods do not match; reconcile inputs first')
                v=expression(m['formula'],values); values[m['key']]=str(v.quantize(Decimal('.0001'))); reason=None
                if relevant_periods: periods[m['key']]=next(iter(relevant_periods))
            except (Missing,ValueError) as e: values[m['key']]=None; reason=str(e)
            metrics.append({**m,'value':values[m['key']],'reason':reason}); pending.remove(m)
    results=[]
    for r in policy.get('rules',[]):
        if not applies(r): result='not_applicable'; reason='Different lending product'
        else:
            try: result='pass' if condition(r['condition'],values) else 'fail'; reason=None
            except Missing as e: result='unable_to_assess'; reason=str(e)
        results.append({**r,'result':result,'reason':reason,'observed':values.get(r.get('condition',{}).get('field',''))})
    return {'metrics':metrics,'rules':results,'facts':values,'blocking':sum(r['severity']=='blocking' and r['result'] in ['fail','unable_to_assess'] for r in results)}

def emi(principal, annual_rate, months):
    p,r,n=decimal(principal),decimal(annual_rate)/Decimal(1200),int(months)
    if p<0 or r<0 or n<=0 or n>600: raise ValueError('Invalid loan terms')
    return (p/n if r==0 else p*r*(1+r)**n/((1+r)**n-1)).quantize(Decimal('.01'))
