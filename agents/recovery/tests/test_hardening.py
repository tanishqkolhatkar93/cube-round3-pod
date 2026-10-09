import copy
import json
import subprocess
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from agents.recovery import app, gemini_client as provider
from agents.prep.common import Rejected
from shared.utils.hashing import seal
from shared.utils.records import build_record
from .test_adapter import h, unresolved
from .worker_fixtures import stalled


@pytest.mark.parametrize('change',['valid_mm','boolean','contradictory','partial'])
def test_owner_measurement_units_remain_strict(change):
    from agents.recovery.reports import measurements_valid
    m={'weight_g':10,'length_mm':20,'width_mm':30,'height_mm':40}
    if change=='boolean':m['weight_g']=True
    if change=='contradictory':m.update(length_cm=9,width_cm=3,height_cm=4)
    if change=='partial':m['length_cm']=2
    assert measurements_valid({'payload':{'measurements':m}})==(change=='valid_mm')


def test_scoped_replay_does_not_return_another_tenants_record(h):
    first=app.handle(h.request)
    foreign=copy.deepcopy(h.request);foreign['subject']['org_id']='org-b'
    foreign['previous_evidence']=[]
    with pytest.raises(Rejected,match='source_not_found'):app.handle(foreign)
    binding=copy.deepcopy(h.binding);binding['org_id']='org-b';binding['files']=[]
    h.config['bindings'].append(binding);h.save();foreign['inputs']=[]
    other=app.handle(foreign)
    assert other['evidence']['record_id']!=first['evidence']['record_id']
    assert other['evidence']['subject']['org_id']=='org-b' and other['status']=='pending'
    assert app.handle(h.request)==first


@pytest.mark.parametrize('change',['stage','org','workflow','schema','hash','unit','agent','scope'])
def test_invalid_requests_rejected_in_both_paths(h,change):
    request=copy.deepcopy(h.request)
    if change=='stage':request['stage']='pack'
    elif change=='org':request['subject']['org_id']='foreign'
    elif change=='workflow':request['workflow_id']='foreign'
    elif change=='schema':request.pop('request_id')
    else:
        r=request['previous_evidence'][0]
        if change=='hash':r['content_hash']='0'*64
        elif change=='unit':r['subject']['unit_id']='foreign'
        elif change=='agent':r['agent_id']='untrusted'
        elif change=='scope':r['subject']['unit_scope']='order'
        if change!='hash':request['previous_evidence'][0]=seal(r)
    with pytest.raises(Rejected) as error:app.handle(request)
    with TestClient(app.app) as client:
        assert client.post('/run',json=request).status_code==error.value.status
    assert h.calls==0


def test_replay_restart_and_conflict_preserve_output(h):
    original=app.handle(h.request)
    result=subprocess.run([sys.executable,'-B','-c',
        'import sys,json;from agents.recovery.app import handle;print(json.dumps(handle(json.load(sys.stdin))))'],
        input=json.dumps(h.request),text=True,capture_output=True,check=True)
    assert json.loads(result.stdout)==original
    changed=copy.deepcopy(h.request);changed['context']['additional']='changed'
    with pytest.raises(Rejected,match='request_content_conflict'):app.handle(changed)
    assert app.handle(h.request)==original


def test_missing_registered_input_is_review_not_complete(h):
    h.request['inputs']=[]
    out=app.handle(h.request)
    assert out['status']=='pending' and out['verdict']=='UNCERTAIN'
    assert out['evidence']['decision']['needs_human']
    assert out['next_step_recommendation']['action']=='review'


def test_explicit_empty_upstream_refs_are_not_replaced(h):
    record=build_record(h.request,agent_id='recovery-manager@2',record_id='RCY-test',
        captured_at=h.binding['captured_at'],checks=[],outcome='insufficient_evidence',
        reason='test',model={'name':'none','version':'0','calls':0},upstream_refs=[])
    assert record['upstream_refs']==[]
    kwargs=dict(agent_id='recovery-manager@2',record_id='RCY-test',captured_at=h.binding['captured_at'],
        checks=[],outcome='insufficient_evidence',reason='test',model={'name':'none','version':'0','calls':0})
    assert build_record(h.request,**kwargs)['upstream_refs']==['PRP-a']


@pytest.mark.parametrize('fault',[None,'cleanup','timeout','truncated','malformed','initialize','missing_key'])
def test_real_worker_accounting_and_handler_pending(h,monkeypatch,fault):
    unresolved(h);sent=[];closed=[]
    class Client:
        def __init__(self,**kw):
            if fault=='initialize':raise RuntimeError('PRIVATE init')
        def post(self,*a,**kw):
            sent.append(kw)
            if fault=='timeout':raise httpx.ReadTimeout('PRIVATE timeout')
            body={'modelVersion':'returned-version','usageMetadata':{'cachedContentTokenCount':4},
                'candidates':[{'finishReason':'MAX_TOKENS' if fault=='truncated' else 'STOP',
                  'content':{'parts':[{'text':'bad' if fault=='malformed' else json.dumps(h.response)}]}}]}
            return httpx.Response(200,json=body,request=httpx.Request('POST','https://example.invalid'))
        def close(self):
            closed.append(True)
            if fault=='cleanup':raise RuntimeError('PRIVATE cleanup')
    monkeypatch.setattr(provider.httpx,'Client',Client)
    class Channel:
        def __init__(self):self.events=[]
        def send(self,event):self.events.append(event)
        def close(self):pass
    def invoke(selection,prompt,payload,images,stats):
        channel=Channel()
        if fault=='missing_key':
            monkeypatch.delenv('RECOVERY_ABSENT',raising=False)
            return provider.invoke({'model':'selected','api_key_env':'RECOVERY_ABSENT','deadline_s':1},prompt,payload,images,stats)
        provider.worker(channel,{'model':'selected','deadline_s':1},'synthetic',prompt,payload,images)
        for event in channel.events:
            if event['event']=='attempt':
                stats['calls']+=1;stats['model']=event['model'];stats['attempts'].append({'model':event['model'],'outcome':'started'})
            elif event['event']=='accounting':
                stats['version']=event['version'];stats['usage']=event.get('usage',stats.get('usage',{}))
        last=channel.events[-1]
        if stats['attempts']:stats['attempts'][-1]['outcome']=last.get('error','success')
        return last.get('data'),last.get('error')
    monkeypatch.setattr(app,'invoke',invoke)
    out=app.handle(h.request)
    assert out['model']['calls']==len(sent)==(0 if fault in ('initialize','missing_key') else 1)
    assert out['status']==('completed' if fault is None else 'pending')
    assert 'PRIVATE' not in json.dumps(out) and 'synthetic' not in json.dumps(out)
    assert 'cost_usd' not in out['model']
    if fault not in ('initialize','missing_key','timeout'):
        assert out['model']['version']=='returned-version'
        assert out['evidence']['payload']['provider_usage']['cachedContentTokenCount']==4
    assert app.handle(h.request)==out


def test_deadline_kills_cleanup_and_keeps_prior_accounting(monkeypatch):
    monkeypatch.setenv('RECOVERY_TEST_KEY','synthetic');monkeypatch.setattr(provider,'worker',stalled)
    stats={'calls':1,'model':'earlier','version':'earlier-version','attempts':[{'model':'earlier','outcome':'success'}]}
    start=time.monotonic()
    result,code=provider.invoke({'model':'selected','api_key_env':'RECOVERY_TEST_KEY','deadline_s':3},'',{},[],stats)
    assert result is None and code=='provider_timeout' and time.monotonic()-start<6
    assert stats['calls']==2 and len(stats['attempts'])==2
    assert stats['attempts'][0]['outcome']=='success' and stats['attempts'][1]['outcome']=='provider_timeout'
    assert stats['usage']['cachedContentTokenCount']==3


def test_processing_deadline_discards_completed_claim(h,monkeypatch):
    h.config['provider']={'model':'test','api_key_env':'UNUSED','deadline_s':.05};h.save()
    original=app._load_fee_lines
    def slow(*args):time.sleep(.08);return original(*args)
    monkeypatch.setattr(app,'_load_fee_lines',slow)
    out=app.handle(h.request)
    assert out['status']=='pending' and out['error']['code']=='processing_deadline_exceeded'
    assert out['evidence']['payload']['claimable_usd']==0
