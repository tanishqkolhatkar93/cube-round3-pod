"""Authenticated console API with existing opt-in fixtures and durable storage.

Only the established test fixtures supply synthetic observations/registrations.
No production configuration, credentials, or provider inference is created.
"""
import os
import shutil
from pathlib import Path
from fastapi.testclient import TestClient
from orchestration import api
from orchestration import orchestrator
from orchestration.orchestrator import discover_inputs as production_discover_inputs
from orchestration.store import FileStore
from shared.utils.hashing import verify
from shared.utils.schema import errors
from tests.e2e.test_registered_pod import cases
from agents.receiving.tests.integration_support import receiving_observed
from agents.prep.tests.integration_support import prep_synthetic
from tests.integration.pack_recovery_support import pack_recovery_synthetic


def test_configured_console_persists_completed_workflow(
        cases, receiving_observed, prep_synthetic, pack_recovery_synthetic,
        tmp_path, monkeypatch):
    case = cases[0]
    lines = [{'line_id': 'positive-fee', 'charge_type': 'inbound_defect_fee',
              'amount_usd': '4.25', 'currency': 'USD', 'unit_scope': 'unit', 'refs': {}}] if case['route'] == 'fba' else []
    pack_recovery_synthetic.set_fee_report(case['unit_id'], lines)
    # Keep the fixture's registered bytes, but exercise production filesystem
    # discovery instead of its Pack/Recovery discovery wrapper.
    input_root = Path(os.environ['INPUT_DIR'])
    for config in pack_recovery_synthetic.configs.values():
        for binding in config['bindings']:
            for item in binding['files']:
                target = input_root / item['ref']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(pack_recovery_synthetic.root / item['path'], target)
    monkeypatch.setattr(orchestrator, 'discover_inputs', production_discover_inputs)
    root = tmp_path / 'console-store'
    monkeypatch.setattr(api, 'STORE', FileStore(root))
    monkeypatch.setattr(api, '_DEMO_PRINCIPAL', None)
    env_name = api.TENANT_TOKEN_ENV[case['org_id']]
    monkeypatch.setenv(env_name, 'explicit-offline-console-test')
    with TestClient(api.app) as client:
        assert client.post('/workflows', json=case).status_code == 401
        assert client.post('/auth/session', json={
            'org_id': case['org_id'], 'token': 'explicit-offline-console-test'}).status_code == 200
        created = client.post('/workflows', json=case)
        assert created.status_code == 200
        wf = created.json()
        assert wf['status'] == 'COMPLETED'
        assert wf['final_outcome']['provisional'] is False
        endpoint = '/workflows/' + wf['workflow_id']
        before = client.get(endpoint + '/evidence').json()
        assert len(before['evidence']) == 3
        assert all(verify(r) and not errors('evidence', r) for r in before['evidence'].values())
        calls = (len(receiving_observed), sum(prep_synthetic.calls.values()), len(pack_recovery_synthetic.calls))
        # Reopen the persisted store: retrieval must not depend on a memory cache.
        monkeypatch.setattr(api, 'STORE', FileStore(root))
        assert client.get(endpoint).json() == wf
        assert client.get(endpoint + '/evidence').json() == before
        replay = client.post('/workflows', json=case)
        assert replay.status_code == 200 and replay.json()['status'] == 'COMPLETED'
        assert client.get(endpoint + '/evidence').json()['evidence'] == before['evidence']
        assert calls == (len(receiving_observed), sum(prep_synthetic.calls.values()), len(pack_recovery_synthetic.calls))
        # The existing Returns CSV fixture has no photographs; API/UI consumers
        # must see uncertainty, never a fabricated successful return inspection.
        returned = next(c for c in cases if c['unit_id'] == 'UNIT-0014')
        assert returned['returned'] is True
        if returned['org_id'] != case['org_id']:
            assert client.post('/workflows', json=returned).status_code == 403
            client.delete('/auth/session')
            monkeypatch.setenv(api.TENANT_TOKEN_ENV[returned['org_id']], 'explicit-offline-returns-test')
            assert client.post('/auth/session', json={
                'org_id': returned['org_id'], 'token': 'explicit-offline-returns-test'}).status_code == 200
        incomplete = client.post('/workflows', json=returned)
        assert incomplete.status_code == 200
        result = incomplete.json()
        assert result['status'] != 'COMPLETED'
        assert result['final_outcome']['provisional'] is True
        evidence = client.get('/workflows/' + result['workflow_id'] + '/evidence').json()['evidence']
        record_id = next(s['record_id'] for s in result['stage_results'] if s['stage'] == 'returns')
        record = evidence[record_id]
        assert record['status'] == 'pending' and record['decision']['verdict'] == 'UNCERTAIN'
        assert 'missing_image' in record['decision']['reason']
        client.delete('/auth/session')
        assert client.get(endpoint).status_code == 401
