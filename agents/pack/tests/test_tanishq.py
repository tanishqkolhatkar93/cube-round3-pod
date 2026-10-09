"""Regression coverage of the repaired Tanishq SDK -> real Pack handler path."""
import copy
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from google.genai import types
from agents.pack import app, safety, vision
from agents.prep.common import Rejected
from shared.utils.hashing import seal, verify
from shared.utils.records import build_record, check
from .test_adapter import h  # explicit registration/ledger fixture
from .worker_fixtures import stalled_sdk


def advisory(verdict='SEAL', **flags):
    return {'verdict':verdict,'checks_performed':dict(
        all_items_present=True,quantities_correct=True,no_extra_items=True,**flags)}


@pytest.mark.parametrize('verdict',['UNCERTAIN','STOP_AND_FIX'])
def test_negative_advisory_never_becomes_pass(h,verdict):
    h.response['assessment']=advisory(verdict)
    out=app.handle(h.request)
    assert out['status']=='pending' and out['verdict']=='UNCERTAIN'
    assert out['evidence']['decision']['outcome']=='pending_review'
    assert len(out['evidence']['checks'])==3
    assert {c['verdict'] for c in out['evidence']['checks']}=={'UNCERTAIN'}
    assert app.handle(h.request)==out and h.calls==1


@pytest.mark.parametrize('kind',['missing','extra','count'])
def test_model_seal_cannot_override_observed_defects(h,kind):
    h.response['assessment']=advisory()
    items=h.response['images'][0]['items']
    if kind=='missing':items.clear()
    elif kind=='extra':items.append({'sku':'FOREIGN','quantity':1})
    else:items[0]['quantity']=100
    out=app.handle(h.request)
    assert out['verdict']=='FAIL' and out['evidence']['decision']['outcome']=='stop_and_fix'
    assert any(c['verdict']=='FAIL' for c in out['evidence']['checks'])


def test_model_check_failure_cannot_grant_seal(h):
    h.response['assessment']=advisory()
    h.response['assessment']['checks_performed']['quantities_correct']=False
    out=app.handle(h.request)
    assert out['status']=='pending' and out['error']['code']=='model_rule_disagreement'


@pytest.mark.parametrize('quantity',[0,1,2,3])
@pytest.mark.parametrize('extra',[False,True])
@pytest.mark.parametrize('complete',[False,True])
def test_synthetic_decision_grid(h,quantity,extra,complete):
    """16 declared truth cases; measures rule behavior, never model accuracy."""
    view=h.response['images'][0]
    view['complete']=complete
    view['items']=([{'sku':'SKU-A','quantity':quantity}] if quantity else [])
    if extra:view['items'].append({'sku':'OTHER','quantity':1})
    h.response['assessment']=advisory()  # Adversarial SEAL even for wrong contents.
    out=app.handle(h.request)
    expected='UNCERTAIN' if not complete else ('PASS' if quantity==2 and not extra else 'FAIL')
    assert out['verdict']==expected
    assert (out['evidence']['decision']['outcome']=='seal')==(expected=='PASS')
    expected_checks = {'items_present':'PASS' if quantity else 'FAIL',
                       'quantities_correct':'PASS' if quantity==2 else 'FAIL',
                       'no_extra_items':'FAIL' if extra else 'PASS'}
    if not complete:expected_checks={key:'UNCERTAIN' for key in expected_checks}
    assert {c['check_key']:c['verdict'] for c in out['evidence']['checks']}==expected_checks


@pytest.mark.parametrize('change',['hash','tenant','unit','workflow','scope','agent','reference'])
def test_upstream_validation_in_both_transports(h,change):
    req={**h.request,'stage':'receiving'}
    record=build_record(req,agent_id='receiving-manager@1.0.0',record_id='RCV-test',
        captured_at=h.binding['captured_at'],unit_scope='po_line',refs={'po_number':'p','po_line':'1'},
        checks=[check('qty','PASS',None)],outcome='received',reason='synthetic',model={'name':'none','version':'1','calls':0})
    if change=='hash':record['content_hash']='0'*64
    elif change=='tenant':record['subject']['org_id']='foreign'
    elif change=='unit':record['subject']['subject_id']='foreign'
    elif change=='workflow':record['workflow_id']='foreign'
    elif change=='scope':record['subject']['unit_scope']='order'
    elif change=='agent':record['agent_id']='untrusted'
    elif change=='reference':record['upstream_refs']=['RCV-unknown']
    if change!='hash':record=seal(record)
    h.request['previous_evidence']=[record]
    with pytest.raises(Rejected):app.handle(h.request)
    with TestClient(app.app) as client:assert client.post('/run',json=h.request).status_code in (404,422)
    assert h.calls==0


def test_pending_calls_shared_helper_and_keeps_real_source_hash(h,monkeypatch):
    original=safety.shared_pending_output;seen=[]
    def tracked(*a,**k):seen.append(k['code']);return original(*a,**k)
    monkeypatch.setattr(safety,'shared_pending_output',tracked)
    h.failure='provider_timeout';out=app.handle(h.request)
    assert seen==['provider_timeout'] and out['status']=='pending'
    assert out['evidence']['inputs']==h.request['inputs'] and verify(out['evidence'])
    assert out['model']['calls']==1 and 'cost_usd' not in out['model']


class Channel:
    def __init__(self):self.events=[]
    def send(self,event):self.events.append(event)
    def close(self):pass


@pytest.mark.parametrize('failure',[None,'initialize','call','timeout','cleanup','both','malformed','overflow','partial','blocked'])
def test_actual_sdk_worker_accounting_bytes_cleanup_and_entrypoint(h,monkeypatch,failure):
    closed=[];requests=[]
    raw={'images':copy.deepcopy(h.response['images']), 'observed_items':'SKU-A x2',
         'checks_performed':advisory()['checks_performed'],'verdict':'SEAL','reasoning':'Visible SKU and count'}
    class Client:
        @property
        def models(self):return self
        def generate_content(self,**kwargs):
            requests.append(kwargs)
            assert kwargs['model']=='selected-model'
            assert kwargs['contents'][2].inline_data.data==(h.root/'front.png').read_bytes()
            assert kwargs['contents'][2].inline_data.mime_type=='image/png'
            assert kwargs['config'].automatic_function_calling.disable is True
            if failure in ('call','both'):raise RuntimeError('PRIVATE diagnostic')
            if failure=='timeout':raise httpx.ReadTimeout('PRIVATE diagnostic')
            return SimpleNamespace(model_version='actual-version',usage_metadata=SimpleNamespace(
                prompt_token_count=17,candidates_token_count=9,cached_content_token_count=4,total_token_count=26),
                candidates=[SimpleNamespace(finish_reason=types.FinishReason.MAX_TOKENS if failure=='partial' else types.FinishReason.STOP)],
                prompt_feedback=SimpleNamespace(block_reason='SAFETY') if failure=='blocked' else None,
                text='not JSON' if failure=='malformed' else '{"x":1e999}' if failure=='overflow' else json.dumps(raw))
        def close(self):
            closed.append(True)
            if failure in ('cleanup','both'):raise RuntimeError('PRIVATE close')
    def factory(selection,key):
        if failure=='initialize':raise RuntimeError('PRIVATE init')
        return Client()
    monkeypatch.setattr(vision,'get_client',factory)
    def sdk(selection,prompt,payload,images,stats):
        channel=Channel();safety.worker(channel,{'model':'selected-model','deadline_s':1},'fake-key',prompt,payload,images)
        for event in channel.events:
            if event['event']=='attempt':stats.update(calls=stats['calls']+1,model=event['model']);stats['attempts'].append({'model':event['model'],'outcome':'started'})
            elif event['event']=='accounting':stats.update(version=event['version'],usage=event.get('usage',stats.get('usage',{})))
        last=channel.events[-1];code=last.get('error')
        if stats['attempts']:stats['attempts'][-1]['outcome']=code or 'success'
        return last.get('data'),code
    monkeypatch.setattr(app,'invoke',sdk)
    out=app.handle(h.request)
    assert out['model']['calls']==(0 if failure=='initialize' else 1)
    assert len(requests)==(0 if failure=='initialize' else 1)
    assert len(closed)==(0 if failure=='initialize' else 1)
    assert out['status']==('completed' if failure is None else 'pending')
    assert 'PRIVATE' not in json.dumps(out) and 'fake-key' not in json.dumps(out)
    assert 'cost_usd' not in out['model'] and verify(out['evidence'])
    if failure not in ('initialize','call','both','timeout'):
        assert out['model']['version']=='actual-version'
        assert out['evidence']['payload']['provider_usage']['cached_content_token_count']==4
    assert app.handle(h.request)==out


def test_sdk_client_disables_retries_and_sets_timeout(monkeypatch):
    captured={}
    monkeypatch.setattr(vision.genai,'Client',lambda **kw:captured.update(kw))
    vision.get_client({'deadline_s':.5},'synthetic-key')
    assert captured['http_options'].timeout==500
    assert captured['http_options'].retry_options.attempts==1


def test_no_credentials_performs_no_call(h,monkeypatch):
    h.config['provider']={'model':'sdk-model','api_key_env':'PACK_TEST_ABSENT','deadline_s':1};h.save()
    monkeypatch.delenv('PACK_TEST_ABSENT',raising=False);monkeypatch.setattr(app,'invoke',safety.invoke)
    out=app.handle(h.request)
    assert out['status']=='pending' and out['model']['calls']==0
    assert out['model']['name']=='none' and out['evidence']['payload']['provider_attempts']==[]


def test_sdk_supervisor_cancels_cleanup_hang_and_keeps_usage(monkeypatch):
    monkeypatch.setenv('PACK_TEST_KEY','synthetic');monkeypatch.setattr(safety,'worker',stalled_sdk)
    stats={'calls':0,'attempts':[]};start=time.monotonic()
    result,code=safety.invoke({'model':'sdk','api_key_env':'PACK_TEST_KEY','deadline_s':3},'',{},[],stats)
    assert code=='provider_timeout' and result is None and time.monotonic()-start<6
    assert stats['calls']==1 and stats['version']=='sdk-version'
    assert stats['usage']['cached_content_token_count']==3
