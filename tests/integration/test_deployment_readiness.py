"""Offline regressions for the deployed UNIT-0014 failure categories."""
import importlib
import json
from pathlib import Path

import httpx
import pytest

from agents.readiness import provider_http_error
from orchestration.orchestrator import load_flow, run_workflow
from orchestration.store import MemoryStore
from tests.helpers import Fake, Boom


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket
    def forbidden(*args, **kwargs):
        raise AssertionError('live network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


@pytest.mark.parametrize('stage', ['prep', 'pack', 'returns', 'recovery'])
def test_missing_registration_reports_fixed_diagnostic(stage, monkeypatch):
    module = importlib.import_module(f'agents.{stage}.app')
    monkeypatch.delenv(stage.upper() + '_CONFIG', raising=False)
    endpoint = next(r.endpoint for r in module.app.routes if r.path == '/health')
    result = endpoint()
    assert result['status'] == 'degraded'
    assert result['error'] == (stage + '_configuration_required' if stage in ('prep', 'returns') else 'configuration_required')
    assert result['remote_provider_validation'] == 'not_run'


def test_returns_health_does_not_create_state(tmp_path, monkeypatch):
    from agents.returns import app
    config = tmp_path / 'source.json'
    config.write_text(json.dumps({'mode': 'synthetic', 'csv': 'approved.csv',
                                 'tenants': [{'organization_id': 'org_demo_alpha', 'client_id': None}]}))
    state = tmp_path / 'state'
    monkeypatch.setenv('RETURNS_CONFIG', str(config))
    monkeypatch.setenv('RETURNS_STATE_DIR', str(state))
    result = app.health()
    assert result['status'] == 'ok' and result['provider_status'] == 'not_required'
    assert result['source_validation'] == 'per_request'
    assert not state.exists()


def test_returns_effective_gemini_selection_precedes_validation(monkeypatch):
    from agents.returns.providers import select_provider
    monkeypatch.setenv('GEMINI_MODEL', 'receiving-only-model')
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS', 'invalid-global-timeout')
    monkeypatch.setenv('GEMINI_API_KEY_ENV', 'GEMINI_API_KEY_2')
    monkeypatch.setenv('GEMINI_API_KEY', 'unused invalid credential')
    monkeypatch.setenv('GEMINI_API_KEY_2', 'offline-selected-key')
    provider, public = select_provider({'name': 'gemini', 'settings': {
        'model': 'gemini-3.8-flash', 'timeout_seconds': 10, 'free_tier_confirmed': True}})
    assert provider.provider.config.api_key == 'offline-selected-key'
    assert public['settings']['model'] == 'gemini-3.8-flash'
    assert 'key' not in json.dumps(public)


def test_invalid_effective_model_is_not_replaced(monkeypatch):
    from agents.returns.providers import select_provider
    from agents.returns.request_store import Rejected
    monkeypatch.setenv('GEMINI_API_KEY', 'offline-key')
    monkeypatch.delenv('GEMINI_API_KEY_ENV', raising=False)
    with pytest.raises(Rejected, match='gemini_invalid_configuration'):
        select_provider({'name': 'gemini', 'settings': {'model': 'invalid', 'timeout_seconds': 10}})


@pytest.mark.parametrize('route,active,skipped', [('fba', 'prep', 'pack'), ('mfn', 'pack', 'prep')])
def test_route_dispatch_never_calls_incompatible_manager(route, active, skipped):
    clients = {s: Fake() for s in ('receiving', 'prep', 'pack', 'returns', 'recovery')}
    clients[skipped] = Boom(AssertionError('wrong route reached manager'))
    wf = run_workflow({'org_id': 'org_demo_alpha', 'unit_id': 'OFFLINE-ROUTE',
                       'route': route, 'returned': True}, load_flow(), MemoryStore(), clients)
    assert clients[skipped].calls == 0 and clients[active].calls == 1
    assert next(s for s in wf['stage_results'] if s['stage'] == skipped)['state'] == 'skipped'
    assert wf['context']['route'] == route


def test_pack_direct_fba_request_remains_rejected():
    from agents.secure_runtime import request_boundary
    from agents.prep.common import Rejected
    request = {'schema_version': '1.0', 'request_id': 'test', 'workflow_id': 'WF-test',
               'stage': 'pack', 'subject': {'org_id': 'org_demo_alpha', 'subject_id': 'UNIT-0014', 'route': 'fba'},
               'inputs': [], 'previous_evidence': [], 'context': {}}
    with pytest.raises(Rejected, match='invalid_request'):
        request_boundary(request, 'pack')


def test_unexpected_manager_error_does_not_leak_into_evidence():
    clients = {s: Fake() for s in ('receiving', 'prep', 'pack', 'returns', 'recovery')}
    clients['prep'] = Boom(RuntimeError('PRIVATE credential or source path'))
    wf = run_workflow({'org_id': 'org_demo_alpha', 'unit_id': 'OFFLINE-ERROR',
                       'route': 'fba', 'returned': False}, load_flow(), MemoryStore(), clients)
    assert 'PRIVATE' not in json.dumps(wf)
    sr = next(s for s in wf['stage_results'] if s['stage'] == 'prep')
    assert sr['error']['message'] == 'agent_execution_failed'
    assert wf['status'] != 'COMPLETED'


@pytest.mark.parametrize('status', [400, 401, 403, 404, 429, 503, 500])
def test_prep_http_diagnostics_are_sanitized_without_retry(monkeypatch, status):
    from agents.prep.providers import _gemini_worker
    class Pipe:
        events = []
        def send(self, value): self.events.append(value)
        def close(self): pass
    calls = []
    def post(*args, **kwargs):
        calls.append(1)
        return httpx.Response(status, text='PRIVATE provider response')
    monkeypatch.setattr(httpx, 'post', post)
    pipe = Pipe()
    _gemini_worker(pipe, 'selected-model', 'offline-key', 1, [], [])
    assert pipe.events == [{'error': provider_http_error(status)}]
    assert calls == [1]


def test_receiving_missing_key_remains_pending_without_assessment(monkeypatch):
    from agents.receiving import app
    from agents.receiving.core import engine
    from agents.receiving.core.extraction.service import ExtractionService
    from agents.receiving.core.failures import Failure
    from shared.utils.hashing import verify
    calls = []
    def unavailable(self, *args, **kwargs):
        calls.append(1)
        raise Failure('provider_configuration_required')
    monkeypatch.setattr(ExtractionService, 'observe', unavailable)
    monkeypatch.setattr(app, 'run_engine', engine.run_engine)
    request = {'schema_version': '1.0', 'request_id': 'offline', 'workflow_id': 'WF-org_demo_alpha-UNIT-0014',
               'stage': 'receiving', 'subject': {'org_id': 'org_demo_alpha', 'subject_id': 'UNIT-0014'},
               'inputs': [], 'previous_evidence': [], 'context': {}}
    result = app._execute(request, {}, 'fixture', {'captured_at': '2026-10-01T00:00:00Z'},
                          [({'ref': 'one.jpg'}, b'one'), ({'ref': 'two.jpg'}, b'two')], [])
    assert calls == [1]
    assert result['status'] == 'pending' and result['verdict'] == 'UNCERTAIN'
    assert result['evidence']['checks'] == [] and verify(result['evidence'])
    assert result['evidence']['model']['calls'] == 0
    assert 'provider_configuration_required' in result['error']['message']


def test_revision_is_only_a_commit_identifier(monkeypatch):
    from orchestration import api
    monkeypatch.setenv('RENDER_GIT_COMMIT', 'PRIVATE-invalid')
    assert api.health()['revision'] is None
    monkeypatch.setenv('RENDER_GIT_COMMIT', 'a' * 40)
    assert api.health()['revision'] == 'a' * 40
