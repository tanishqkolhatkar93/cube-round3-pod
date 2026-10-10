"""Explicit synthetic sources and mocked HTTP only; actual manager rules execute."""
import json
import time

import pytest

from agents import groq_provider as groq, bounded_provider
from agents.prep.common import Failure
from shared.utils.hashing import verify
from shared.utils.schema import errors

SELECTION = {'kind': 'groq', 'model': groq.MODEL, 'api_key_env': 'GROQ_API_KEY_2', 'deadline_s': 2}


def envelope(data, **changes):
    return json.dumps({'model': groq.MODEL, 'choices': [{'finish_reason': 'stop',
        'message': {'role': 'assistant', 'content': json.dumps(data)}}],
        'usage': {'total_tokens': 10}, **changes}).encode()


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY_2', 'offline-selected-sentinel')
    calls, result = [], {'data': {}}
    def post(url, body, timeout, key):
        assert url == groq.ENDPOINT and key == 'offline-selected-sentinel'
        calls.append(body)
        if 'failure' in result: raise result['failure']
        return 200, result.get('raw', envelope(result['data']))
    monkeypatch.setattr(groq, 'post_json', post)
    # Exercise the actual worker protocol inline; no spawned process or network.
    def inline(selection, prompt, payload, images, stats, *, worker_target):
        events = []
        class Pipe:
            def send(self, event): events.append(event)
            def close(self): pass
        worker_target(Pipe(), selection, groq.key_for(selection), prompt, payload, images)
        for e in events:
            if e['event'] == 'attempt':
                stats['calls'] += 1
                stats['model'] = e['model']
                stats['attempts'].append({'model': e['model'], 'outcome': 'started'})
            if e['event'] == 'accounting': stats.update(version=e['version'], usage=e['usage'])
        final = events[-1]
        if stats['attempts']: stats['attempts'][-1]['outcome'] = final.get('error', 'success')
        return final.get('data'), final.get('error')
    monkeypatch.setattr(bounded_provider, 'invoke', inline)
    return calls, result


def test_prep_groq_real_adapter_rules_and_replay(tmp_path, transport):
    from agents.prep.tests.test_prep import Harness, facts
    from agents.prep.adapter import Adapter
    h = Harness(tmp_path); h.config['provider'] = dict(SELECTION)
    calls, result = transport; result['data'] = facts(h.criteria)
    adapter = Adapter(h.config, h.root, h.state)
    out = adapter.handle(h.request)
    assert out['status'] == 'completed' and out['verdict'] == 'PASS'
    assert out['model']['provider'] == 'groq' and out['model']['version'] == groq.MODEL
    assert verify(out['evidence']) and not errors('agent-output', out)
    assert adapter.handle(h.request) == out and len(calls) == 1


def test_pack_groq_real_adapter_rules_and_replay(tmp_path, monkeypatch, transport):
    from agents.pack.tests.test_adapter import Harness
    from agents.pack import app, safety
    h = Harness(tmp_path, monkeypatch)
    monkeypatch.setattr(app, 'invoke', safety.invoke)
    h.config['provider'] = dict(SELECTION); h.save()
    calls, result = transport; result['data'] = h.response
    out = app.handle(h.request)
    assert out['status'] == 'completed' and out['verdict'] == 'PASS'
    assert out['model']['provider'] == 'groq' and out['model']['calls'] == 1
    assert verify(out['evidence']) and not errors('agent-output', out)
    assert app.handle(h.request) == out and len(calls) == 1


def test_recovery_groq_real_rules_and_citations(tmp_path, monkeypatch, transport):
    from agents.pack.tests.test_adapter import Harness
    from agents.recovery.tests.test_adapter import record
    from agents.recovery import app
    h = Harness(tmp_path, monkeypatch, 'recovery')
    h.binding.pop('order_lines'); h.binding['refs'] = {}
    h.binding['fee_policies'] = {'test_fee': {'version': 'offline-1', 'text': 'Explicit synthetic policy'}}
    h.config['provider'] = dict(SELECTION)
    report = {'org_id': 'org-a', 'subject_id': 'unit-a', 'workflow_id': 'wf-a', 'complete': True,
              'line_count': 1, 'lines': [{'line_id': 'fee', 'charge_type': 'test_fee',
                  'amount_usd': '2.00', 'currency': 'USD', 'unit_scope': 'unit', 'refs': {}}]}
    h.add('report.json', json.dumps(report).encode(), 'document'); h.save()
    h.request['previous_evidence'] = [record(h)]
    calls, result = transport
    result['data'] = {'results': [{'line_id': 'fee', 'position': 'CONTRADICTS', 'confidence': .9,
                                  'reason': 'Synthetic policy observation', 'evidence_record_ids': ['PRP-a']}]}
    out = app.handle(h.request)
    assert out['status'] == 'completed' and out['evidence']['payload']['claimable_usd'] == 2
    assert out['model']['provider'] == 'groq' and verify(out['evidence'])
    assert not errors('agent-output', out)
    assert app.handle(h.request) == out and len(calls) == 1
    assert all(p['type'] == 'text' for p in calls[0]['messages'][1]['content'])


def test_receiving_groq_uses_canonical_observation(monkeypatch, transport):
    from agents.receiving.core.config import CFG
    from agents.receiving.core.extraction.groq import GroqProvider
    from agents.receiving.core.extraction.base import VisionRequest
    from agents.receiving.core.models import ImageObservation
    monkeypatch.setattr(CFG, 'provider', 'groq')
    monkeypatch.setattr(CFG, 'groq_model', groq.MODEL)
    monkeypatch.setattr(CFG, 'groq_api_key_env', 'GROQ_API_KEY_2')
    calls, result = transport; result['data'] = {'visible_sku_text': 'SYNTHETIC-SKU'}
    stats = {'calls': 0, 'attempts': []}
    out = GroqProvider().analyze(VisionRequest(b'fixture', 'Observe JSON facts', 'test', ImageObservation),
                                 stats=stats, deadline=time.monotonic() + 2)
    assert out.parsed.visible_sku_text == 'SYNTHETIC-SKU'
    assert out.model_id == groq.MODEL and stats['provider'] == 'groq' and len(calls) == 1
    result['data'] = {'invented_field': 'not an observation'}
    from agents.receiving.core.failures import Failure as ReceivingFailure
    with pytest.raises(ReceivingFailure, match='model_invalid_response'):
        GroqProvider().analyze(VisionRequest(b'fixture', 'facts', 'test', ImageObservation),
                               stats=stats, deadline=time.monotonic() + 2)


@pytest.mark.parametrize('status', [400, 401, 403, 404, 429, 503, 500])
def test_groq_failure_never_rotates_or_retries(transport, status):
    from agents.readiness import provider_http_error
    calls, result = transport; result['failure'] = groq.GroqHTTPFailure(status)
    stats = {'calls': 0, 'attempts': []}
    data, code = groq.invoke(SELECTION, 'facts', {}, [], stats)
    assert data is None and code == provider_http_error(status)
    assert len(calls) == stats['calls'] == 1 and 'sentinel' not in str(stats)


@pytest.mark.parametrize('change', ['foreign_model', 'truncated', 'tool', 'nonfinite', 'secret', 'extra_choice'])
def test_groq_invalid_response_never_produces_assessment(transport, change):
    calls, result = transport
    value = json.loads(envelope({'facts': []}))
    if change == 'foreign_model': value['model'] = 'other-model'
    if change == 'truncated': value['choices'][0]['finish_reason'] = 'length'
    if change == 'tool': value['choices'][0]['message']['tool_calls'] = [{}]
    if change == 'nonfinite': value['choices'][0]['message']['content'] = '{"x":1e999}'
    if change == 'secret': value['choices'][0]['message']['content'] = '{"text":"offline-selected-sentinel"}'
    if change == 'extra_choice': value['choices'] *= 2
    result['raw'] = json.dumps(value).encode()
    stats = {'calls': 0, 'attempts': []}
    data, code = groq.invoke(SELECTION, 'facts', {}, [], stats)
    assert data is None and code == 'invalid_provider_response' and len(calls) == 1
    assert 'sentinel' not in str(stats)


def test_missing_selected_groq_key_does_not_use_primary(monkeypatch, transport):
    monkeypatch.delenv('GROQ_API_KEY_2')
    monkeypatch.setenv('GROQ_API_KEY', 'unused-primary')
    stats = {'calls': 0, 'attempts': []}
    data, code = groq.invoke(SELECTION, 'facts', {}, [], stats)
    assert data is None and code == 'provider_unconfigured'
    assert stats['calls'] == 0 and not transport[0]


def test_over_limit_images_are_not_silently_dropped(transport):
    stats = {'calls': 0, 'attempts': []}
    data, code = groq.invoke(SELECTION, 'facts', {}, [{}] * 4, stats)
    assert data is None and code == 'provider_image_limit_exceeded'
    assert stats['calls'] == 0 and not transport[0]


@pytest.mark.parametrize('field,value', [('model', 'unapproved-model'), ('api_key_env', 'GROQ_API_KEY_5')])
def test_unknown_selection_fails_closed(transport, field, value):
    stats = {'calls': 0, 'attempts': []}
    data, code = groq.invoke({**SELECTION, field: value}, 'facts', {}, [], stats)
    assert data is None and code == 'provider_configuration_invalid' and not transport[0]


def test_receiving_cache_does_not_reuse_other_provider(tmp_path, monkeypatch):
    import io
    from PIL import Image
    from types import SimpleNamespace
    from agents.receiving.core import engine
    from agents.receiving.core.config import CFG
    from agents.receiving.core.extraction import service, gemini, groq as receiving_groq
    from agents.receiving.core.models import ImageObservation
    monkeypatch.setattr(CFG, 'cache_dir', tmp_path / 'cache')
    monkeypatch.setattr(service, 'assess_quality', lambda raw: {'verdict': 'ACCEPTABLE'})
    monkeypatch.setattr(service, 'decode_barcodes', lambda raw: [])
    calls = []
    class Provider:
        def analyze(self, req, *, stats, deadline):
            calls.append(CFG.provider)
            stats['calls'] += 1
            return SimpleNamespace(parsed=ImageObservation(), model_id=CFG.provider + '-test', tokens=1, latency_ms=1)
    monkeypatch.setattr(gemini, 'GeminiProvider', Provider)
    monkeypatch.setattr(receiving_groq, 'GroqProvider', Provider)
    buf = io.BytesIO(); Image.new('RGB', (20, 20)).save(buf, 'JPEG')
    for provider in ('gemini', 'groq', 'groq', 'gemini'):
        monkeypatch.setattr(CFG, 'provider', provider)
        observations, stats, errors = engine.run_engine([('synthetic.jpg', buf.getvalue())])
        assert not errors and stats['model_ids'] == [provider + '-test']
    assert calls == ['gemini', 'groq']


@pytest.mark.parametrize('bad_source', [False, True])
def test_groq_does_not_bypass_prep_source_or_citation_validation(tmp_path, transport, bad_source):
    from agents.prep.tests.test_prep import Harness, facts
    from agents.prep.adapter import Adapter
    from agents.prep.common import Rejected
    h = Harness(tmp_path); h.config['provider'] = dict(SELECTION)
    calls, result = transport
    result['data'] = facts(h.criteria)
    adapter = Adapter(h.config, h.root, h.state)
    if bad_source:
        (h.root / h.binding['images'][0]['path']).write_bytes(b'tampered')
        with pytest.raises(Rejected, match='input_hash_mismatch'):
            adapter.handle(h.request)
        assert not calls
    else:
        result['data']['observations'][0]['photo_index'] = 999
        out = adapter.handle(h.request)
        assert out['status'] == 'pending' and out['verdict'] == 'UNCERTAIN'
        assert out['evidence']['payload']['observations'] is None


def test_groq_pack_order_rules_reject_false_seal(tmp_path, monkeypatch, transport):
    from agents.pack.tests.test_adapter import Harness
    from agents.pack import app, safety
    h = Harness(tmp_path, monkeypatch)
    monkeypatch.setattr(app, 'invoke', safety.invoke)
    h.config['provider'] = dict(SELECTION); h.save()
    calls, result = transport; result['data'] = h.response
    result['data']['images'][0]['items'][0]['quantity'] = 1
    result['data']['assessment'] = {'verdict': 'SEAL', 'checks_performed': {
        'all_items_present': True, 'quantities_correct': True, 'no_extra_items': True}}
    out = app.handle(h.request)
    assert out['verdict'] == 'FAIL' and out['evidence']['decision']['outcome'] == 'stop_and_fix'
    assert len(calls) == 1 and verify(out['evidence'])
