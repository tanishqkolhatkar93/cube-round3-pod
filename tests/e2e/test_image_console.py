"""Real upload -> registration resolution -> orchestration -> durable evidence.

Only vision observations are supplied by existing explicit offline fixtures.
No upload resolver, routing decision, workflow output or evidence record is mocked.
"""
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from agents.prep.adapter import Adapter as PrepAdapter
from agents.prep import app as prep_app
from agents.receiving import app as receiving
from agents.receiving.tests.integration_support import receiving_observed
from agents.prep.tests.integration_support import prep_synthetic
from tests.integration.pack_recovery_support import pack_recovery_synthetic
from tests.e2e.test_registered_pod import cases
from orchestration import api
from orchestration.store import FileStore
from shared.utils.hashing import verify
from shared.utils.schema import errors


def test_images_resolve_and_run_registered_flow(cases, receiving_observed, prep_synthetic,
                                               pack_recovery_synthetic, tmp_path, monkeypatch):
    case = cases[0]
    unit, org = case['unit_id'], case['org_id']
    # This deployment has the selected tenant's genuine Prep adapter; only its
    # provider transport uses the existing synthetic observation fixture.
    config_path = prep_synthetic.registrations[org]
    config = json.loads(config_path.read_text(encoding='utf-8'))
    monkeypatch.setattr(prep_app, 'configured_adapter', lambda: PrepAdapter(
        config, config_path.parent, tmp_path / 'prep-upload-state', provider_factory=lambda _: prep_synthetic))
    pack_recovery_synthetic.set_fee_report(unit, [])
    store_root = tmp_path / 'upload-console'
    monkeypatch.setattr(api, 'STORE', FileStore(store_root))
    monkeypatch.setattr(api, '_DEMO_PRINCIPAL', None)
    monkeypatch.setenv(api.TENANT_TOKEN_ENV[org], 'upload-e2e-token')
    route_stage = 'prep' if case['route'] == 'fba' else 'pack'
    registry = json.loads(Path(os.environ['RECEIVING_CAPTURE_REGISTRY']).read_text(encoding='utf-8'))
    receiving_capture = next(i for i in registry['captures'] if i['subject_id'] == unit)
    receiving_path = receiving.DATA_INPUT / receiving_capture['ref']
    if route_stage == 'prep':
        binding = next(b for b in config['bindings'] if b['subject_id'] == unit)
        image = binding['images'][0]
        route_path = config_path.parent / image['path']
    else:
        binding = next(b for b in pack_recovery_synthetic.configs['pack']['bindings'] if b['subject_id'] == unit)
        image = binding['files'][0]
        route_path = pack_recovery_synthetic.root / image['path']
    with TestClient(api.app) as client:
        assert client.post('/auth/session', json={'org_id': org, 'token': 'upload-e2e-token'}).status_code == 200
        receipts = []
        for source, mime, expected in [(receiving_path, 'image/jpeg', 'receiving'), (route_path, 'image/png', route_stage)]:
            response = client.put('/uploads', params={'unit_id': unit}, content=source.read_bytes(), headers={'content-type': mime})
            assert response.status_code == 200, response.text
            assert response.json()['stage'] == expected
            receipts.append(response.json()['receipt_id'])
        assert len(receiving_observed) == 0  # Association lookup never invokes vision.
        assert not prep_synthetic.calls and not pack_recovery_synthetic.calls
        body = {'unit_id': unit, 'route': case['route'], 'returned': False, 'receipts': receipts}
        response = client.post('/image-workflows', json=body)
        assert response.status_code == 200, response.text
        wf = response.json()
        assert wf['status'] == 'COMPLETED', wf['errors']
        assert [s['stage'] for s in wf['stage_results'] if s['state'] != 'skipped'] == ['receiving', route_stage, 'recovery']
        assert wf['context']['upload_inputs']['receiving'][0]['ref'] == receiving_capture['ref']
        assert any(i['ref'] == image['ref'] for i in wf['context']['upload_inputs'][route_stage])
        endpoint = '/workflows/' + wf['workflow_id']
        bundle = client.get(endpoint + '/evidence').json()
        assert all(verify(r) and not errors('evidence', r) for r in bundle['evidence'].values())
        assert len(receiving_observed) == 1
        assert (sum(prep_synthetic.calls.values()) if route_stage == 'prep' else len(pack_recovery_synthetic.calls)) == 1
        monkeypatch.setattr(api, 'STORE', FileStore(store_root))
        assert client.post('/image-workflows', json=body).json() == wf
        assert client.get(endpoint + '/evidence').json() == bundle
        assert len(receiving_observed) == 1
        # The same uploaded bytes cannot authorize another authenticated tenant.
        other = 'org_demo_bravo' if org == 'org_demo_alpha' else 'org_demo_alpha'
        monkeypatch.setenv(api.TENANT_TOKEN_ENV[other], 'other-upload-token')
        client.delete('/auth/session')
        client.post('/auth/session', json={'org_id': other, 'token': 'other-upload-token'})
        assert client.put('/uploads', params={'unit_id': unit}, content=receiving_path.read_bytes(),
                          headers={'content-type': 'image/jpeg'}).status_code == 422
        assert client.post('/image-workflows', json=body).status_code == 422
        assert client.get(endpoint).status_code == 404
        client.delete('/auth/session')
        client.post('/auth/session', json={'org_id': org, 'token': 'upload-e2e-token'})
        original = receiving_path.read_bytes()
        receiving_path.write_bytes(b'tampered trusted source')
        result = client.put('/uploads', params={'unit_id': unit}, content=original, headers={'content-type': 'image/jpeg'})
        assert result.status_code == 422
        assert result.json()['detail']['status'] == 'unresolved'
