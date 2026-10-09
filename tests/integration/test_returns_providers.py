"""Offline cloud wiring tests: generated pixels and explicitly mocked observations."""
from dataclasses import asdict
import hashlib
import io
import json
import socket
import traceback
from unittest.mock import Mock, MagicMock
from urllib.error import HTTPError

import pytest
from PIL import Image

from agents.returns import providers
from agents.returns.adapter import Adapter
from agents.returns.core.returns_manager import gemini, groq
from agents.returns.core.returns_manager.domain import ValidationError
from agents.returns.core.returns_manager.observations import ObservationScope
from agents.returns.core.returns_manager.rules import assess
from agents.returns.core.returns_manager.vision import ProviderUnavailable
from agents.returns.input_resolver import run_from
from agents.returns.request_store import Rejected
from tests.integration.test_returns_adapter import existing, request_for

TEST_KEY = "OFFLINE_SENTINEL_NOT_A_CREDENTIAL"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network forbidden in provider wiring tests")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    for module in (gemini, groq):
        monkeypatch.setattr(module, "build_opener", blocked)
    for key in ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_TIMEOUT_SECONDS",
                "GEMINI_FREE_TIER_CONFIRMED", "GROQ_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", TEST_KEY)
    monkeypatch.setenv("GEMINI_FREE_TIER_CONFIRMED", "1")
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("GROQ_API_KEY", TEST_KEY)


def cloud(existing, name, monkeypatch, *, mutate=None, failure=None, raw=None):
    config, capture, root = existing
    # Independent test pixels, unrelated to the user's persisted demo package.
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(stream, format="JPEG")
    content = stream.getvalue()
    (root / "test.jpg").write_bytes(content)
    config["bindings"][0]["images"][0].update(path="test.jpg", sha256=hashlib.sha256(content).hexdigest())
    config["provider"] = {"name": name, "settings": {"timeout_seconds": 10}}
    batch = {"scope": asdict(ObservationScope.from_capture(capture)), "identity": [],
             "components": [], "condition": [], "limitations": ["OFFLINE synthetic response only"]}
    if mutate:
        mutate(batch)
    def transport(*args):
        if failure:
            raise failure
        if raw is not None:
            return raw if name == "gemini" else (200, raw)
        if name == "gemini":
            return json.dumps({"candidates": [{"finishReason": "STOP", "content": {
                "parts": [{"text": json.dumps(batch)}]}}], "modelVersion": "offline-model"}).encode()
        return 200, json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps(batch)}}], "model": "offline-model"}).encode()
    mock = Mock(side_effect=transport)
    cls = gemini.GeminiVisionProvider if name == "gemini" else groq.GroqVisionProvider
    monkeypatch.setattr(providers, cls.__name__, lambda config: cls(config, transport=mock))
    adapter = Adapter(config, root, root / "state")
    return adapter, mock


@pytest.mark.parametrize("name", ["ollama", "gemini", "groq"])
def test_explicit_selection_without_network(name):
    provider, public = providers.select_provider({"name": name, "settings": {"timeout_seconds": 10}})
    assert provider.name == name and provider.mode == "real"
    assert TEST_KEY not in json.dumps(public) + repr(provider)


@pytest.mark.parametrize("selection,code", [
    ({"name": "unknown"}, "unknown_returns_provider"),
    ({"name": []}, "unknown_returns_provider"),
    (None, "explicit_real_provider_required"),
    ({"name": "gemini", "settings": {"api_key": TEST_KEY}}, "invalid_provider_configuration"),
    ({"name": "groq", "Authorization": TEST_KEY}, "invalid_provider_configuration"),
    ({"name": "groq", "settings": {"model": "override"}}, "invalid_provider_configuration"),
    ({"name": "gemini", "settings": {"model": "invalid"}}, "gemini_invalid_configuration"),
    ({"name": "groq", "settings": {"timeout_seconds": False}}, "groq_invalid_configuration"),
    ({"name": "gemini", "settings": {"timeout_seconds": float("nan")}}, "gemini_invalid_configuration"),
    ({"name": "groq"}, "provider_timeout_exceeds_adapter_budget"),
    ({"name": "gemini", "settings": {"timeout_seconds": 21}}, "provider_timeout_exceeds_adapter_budget"),
])
def test_bad_configuration_is_sanitized(selection, code):
    with pytest.raises(Rejected, match=code) as exc:
        providers.select_provider(selection)
    assert TEST_KEY not in "".join(traceback.format_exception(exc.value))


@pytest.mark.parametrize("name", ["gemini", "groq"])
def test_missing_key_rejected_before_state_creation(existing, name, monkeypatch):
    monkeypatch.delenv(name.upper() + "_API_KEY")
    config, _, root = existing
    config["provider"] = {"name": name, "settings": {"timeout_seconds": 10}}
    with pytest.raises(Rejected, match=name + "_key_missing"):
        Adapter(config, root, root / "state")
    assert not (root / "state").exists()


def test_gemini_environment_semantics(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.7-flash")
    provider, public = providers.select_provider({"name": "gemini"})
    assert provider.provider.config.model == public["settings"]["model"] == "gemini-3.7-flash"
    assert public["settings"]["timeout_seconds"] == 10
    monkeypatch.delenv("GEMINI_FREE_TIER_CONFIRMED")
    with pytest.raises(Rejected, match="gemini_free_tier_confirmation_required"):
        providers.select_provider({"name": "gemini"})
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", TEST_KEY)
    with pytest.raises(Rejected, match="gemini_invalid_configuration") as exc:
        providers.select_provider({"name": "gemini"})
    assert TEST_KEY not in str(exc.value)


@pytest.mark.parametrize("name,cls", [("gemini", "GeminiVisionProvider"), ("groq", "GroqVisionProvider")])
def test_initialization_failure_is_sanitized(name, cls, monkeypatch):
    monkeypatch.setattr(providers, cls, Mock(side_effect=RuntimeError("Authorization: Bearer " + TEST_KEY)))
    with pytest.raises(Rejected, match=name + "_initialization_failed") as exc:
        providers.select_provider({"name": name, "settings": {"timeout_seconds": 10}})
    assert exc.value.status == 503
    assert TEST_KEY not in "".join(traceback.format_exception(exc.value))


@pytest.mark.parametrize("name", ["gemini", "groq"])
def test_real_classes_mock_transport_canonical_rules_and_durable_replay(existing, name, monkeypatch):
    adapter, transport = cloud(existing, name, monkeypatch)
    source = existing[2] / "source.sqlite3"
    before = source.read_bytes()
    out = adapter.handle(request_for())
    assert out["status"] == "completed" and out["verdict"] == "UNCERTAIN"
    payload = out["evidence"]["payload"]
    run = run_from(existing[1], payload["vision_run"])
    assert json.loads(json.dumps(asdict(assess(existing[1], run.observations)))) == payload["assessment"]
    assert payload["source"]["source_sha256"] == existing[1].source.source_sha256
    assert payload["timestamp_kind"] == "synthetic_fixture_timestamp"
    assert Adapter(existing[0], existing[2], existing[2] / "state").handle(request_for()) == out
    assert transport.call_count == 1 and source.read_bytes() == before
    url, body, timeout, key = transport.call_args.args
    assert timeout == 10 and key == TEST_KEY
    assert key not in url + json.dumps(body)
    if name == "gemini":
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert "responseJsonSchema" in body["generationConfig"]
    else:
        assert url == groq.ENDPOINT and body["model"] == groq.MODEL
        assert body["response_format"] == {"type": "json_object"}
        assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert TEST_KEY not in json.dumps(out)
    for path in (existing[2] / "state").glob("*.sqlite3"):
        assert TEST_KEY.encode() not in path.read_bytes()


@pytest.mark.parametrize("name,failure,diagnostic,code", [
    *( ("gemini", ProviderUnavailable("gemini_" + category), "gemini_" + category, "provider_unavailable")
       for category in ("authentication_failed", "request_rejected", "model_unavailable", "overloaded", "rate_limited", "network_error")),
    *( ("groq", groq.GroqHTTPFailure(status), diagnostic, "provider_unavailable")
       for status, diagnostic in providers.GROQ_STATUS.items()),
    ("groq", ProviderUnavailable("private " + TEST_KEY), "groq_unavailable", "provider_unavailable"),
    ("gemini", ProviderUnavailable("private " + TEST_KEY), "gemini_unavailable", "provider_unavailable"),
    *( (name, TimeoutError("Authorization: Bearer " + TEST_KEY), name + "_timeout", "provider_timeout") for name in ("gemini", "groq")),
    *( (name, RuntimeError(TEST_KEY), name + "_failure", "provider_failure") for name in ("gemini", "groq")),
])
def test_safe_failure_categories_and_replay(existing, name, failure, diagnostic, code, monkeypatch, caplog, capsys):
    adapter, transport = cloud(existing, name, monkeypatch, failure=failure)
    out = adapter.handle(request_for())
    assert out["status"] == "pending" and out["verdict"] == "UNCERTAIN"
    assert out["error"]["code"] == code
    assert out["evidence"]["payload"]["provider_diagnostic"] == diagnostic
    assert adapter.handle(request_for()) == out and transport.call_count == 1
    captured = capsys.readouterr()
    rendered = json.dumps(out) + caplog.text + captured.out + captured.err
    assert TEST_KEY not in rendered and "Authorization" not in rendered


@pytest.mark.parametrize("name", ["gemini", "groq"])
@pytest.mark.parametrize("raw", [b"not json", b"{}", b"[]"])
def test_malformed_envelopes(existing, name, raw, monkeypatch):
    adapter, _ = cloud(existing, name, monkeypatch, raw=raw)
    out = adapter.handle(request_for())
    assert out["error"]["code"] == "invalid_response"
    assert out["evidence"]["payload"]["provider_diagnostic"] == name + "_invalid_response"


@pytest.mark.parametrize("name", ["gemini", "groq"])
@pytest.mark.parametrize("mutation", ["disposition", "incomplete", "condition", "credential", "header", "scope"])
def test_canonical_rejection_and_secret_response_guard(existing, name, mutation, monkeypatch):
    def mutate(batch):
        if mutation == "disposition":
            batch["disposition"] = "RESTOCK"
        elif mutation == "incomplete":
            del batch["identity"]
        elif mutation == "condition":
            batch["condition"] = [{"feature": "scratches", "state": "observed", "description": None,
                "evidence_refs": ["test-evidence"], "limitations": []}]
        elif mutation == "scope":
            batch["scope"]["unit_id"] = "foreign"
        else:
            batch["limitations"] = [TEST_KEY if mutation == "credential" else "Authorization: Bearer private"]
    adapter, _ = cloud(existing, name, monkeypatch, mutate=mutate)
    out = adapter.handle(request_for())
    assert out["error"]["code"] == ("response_scope_mismatch" if mutation == "scope" else "invalid_response")
    assert out["verdict"] == "UNCERTAIN"
    run = out["evidence"]["payload"]["vision_run"]
    assert run["raw_response"] is None and run["observations"] is None
    assert TEST_KEY not in json.dumps(out) and "Authorization" not in json.dumps(out)


def test_effective_environment_model_changes_conflict_but_key_rotation_does_not(existing, monkeypatch):
    adapter, transport = cloud(existing, "gemini", monkeypatch)
    original = adapter.handle(request_for())
    monkeypatch.setenv("GEMINI_API_KEY", "ROTATED_OFFLINE_SENTINEL")
    assert Adapter(existing[0], existing[2], existing[2] / "state").handle(request_for()) == original
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.7-flash")
    with pytest.raises(Rejected, match="request_content_conflict"):
        Adapter(existing[0], existing[2], existing[2] / "state").handle(request_for())
    assert transport.call_count == 1


@pytest.mark.parametrize("name", ["gemini", "groq"])
def test_contradictory_observations_preserve_uncertainty(existing, name, monkeypatch):
    def mutate(batch):
        batch["identity"] = [dict(field="sku", state="observed", values=[value],
            evidence_refs=["test-evidence"], limitations=[]) for value in ("TEST-A", "TEST-B")]
    adapter, _ = cloud(existing, name, monkeypatch, mutate=mutate)
    out = adapter.handle(request_for())
    payload = out["evidence"]["payload"]
    assert payload["vision_run"]["observations"]["conflicts"] == ["identity:sku"]
    assert payload["assessment"]["identity"]["verdict"] == "UNCERTAIN"
    assert payload["assessment"]["disposition"]["decision"] == "pending_review"


def test_groq_single_jpeg_requirement_preserved(existing, monkeypatch):
    adapter, transport = cloud(existing, "groq", monkeypatch)
    image = existing[0]["bindings"][0]["images"][0]
    image.update(path="test.png", sha256=hashlib.sha256((existing[2] / "test.png").read_bytes()).hexdigest())
    adapter = Adapter(existing[0], existing[2], existing[2] / "state")
    assert adapter.handle(request_for())["error"]["code"] == "invalid_response"
    transport.assert_not_called()


def test_diagnostic_does_not_carry_into_missing_image_request(existing, monkeypatch):
    adapter, transport = cloud(existing, "gemini", monkeypatch, failure=ProviderUnavailable("gemini_overloaded"))
    assert adapter.handle(request_for())["evidence"]["payload"]["provider_diagnostic"] == "gemini_overloaded"
    (existing[2] / "test.jpg").unlink()
    request = request_for()
    request["request_id"] += "-missing"
    out = adapter.handle(request)
    assert out["error"]["code"] == "missing_image"
    assert "provider_diagnostic" not in out["evidence"]["payload"]
    assert transport.call_count == 1


@pytest.mark.parametrize("name", ["gemini", "groq"])
@pytest.mark.parametrize("fails", [False, True])
def test_original_http_transport_headers_and_sanitized_errors(name, fails, monkeypatch, capsys):
    module = gemini if name == "gemini" else groq
    opener = Mock()
    if fails:
        opener.open.side_effect = HTTPError("https://invalid/" + TEST_KEY, 401,
            "Authorization: Bearer " + TEST_KEY, {}, io.BytesIO(TEST_KEY.encode()))
    else:
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b"{}"
        opener.open.return_value = response
    monkeypatch.setattr(module, "build_opener", Mock(return_value=opener))
    url = gemini.GeminiConfig().endpoint if name == "gemini" else groq.ENDPOINT
    if fails:
        with pytest.raises(ProviderUnavailable) as exc:
            module.post_json(url, {}, 10, TEST_KEY)
        assert TEST_KEY not in "".join(traceback.format_exception(exc.value))
    else:
        module.post_json(url, {}, 10, TEST_KEY)
    opener.open.assert_called_once()
    request = opener.open.call_args.args[0]
    header = request.get_header("X-goog-api-key" if name == "gemini" else "Authorization")
    assert header == (TEST_KEY if name == "gemini" else "Bearer " + TEST_KEY)
    assert TEST_KEY not in request.full_url + request.data.decode()
    captured = capsys.readouterr()
    assert TEST_KEY not in captured.out + captured.err
