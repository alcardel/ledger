"""Evidence-grounded presentation of immutable assessment results."""
from decimal import Decimal, InvalidOperation


def field_name(key, snapshot):
    catalog=snapshot.get('policy',{}).get('fields',[])
    for field in catalog:
        if field.get('key')==key: return field.get('label') or field.get('name') or key.replace('_',' ')
    return {'commercial_cibil_rank':'business credit rank', 'existing_emi':'existing monthly EMI',
            'statement_months':'bank statement coverage', 'requested_amount':'requested loan amount'}.get(key,key.replace('_',' '))


def condition_fields(condition):
    if condition.get('field'): return [condition['field']]
    return [key for op in ('all','any') for child in condition.get(op,[]) for key in condition_fields(child)]


def rupees(value):
    amount=Decimal(str(value))
    if abs(amount)>=10000000: return f'₹{(amount/10000000).normalize():f} crore'
    if abs(amount)>=100000: return f'₹{(amount/100000).normalize():f} lakh'
    return f'₹{amount:,.0f}'

def structured_appraisal(assessment):
    rules=assessment.get('rules',[])
    snapshot=assessment.get('snapshot',{})
    model=assessment.get('decision') or assessment.get('jev') or {}
    failed=[r for r in rules if r.get('result')=='fail']
    missing=snapshot.get('missing_documents',[])
    unknown=[r for r in rules if r.get('result')=='unable_to_assess']
    actions=[]
    for document in missing:
        actions.append(f'Collect and review {document}. Upload the source document and verify the extracted information.')
    requested=set()
    for rule in unknown:
        fields=condition_fields(rule.get('condition',{}))
        new_fields=[key for key in fields if key not in requested]
        if fields and not new_fields: continue
        requested.update(new_fields)
        if 'commercial_cibil_rank' in new_fields:
            actions.append('Obtain the business credit report and verify its commercial rank. If the business has no rank yet, document this and refer the case for an authorized policy exception; the promoter’s personal score does not replace it.')
        elif new_fields:
            actions.append('Obtain and verify '+', '.join(field_name(key,snapshot) for key in new_fields)+f" to assess: {rule.get('name','the outstanding policy check')}.")
        else:
            actions.append(f"Obtain supporting evidence for {rule.get('name','the outstanding policy check')} and reassess it.")
    for key in snapshot.get('unverified',[]):
        actions.append(f'Verify {field_name(key,snapshot)} against its source and correct any extraction errors before relying on it for a decision.')
    for rule in failed:
        disposition='Resolve this approval block or obtain an explicit administrator override.' if rule.get('severity')=='blocking' else 'Record the risk review and any required conditions.'
        observed=f" Recorded value: {rule['observed']}." if rule.get('observed') is not None else ''
        actions.append(f"Review the failed check: {rule.get('name','Policy requirement')}.{observed} {disposition}")
    metrics={m.get('key'):m.get('value') for m in assessment.get('metrics',[])}
    amount=snapshot.get('facts',{}).get('requested_amount')
    limit=metrics.get('eligible_limit')
    try:
        if amount is not None and limit is not None and Decimal(str(amount))>Decimal(str(limit)):
            actions.append(f'Reconsider the {rupees(amount)} request against the {rupees(limit)} indicative eligible limit. Discuss a lower facility or obtain additional eligible stock / receivables evidence and recalculate. This is not a sanctioned amount.')
    except (InvalidOperation,ValueError): pass
    for explanation in snapshot.get('evidence_explanations',[]):
        if explanation.get('review_status')=='pending_review':
            actions.append(f"Review the explanation for {explanation.get('document_type','evidence').replace('_',' ')}: {explanation.get('reason','No explanation recorded')} Record whether more evidence or an authorized exception is needed.")
    if actions: actions.append('After the evidence is verified and outstanding concerns are addressed, review the updated assessment and record the officer’s decision.')
    else: actions.append('Review the completed policy checks and supporting evidence, confirm the proposed terms, and record the officer’s decision.')
    return {
        'next_steps':actions,
        'approval_holds':assessment.get('gates',[]),
        'policy_failures':failed,
        'missing_documents':missing,
        'unable_to_assess':unknown,
        'unverified_fields':snapshot.get('unverified',[]),
        'passed_checks':[r for r in rules if r.get('result')=='pass'],
        'not_applicable':[r for r in rules if r.get('result')=='not_applicable'],
        'additional_notes':[n for n in [assessment.get('provider_error'), model.get('summary')] if n],
        'evidence_explanations':snapshot.get('evidence_explanations',[]),
    }
