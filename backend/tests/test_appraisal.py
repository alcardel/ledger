from app.appraisal import structured_appraisal


def test_structured_output_preserves_warning_and_excludes_dscr():
    summary=structured_appraisal({'snapshot':{'missing_documents':['GST returns','Stock statement']},'rules':[
        {'id':'cmr','result':'fail','severity':'warning','observed':7},
        {'id':'dscr','result':'not_applicable','severity':'blocking'},
        {'id':'score','result':'unable_to_assess','observed':None},
        {'id':'liquidity','result':'pass'}], 'decision':{'summary':'Extra model commentary'}})
    assert [r['id'] for r in summary['policy_failures']]==['cmr']
    assert summary['policy_failures'][0]['severity']=='warning'
    assert summary['policy_failures'][0]['observed']==7
    assert summary['not_applicable'][0]['id']=='dscr'
    assert summary['unable_to_assess'][0]['observed'] is None
    assert any('Collect and review GST returns' in step for step in summary['next_steps'])
    assert not any('DSCR' in step for step in summary['next_steps'])
    assert summary['additional_notes']==['Extra model commentary']


def test_next_steps_use_evidence_and_do_not_repeat_business_rank():
    result=structured_appraisal({'snapshot':{'facts':{'requested_amount':'30000000'},'unverified':['existing_emi'],'missing_documents':[], 'evidence_explanations':[]},'metrics':[{'key':'eligible_limit','value':'8000000'}],'rules':[
        {'name':'Business rank range','result':'unable_to_assess','condition':{'field':'commercial_cibil_rank'}},
        {'name':'Business rank threshold','result':'unable_to_assess','condition':{'field':'commercial_cibil_rank'}},
        {'name':'DSCR','result':'not_applicable'}]})
    steps=result['next_steps']
    assert sum('Obtain the business credit report' in s for s in steps)==1
    assert any('existing monthly EMI' in s for s in steps)
    assert any('₹3 crore' in s and '₹80 lakh' in s for s in steps)
    assert not any('Collect and review' in s or 'DSCR' in s for s in steps)
