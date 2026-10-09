"""Reconciliation regressions; staged photos are synthetic, observations offline."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents.receiving import app as receiving
from agents.receiving import safety
from agents.receiving.core.models import ImageObservation
from agents.receiving.tests.test_adapter import _gate_rejected_jpeg, _req
from shared.utils.hashing import verify

ROOT = Path(__file__).resolve().parents[3]


def test_one_authoritative_reference_validator_and_record_id():
    assert receiving._safe_rel is safety.safe_ref
    assert receiving._record_id is safety.record_id


@pytest.mark.parametrize("mode", ["pending", "completed", "error"])
def test_zain_record_identity_on_every_path(register, mode):
    inputs = [] if mode == "pending" else [register(raw=_gate_rejected_jpeg())]
    if mode == "error":
        inputs.append({"ref": "../foreign.jpg", "kind": "image"})
    request = _req("UNIT-9001", "org_demo_alpha", rid="combined-identity", inputs=inputs)
    out = receiving.handle(request)
    expected = "RCV-" + hashlib.sha256(b"combined-identity").hexdigest()[:12]
    assert out["status"] == mode and out["evidence"]["record_id"] == expected
    assert receiving.handle(request) == out
    assert verify(out["evidence"])


def test_staged_registry_has_exactly_23_original_captures():
    bindings = json.loads((ROOT / "agents/receiving/fixtures/captures.json").read_text())["captures"]
    actual = {p.relative_to(ROOT / "data/input").as_posix()
              for p in (ROOT / "data/input").glob("*/receiving/*.jpeg")}
    assert len(bindings) == len(actual) == 23
    assert {b["ref"] for b in bindings} == actual
    for binding in bindings:
        receiving._lookup(binding["subject_id"], binding["org_id"])
        raw = (ROOT / "data/input" / binding["ref"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == binding["sha256"]


@pytest.mark.parametrize("unit", ["UNIT-0001", "UNIT-0003", "UNIT-0012", "UNIT-0014", "UNIT-0039", "UNIT-9001", "UNIT-9002"])
def test_discovery_trusted_registration_and_real_pipeline(unit, monkeypatch):
    from tests.conftest import make_input
    registry = ROOT / "agents/receiving/fixtures/captures.json"
    bindings = [b for b in json.loads(registry.read_text())["captures"] if b["subject_id"] == unit]
    monkeypatch.setenv("INPUT_DIR", str(ROOT / "data/input"))
    monkeypatch.setenv("RECEIVING_CAPTURE_REGISTRY", str(registry))
    monkeypatch.setattr(receiving, "DATA_INPUT", ROOT / "data/input")

    class OfflineProvider:
        def analyze(self, req, *, stats, deadline):
            assert isinstance(req.image_bytes, bytes) and req.image_bytes.startswith(b"\xff\xd8")
            stats["calls"] += 1
            stats["attempts"].append({"model": "offline-combined", "outcome": "success"})
            # Deliberately incomplete facts: exercising staged imagery must not
            # turn synthetic pictures into an invented compliant judgment.
            return SimpleNamespace(parsed=ImageObservation(), model_id="offline-combined", tokens=0, latency_ms=0)

        def close(self):
            pass

    monkeypatch.setattr("agents.receiving.core.extraction.gemini.GeminiProvider", OfflineProvider)
    request = make_input("receiving", {"unit_id": unit, "org_id": bindings[0]["org_id"], "route": "unknown"})
    assert {i["ref"] for i in request["inputs"]} == {b["ref"] for b in bindings}
    found, issues, _ = receiving._resolve_inputs(request, unit)
    assert len(found) == len(bindings) and not issues
    out = receiving.handle(request)
    assert out["verdict"] != "PASS" and verify(out["evidence"])
    assert out["evidence"]["record_id"] == safety.record_id(request)
    assert receiving.handle(request) == out


def test_valid_upstream_rejected_on_http_and_inproc():
    from orchestration.clients import InProcClient, AgentRejected
    request = _req("UNIT-9001", "org_demo_alpha", rid="upstream-source")
    prior = receiving.handle(request)["evidence"]
    assert verify(prior)
    request["request_id"] = "upstream-rejected"
    request["previous_evidence"] = [prior]
    with pytest.raises(AgentRejected, match="unexpected_upstream_evidence"):
        InProcClient({"module": "agents.receiving.app"}).run(request, 30)
    with TestClient(receiving.app) as client:
        response = client.post("/run", json=request)
        assert response.status_code == 422
        assert response.json()["error"] == "unexpected_upstream_evidence"
