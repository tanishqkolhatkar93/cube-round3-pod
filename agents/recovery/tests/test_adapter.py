import copy
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from agents.pack.tests.test_adapter import Harness
from agents.prep.common import Rejected
from agents.recovery import app
adapter = app
from shared.utils.records import build_record, check
from shared.utils.hashing import verify, seal
from shared.utils.schema import errors


def record(h,stage='prep',verdict='PASS'):
    req={**h.request,'stage':stage,'previous_evidence':[]}
    return build_record(req,agent_id=h.binding['trusted_agents'][stage][0],record_id={'prep':'PRP','receiving':'RCV','pack':'PCK','returns':'RTN'}[stage]+'-a',
        captured_at='2026-10-01T10:00:00Z',checks=[check('inspection',verdict,None)],outcome='compliant',
        reason='test judgment',model={'name':'fixture','version':'1','calls':1},unit_scope='unit')


@pytest.fixture
def h(tmp_path,monkeypatch):
    h=Harness(tmp_path,monkeypatch,'recovery')
    h.binding.pop('order_lines');h.binding['refs']={}
    h.report={'org_id':'org-a','subject_id':'unit-a','workflow_id':'wf-a','complete':True,'line_count':1,
              'lines':[{'line_id':'fee-a','charge_type':'inbound_defect_fee','amount_usd':'4.25',
                        'currency':'USD','unit_scope':'unit','refs':{}}]}
    def update():
        h.binding['files']=[];h.request['inputs']=[]
        h.add('report.json',json.dumps(h.report).encode(),'document');h.save()
    h.update=update;update()
    h.request['previous_evidence']=[record(h)]
    assert errors('agent-input',h.request)==[]
    monkeypatch.setattr(adapter,'invoke',h.invoke)
    return h


def test_actual_report_deterministic_claim_and_replay(h):
    out=app.handle(h.request)
    assert errors('agent-output',out)==[] and verify(out['evidence'])
    assert out['verdict']=='FAIL' and out['evidence']['payload']['claimable_usd']==4.25
    assert out['evidence']['payload']['charges'][0]['evidence_record_ids']==['PRP-a']
    assert out['model']['calls']==0 and out['model']['name']=='none'
    assert app.handle(h.request)==out


@pytest.mark.parametrize('change',['missing','incomplete','count','empty_unproven','foreign_report','bad_money','bool_money','currency','duplicate','scope'])
def test_invalid_source_never_claims_or_passes(h,change):
    if change=='missing':h.request['inputs']=[]
    else:
        if change=='incomplete':h.report['complete']=False
        elif change=='count':h.report['line_count']=2
        elif change=='empty_unproven':h.report['lines']=[]
        elif change=='foreign_report':h.report['org_id']='foreign'
        elif change=='bad_money':h.report['lines'][0]['amount_usd']='NaN'
        elif change=='bool_money':h.report['lines'][0]['amount_usd']=True
        elif change=='currency':h.report['lines'][0]['currency']='EUR'
        elif change=='duplicate':h.report['lines']*=2;h.report['line_count']=2
        elif change=='scope':h.report['lines'][0]['refs']={'order_id':'other'}
        h.update()
    out=app.handle(h.request)
    assert out['verdict']=='UNCERTAIN' and out['status']=='pending'
    assert out['evidence']['payload']['claimable_usd']==0 and h.calls==0


def test_explicit_trusted_zero_line_report_proves_no_fees(h):
    h.report.update(lines=[],line_count=0);h.update()
    out=app.handle(h.request)
    assert out['verdict']=='PASS' and out['evidence']['checks'][0]['check_key']=='complete_report_has_no_fees'
    assert out['evidence']['checks'][0]['evidence_refs']==['report.json']


@pytest.mark.parametrize('change',['hash','org','unit','workflow','unit_id','scope','agent','refs','duplicate','unknown_upstream','check_ref','agent_override','rollup','empty_checks','prefix'])
def test_upstream_integrity_is_enforced_before_financial_rules(h,change):
    r=h.request['previous_evidence'][0]
    if change=='hash':r['content_hash']='0'*64
    elif change=='org':r['subject']['org_id']='other'
    elif change=='unit':r['subject']['subject_id']='other'
    elif change=='workflow':r['workflow_id']='other'
    elif change=='unit_id':r['subject']['unit_id']='other'
    elif change=='scope':r['subject']['unit_scope']='po_line'
    elif change=='agent':r['agent_id']='untrusted'
    elif change=='refs':h.binding['refs']={'sku':'expected'};h.save();r['subject']['refs']={'sku':'other'}
    elif change=='duplicate':h.request['previous_evidence'].append(copy.deepcopy(r))
    elif change=='unknown_upstream':r['upstream_refs']=['absent']
    elif change=='check_ref':r['checks'][0]['evidence_refs']=['absent']
    elif change=='rollup':r['checks'][0]['verdict']='FAIL'
    elif change=='empty_checks':r['checks']=[]
    elif change=='prefix':r['record_id']='PCK-forged-prefix'
    elif change=='agent_override':r['overrides']=[{'overridden_at':'2026-01-01T00:00:00Z','overridden_by':'x','target':'decision','original_verdict':'PASS','new_verdict':'FAIL','reason':'untrusted'}]
    if change!='hash':h.request['previous_evidence'][0]=seal(r)
    with pytest.raises(Rejected):app.handle(h.request)
    assert h.calls==0


def test_scope_mismatch_cannot_support_fee(h):
    h.report['lines'][0]['unit_scope']='order';h.update()
    out=app.handle(h.request)
    assert out['verdict']=='UNCERTAIN' and out['evidence']['payload']['claimable_usd']==0


@pytest.mark.parametrize('scope',['order','po_line'])
def test_scoped_fee_requires_explicit_join_keys(h,scope):
    h.report['lines'][0]['unit_scope']=scope;h.update()
    out=app.handle(h.request)
    assert out['status']=='pending' and out['error']['code']=='invalid_or_incomplete_report'
    assert out['evidence']['payload']['claimable_usd']==0


def test_override_requires_registration_new_request_and_preserves_original(h):
    original=app.handle(h.request)
    override={'override_id':'OVR-1','supersedes':{'record_id':'PRP-a','override_id':None},'target':'decision',
              'actor':'reviewer','at':'2026-10-01T12:00:00Z','reason':'manual inspection',
              'original_verdict':'PASS','previous_verdict':'PASS','new_verdict':'FAIL'}
    h.request['context']['overrides']=[override]
    with pytest.raises(Rejected,match='unauthorized_override'):app.handle(h.request)
    h.binding['trusted_overrides']=[override];h.save()
    with pytest.raises(Rejected,match='request_content_conflict'):app.handle(h.request)
    h.request['request_id']='reassessment'
    out=app.handle(h.request)
    assert out['verdict']=='PASS' and out['evidence']['payload']['claimable_usd']==0
    assert original['evidence']['payload']['claimable_usd']==4.25 and verify(original['evidence'])
    assert h.request['previous_evidence'][0]['decision']['verdict']=='PASS'


def unresolved(h):
    h.report['lines']=[{**h.report['lines'][0],'line_id':name,'charge_type':'registered_fee'} for name in ('a','b')]
    h.report['line_count']=2
    h.binding['fee_policies']={'registered_fee':{'version':'test-v1','text':'Explicit synthetic eligibility policy'}}
    h.update()
    h.response={'results':[{'line_id':name,'position':'CONTRADICTS','confidence':.9,'reason':'Evidence under registered policy',
                            'evidence_record_ids':['PRP-a']} for name in ('a','b')]}


def test_two_unresolved_fees_use_one_batched_call(h):
    unresolved(h)
    out=app.handle(h.request)
    assert out['evidence']['payload']['claimable_usd']==8.5 and h.calls==1 and out['model']['calls']==1
    assert app.handle(h.request)==out and h.calls==1


@pytest.mark.parametrize('change',['foreign_ref','missing_ref','missing_line','duplicate','invalid_position','nan_confidence','extra_field'])
def test_strict_batch_response_cannot_fabricate_claims(h,change):
    unresolved(h);c=h.response['results'][0]
    if change=='foreign_ref':c['evidence_record_ids']=['foreign']
    elif change=='missing_ref':c['evidence_record_ids']=[]
    elif change=='missing_line':h.response['results'].pop()
    elif change=='duplicate':h.response['results'][1]['line_id']='a'
    elif change=='invalid_position':c['position']='PASS'
    elif change=='nan_confidence':c['confidence']=float('nan')
    elif change=='extra_field':h.response['verdict']='claim'
    out=app.handle(h.request)
    assert out['status']=='pending' and out['evidence']['payload']['claimable_usd']==0
    assert out['model']['calls']==1


@pytest.mark.parametrize('code',['provider_timeout','provider_cleanup_failure','provider_unavailable'])
def test_provider_failure_preserves_call_identity_and_attempts(h,code):
    unresolved(h);h.failure=code
    out=app.handle(h.request)
    assert out['status']=='pending' and out['model']['calls']==1 and out['model']['version']=='fixture-version'
    assert out['evidence']['payload']['provider_attempts'][0]['outcome']==code
    assert app.handle(h.request)==out and h.calls==1


@pytest.mark.parametrize('m',[{}, {'weight_g':-1}, {'weight_g':float('nan')}, {'weight_g':True}, 'invalid'])
def test_invalid_measurements_never_reach_model(h,m):
    h.report['lines'][0]['charge_type']='fulfilment_fee_weight_tier';h.update()
    h.binding['fee_policies']={'fulfilment_fee_weight_tier':{'version':'v1','text':'test policy'}};h.save()
    r=h.request['previous_evidence'][0];r['payload']['measurements']=m
    # NaN is rejected at the request JSON boundary; all other invalid blobs stay silent.
    if isinstance(m,dict) and any(isinstance(v,float) and v!=v for v in m.values()):
        with pytest.raises(Rejected):app.handle(h.request)
    else:
        h.request['previous_evidence'][0]=seal(r)
        out=app.handle(h.request)
        assert out['verdict']=='UNCERTAIN' and out['evidence']['payload']['claimable_usd']==0
    assert h.calls==0


def test_unknown_policy_is_silent_and_not_delegated(h):
    h.report['lines'][0]['charge_type']='unknown_fee';h.update()
    out=app.handle(h.request)
    assert out['verdict']=='UNCERTAIN' and h.calls==0


def test_direct_http_validation_parity_and_concurrent_replay(h):
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda _:app.handle(h.request),range(3)))
    assert all(r==results[0] for r in results)
    with TestClient(app.app) as client:
        assert client.post('/run',json=h.request).json()==results[0]
        h.request['previous_evidence'][0]['content_hash']='0'*64
        assert client.post('/run',json=h.request).status_code==422
        with pytest.raises(Rejected):app.handle(h.request)
