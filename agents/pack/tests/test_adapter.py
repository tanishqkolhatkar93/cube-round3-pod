import copy
import hashlib
import io
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from agents.pack import adapter, app
from agents.prep.common import Rejected
from shared.utils.hashing import verify
from shared.utils.schema import errors


class Harness:
    def __init__(self, root, monkeypatch, stage='pack'):
        self.root, self.stage = root, stage
        root.mkdir(parents=True, exist_ok=True)
        self.config = {'version': 1, 'bindings': [{
            'org_id': 'org-a', 'subject_id': 'unit-a', 'workflow_id': 'wf-a',
            'captured_at': '2026-10-01T10:00:00Z', 'files': [],
            'refs': {'order_id': 'order-a'}, 'order_lines': {'SKU-A': 2},
            'trusted_agents': {'receiving': ['receiving-manager@1.0.0'], 'prep': ['pod14-prep-manager@1'],
                               'pack': ['pack-manager@2'], 'returns': ['returns-manager@1']}}]}
        self.binding = self.config['bindings'][0]
        self.request = {'schema_version': '1.0', 'stage': stage, 'request_id': 'req-a', 'workflow_id': 'wf-a',
                        'subject': {'org_id': 'org-a', 'subject_id': 'unit-a', 'route': 'mfn'},
                        'inputs': [], 'previous_evidence': [], 'context': {}}
        self.path = root/'config.json'
        monkeypatch.setenv(stage.upper()+'_CONFIG', str(self.path))
        monkeypatch.setenv(stage.upper()+'_STATE_DIR', str(root/'state'))
        self.calls = 0
        self.response = None
        self.failure = None
        if stage == 'pack':
            b = io.BytesIO(); Image.new('RGB', (40, 40), (150,100,50)).save(b, 'PNG')
            self.add('front.png', b.getvalue(), 'image')
            self.response = {'images': [{'ref': 'front.png', 'usable': True, 'complete': True,
                                         'items': [{'sku': 'SKU-A', 'quantity': 2}]}]}
            monkeypatch.setattr(adapter, 'invoke', self.invoke)
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.config))

    def add(self, ref, raw, kind):
        (self.root/ref).write_bytes(raw)
        item = {'ref': ref, 'path': ref, 'sha256': hashlib.sha256(raw).hexdigest(), 'kind': kind}
        self.binding['files'].append(item)
        self.request['inputs'].append({k:item[k] for k in ('ref','sha256','kind')})
        return item

    def invoke(self, config, prompt, payload, images, stats):
        self.calls += 1
        stats.update(provider='test',calls=1, model='offline-fixture', version='fixture-version',
                     attempts=[{'model':'offline-fixture','outcome': self.failure or 'success'}])
        return copy.deepcopy(self.response), self.failure


@pytest.fixture
def h(tmp_path, monkeypatch):
    return Harness(tmp_path, monkeypatch)


def test_real_entry_success_and_replay(h):
    out = app.handle(h.request)
    assert out['status']=='completed' and out['verdict']=='PASS'
    assert out['evidence']['decision']['outcome']=='seal'
    assert errors('agent-output',out)==[] and verify(out['evidence'])
    assert app.handle(h.request)==out and h.calls==1
    assert out['model']['version']=='fixture-version'


@pytest.mark.parametrize('change', ['empty', 'missing_file', 'invalid_image'])
def test_required_images_prevent_pass(h, change):
    if change=='empty': h.request['inputs']=[]
    elif change=='missing_file': (h.root/'front.png').unlink()
    else:
        raw=b'not an image'; (h.root/'front.png').write_bytes(raw)
        sha=hashlib.sha256(raw).hexdigest()
        h.binding['files'][0]['sha256']=sha;h.request['inputs'][0]['sha256']=sha;h.save()
    out=app.handle(h.request)
    assert out['status']=='pending' and out['verdict']=='UNCERTAIN' and h.calls==0
    assert out['model']['calls']==0 and out['model']['name']=='none'


@pytest.mark.parametrize('change', ['org','unit','workflow','hash','tamper','foreign_ref','duplicate','traversal','alias','route'])
def test_ownership_and_integrity(h,change):
    if change=='org':h.request['subject']['org_id']='other'
    elif change=='unit':h.request['subject']['subject_id']='other'
    elif change=='workflow':h.request['workflow_id']='other'
    elif change=='hash':h.request['inputs'][0]['sha256']='0'*64
    elif change=='tamper':(h.root/'front.png').write_bytes(b'tampered')
    elif change=='foreign_ref':h.request['inputs'][0]['ref']='other.png'
    elif change=='duplicate':h.request['inputs']*=2
    elif change=='traversal':h.request['inputs'][0]['ref']='../front.png'
    elif change=='alias':h.request['inputs'][0]['ref']='a\\front.png'
    elif change=='route':h.request['subject']['route']='fba'
    with pytest.raises(Rejected):app.handle(h.request)
    assert h.calls==0


@pytest.mark.parametrize('items', [[], [{'sku':'SKU-A','quantity':1}], [{'sku':'SKU-A','quantity':2},{'sku':'EXTRA','quantity':1}]])
def test_deterministic_failure_cannot_seal(h,items):
    h.response['images'][0]['items']=items
    out=app.handle(h.request)
    assert out['verdict']=='FAIL' and out['evidence']['decision']['outcome']=='stop_and_fix'


@pytest.mark.parametrize('change',['verdict','partial','unusable','wrong_ref','bool_count','duplicate_sku','missing_view'])
def test_model_cannot_grant_permission(h,change):
    view=h.response['images'][0]
    if change=='verdict':h.response['verdict']='SEAL'
    elif change=='partial':view['complete']=False
    elif change=='unusable':view['usable']=False
    elif change=='wrong_ref':view['ref']='unseen.png'
    elif change=='bool_count':view['items'][0]['quantity']=True
    elif change=='duplicate_sku':view['items']*=2
    elif change=='missing_view':h.response['images']=[]
    out=app.handle(h.request)
    assert out['status']=='pending' and out['verdict']=='UNCERTAIN'


def test_contradictory_views(h):
    h.add('back.png',(h.root/'front.png').read_bytes(),'image');h.save()
    view=copy.deepcopy(h.response['images'][0]);view['ref']='back.png';view['items'][0]['quantity']=100
    h.response['images'].append(view)
    out=app.handle(h.request)
    assert out['error']['code']=='contradictory_observations' and out['verdict']=='UNCERTAIN'


@pytest.mark.parametrize('code',['provider_timeout','provider_unavailable','provider_cleanup_failure','invalid_provider_response'])
def test_failure_preserves_accounting(h,code):
    h.failure=code
    out=app.handle(h.request)
    assert out['status']=='pending' and out['model']['calls']==1 and out['model']['version']=='fixture-version'
    assert out['evidence']['payload']['provider_attempts'][0]['outcome']==code
    assert app.handle(h.request)==out and h.calls==1


def test_changed_content_conflicts_and_new_assessment_is_immutable(h):
    original=app.handle(h.request)
    h.request['context']['operator_note']='changed'
    with pytest.raises(Rejected,match='request_content_conflict'):app.handle(h.request)
    h.request['request_id']='req-b'
    newer=app.handle(h.request)
    assert newer['evidence']['record_id']!=original['evidence']['record_id'] and verify(original['evidence'])


def test_concurrent_replay(h):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:app.handle(h.request),range(4)))
    assert all(out==results[0] for out in results) and h.calls==1


def test_restart_replay_uses_persisted_output(h):
    expected=app.handle(h.request)
    code='import json,sys;from agents.pack.app import handle;print(json.dumps(handle(json.loads(sys.argv[1]))))'
    child=subprocess.run([sys.executable,'-B','-c',code,json.dumps(h.request)],capture_output=True,text=True,check=True)
    assert json.loads(child.stdout)==expected and h.calls==1


def test_http_and_direct_parity(h):
    with TestClient(app.app) as client:
        assert client.get('/health').json()['status']=='ok'
        out=client.post('/run',json=h.request)
        assert out.status_code==200 and out.json()==app.handle(h.request)
        bad={**h.request,'stage':'recovery'}
        assert client.post('/run',json=bad).status_code==422
        h.request['subject']['org_id']='foreign'
        assert client.post('/run',json=h.request).status_code==404


def test_health_does_not_mask_config_error(monkeypatch):
    monkeypatch.delenv('PACK_CONFIG',raising=False)
    with TestClient(app.app) as client:
        assert client.get('/health').json()['status']=='degraded'


def test_total_deadline_discards_late_success_and_keeps_accounting(h,monkeypatch):
    h.config['provider']={'model':'fixture','api_key_env':'UNUSED_TEST_KEY','deadline_s':.05};h.save()
    original=h.invoke
    def slow(*args):
        time.sleep(.08)
        return original(*args)
    monkeypatch.setattr(adapter,'invoke',slow)
    out=app.handle(h.request)
    assert out['status']=='pending' and out['error']['code']=='processing_deadline_exceeded'
    assert out['model']['calls']==1 and out['model']['version']=='fixture-version'
    assert app.handle(h.request)==out and h.calls==1


def test_unexpected_transport_exception_keeps_recorded_accounting(h,monkeypatch):
    def fail(*args):
        h.invoke(*args)
        raise RuntimeError('SECRET must not escape')
    monkeypatch.setattr(adapter,'invoke',fail)
    out=app.handle(h.request)
    assert out['status']=='pending' and out['model']['calls']==1
    assert 'SECRET' not in json.dumps(out)


def test_capture_arrival_after_pending_conflicts(h):
    raw=(h.root/'front.png').read_bytes();(h.root/'front.png').unlink()
    pending=app.handle(h.request)
    assert pending['status']=='pending'
    (h.root/'front.png').write_bytes(raw)
    with pytest.raises(Rejected,match='request_content_conflict'):app.handle(h.request)
    assert h.calls==0


def test_invalid_nonfinite_model_payload_still_produces_truthful_pending(h):
    h.response['unexpected']=float('inf')
    out=app.handle(h.request)
    assert out['status']=='pending' and out['error']['code']=='invalid_provider_response'
    assert out['model']['calls']==1 and out['model']['version']=='fixture-version'
    assert out['evidence']['payload']['observations'] is None
    assert app.handle(h.request)==out
