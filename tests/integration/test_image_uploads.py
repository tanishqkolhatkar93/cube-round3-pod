import hashlib
import io

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from orchestration import api, uploads
from orchestration.store import FileStore


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = FileStore(tmp_path / 'out')
    monkeypatch.setattr(api, 'STORE', store)
    api.app.dependency_overrides[api.require_principal] = lambda: api.Principal('org_demo_alpha', 'test')
    stream = io.BytesIO()
    Image.new('RGB', (8, 8)).save(stream, format='PNG')
    raw = stream.getvalue()
    item = {'ref': 'registered/photo.png', 'kind': 'image', 'sha256': hashlib.sha256(raw).hexdigest()}
    monkeypatch.setattr(uploads, 'registered_inputs', lambda org, unit, stage: [item] if (org, unit, stage) == ('org_demo_alpha', 'U1', 'receiving') else [])
    with TestClient(api.app) as client:
        yield client, raw, store
    api.app.dependency_overrides.clear()


def test_upload_is_private_bound_and_replayable(setup, monkeypatch):
    client, raw, store = setup
    response = client.put('/uploads?unit_id=U1', content=raw, headers={'content-type': 'image/png'})
    assert response.status_code == 200
    receipt = response.json()['receipt_id']
    assert response.json()['status'] == 'evidence_accepted'
    assert client.get('/uploads/' + receipt + '.bin').status_code == 404
    calls = []
    def run(case, flow, scoped):
        calls.append(case)
        from orchestration.orchestrator import new_workflow
        wf = new_workflow(case, flow)
        scoped.save_workflow(wf)
        return wf
    monkeypatch.setattr(api, 'run_workflow', run)
    body = {'unit_id': 'U1', 'route': 'fba', 'returned': False, 'receipts': [receipt]}
    for _ in range(2):
        result = client.post('/image-workflows', json=body)
        assert result.status_code == 200, result.text
    assert len(calls) == 1
    assert calls[0]['upload_inputs']['receiving'][0]['sha256'] == hashlib.sha256(raw).hexdigest()
    body['unit_id'] = 'U2'
    assert client.post('/image-workflows', json=body).status_code == 422
    api.app.dependency_overrides[api.require_principal] = lambda: api.Principal('org_demo_bravo', 'test')
    body['unit_id'] = 'U1'
    assert client.post('/image-workflows', json=body).status_code == 422


def test_invalid_bytes_and_unregistered_images(setup, monkeypatch):
    client, raw, _ = setup
    url = '/uploads?unit_id=U1'
    assert client.put(url, content=b'fake', headers={'content-type': 'image/png'}).status_code == 422
    assert client.put(url, content=raw, headers={'content-type': 'image/jpeg'}).status_code == 422
    monkeypatch.setattr(uploads, 'registered_inputs', lambda *args: [])
    assert client.put(url, content=raw, headers={'content-type': 'image/png'}).status_code == 422
    assert client.put('/uploads?unit_id=../escape', content=raw, headers={'content-type': 'image/png'}).status_code == 422


def test_tampering_and_stage_conflict(setup, monkeypatch):
    client, raw, store = setup
    item = {'ref': 'registered/pack.png', 'kind': 'image', 'sha256': hashlib.sha256(raw).hexdigest()}
    monkeypatch.setattr(uploads, 'registered_inputs', lambda org, unit, stage: [item] if stage == 'pack' else [])
    result = client.put('/uploads?unit_id=U1', content=raw, headers={'content-type': 'image/png'})
    receipt = result.json()['receipt_id']
    body = {'unit_id': 'U1', 'route': 'fba', 'returned': False, 'receipts': [receipt]}
    assert client.post('/image-workflows', json=body).status_code == 422
    (store.root / 'uploads' / (receipt + '.bin')).write_bytes(b'tamper')
    assert client.post('/image-workflows', json=body).status_code == 503


def test_authentication_required(setup):
    client, raw, _ = setup
    api.app.dependency_overrides.clear()
    assert client.put('/uploads?unit_id=U1', content=raw).status_code == 401
    assert client.post('/image-workflows', json={}).status_code == 401

def test_ambiguous_capture_requires_reference_not_stage(setup, monkeypatch):
    client, raw, store = setup
    sha = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(uploads, 'registered_inputs', lambda org, unit, stage:
        [{'ref': stage + '/trusted.png', 'kind': 'image', 'sha256': sha}]
        if stage in ('receiving', 'returns') else [])
    for extra in ('', '&stage=returns'):
        response = client.put('/uploads?unit_id=U1' + extra, content=raw, headers={'content-type': 'image/png'})
        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'ambiguous_capture'
        assert response.json()['detail']['required_information'] == 'capture_ref'
    assert not (store.root / 'uploads').exists()
    assert not list((store.root / 'workflows').iterdir())
    response = client.put('/uploads?unit_id=U1&capture_ref=returns/trusted.png', content=raw, headers={'content-type': 'image/png'})
    assert response.status_code == 200
    assert response.json()['stage'] == 'returns'
    assert client.put('/uploads?unit_id=U1&capture_ref=unknown', content=raw,
                      headers={'content-type': 'image/png'}).status_code == 422


def test_new_ambiguity_invalidates_automatic_receipt(setup, monkeypatch):
    client, raw, _ = setup
    receipt = client.put('/uploads?unit_id=U1', content=raw, headers={'content-type': 'image/png'}).json()['receipt_id']
    monkeypatch.setattr(uploads, 'registered_inputs', lambda org, unit, stage:
        [{'ref': stage + '/trusted.png', 'kind': 'image', 'sha256': hashlib.sha256(raw).hexdigest()}])
    response = client.post('/image-workflows', json={'unit_id': 'U1', 'route': 'fba', 'returned': False, 'receipts': [receipt]})
    assert response.status_code == 409
    assert response.json()['detail']['status'] == 'unresolved'


def test_missing_configuration_and_no_match_remain_unresolved(setup, monkeypatch):
    client, raw, store = setup
    def unavailable(*args):
        raise HTTPException(422, 'configuration missing')
    monkeypatch.setattr(uploads, 'registered_inputs', unavailable)
    response = client.put('/uploads?unit_id=U1', content=raw, headers={'content-type': 'image/png'})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'capture_unresolved'
    assert 'registration operator' in response.json()['detail']['message']
    assert not (store.root / 'uploads').exists()


def test_same_reference_in_two_stages_is_still_ambiguous(setup, monkeypatch):
    client, raw, _ = setup
    monkeypatch.setattr(uploads, 'registered_inputs', lambda org, unit, stage:
        [{'ref': 'shared.png', 'kind': 'image', 'sha256': hashlib.sha256(raw).hexdigest()}])
    response = client.put('/uploads?unit_id=U1&capture_ref=shared.png', content=raw, headers={'content-type': 'image/png'})
    assert response.status_code == 409
    assert response.json()['detail']['status'] == 'unresolved'
