"""Returns boundary tests. All images/provider results here are explicit test data."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from agents.returns.adapter import Adapter
from agents.returns.app import app, configured_adapter
from agents.returns.input_resolver import SAMPLE_SHA256
from agents.returns.request_store import Rejected, RequestStore, digest
from agents.returns.core.returns_manager.domain import (
    TenantContext, ObservationPlaceholder, CollectionLineage, DecisionReference, Component,
)
from agents.returns.core.returns_manager.validation import read_csv, parse_record, validate_capture
from agents.returns.core.returns_manager.storage import Store
from agents.returns.core.returns_manager.rules import assess
from agents.returns.core.returns_manager.vision import observe, ImageInput, FixtureProvider
from agents.returns.core.returns_manager.observations import ObservationScope, ProviderResponse
from agents.returns.core.returns_manager.ollama import OllamaVisionProvider, OllamaConfig
from shared.utils.hashing import verify, seal
from shared.utils.records import build_record, check
from shared.utils.schema import errors
from tests.conftest import ROOT, make_input

ROWS = read_csv(ROOT / "data/sample/returns_sample.csv")


def request_for(row=ROWS[0][0]):
    return make_input("returns", {"org_id": row["org_id"], "unit_id": row["unit_id"],
                                  "route": "fba", "returned": True})


def response(request):
    return {"scope": asdict(request.scope), "identity": [], "components": [], "condition": [],
            "limitations": ["Explicit test response; no visual claims."]}


class MockReal:
    name, mode = "test-real-boundary", "real"

    def __init__(self, failure=None):
        self.calls, self.failure = 0, failure

    def observe(self, request):
        self.calls += 1
        time.sleep(0.03)
        if self.failure:
            raise self.failure("test-only private provider diagnostic")
        return ProviderResponse(json.dumps(response(request)), self.name, self.mode, "test-model")


@pytest.fixture
def existing(tmp_path):
    row, source = ROWS[0]
    tenant = TenantContext(row["org_id"], "test-client")
    capture = parse_record(row, tenant, source)
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(stream, format="PNG")
    content = stream.getvalue()  # Explicit decoder fixture, never a claimed product photograph.
    (tmp_path / "test.png").write_bytes(content)
    with Store(tmp_path / "source.sqlite3", tenant) as store:
        store.save_capture(capture)
    config = {"mode": "existing", "tenants": [asdict(tenant)],
        "provider": {"name": "ollama", "settings": {"timeout_seconds": 10}},
        "bindings": [{"organization_id": tenant.organization_id, "unit_id": capture.unit.unit_id,
            "record_id": capture.record_id, "database": "source.sqlite3", "capture_sha256": digest(asdict(capture)),
            "inspection": "live", "images": [{"ref": capture.images[0].reference, "path": "test.png",
                "kind": "genuine", "sha256": hashlib.sha256(content).hexdigest(), "role": "returned_product",
                "image_id": "test-image", "evidence_id": "test-evidence"}]}]}
    return config, capture, tmp_path


def adapter_for(existing, provider=None):
    config, _, root = existing
    return Adapter(config, root, root / "state", provider=provider or MockReal())


@pytest.mark.parametrize("row,source", ROWS, ids=[r["unit_id"] for r, _ in ROWS])
def test_all_24_rows_preserve_lineage_and_never_replay_labels(row, source):
    validate_capture(parse_record(row, TenantContext(row["org_id"]), source))
    out = configured_adapter().handle(request_for(row))
    assert not errors("agent-output", out) and verify(out["evidence"])
    ev, payload = out["evidence"], out["evidence"]["payload"]
    assert ev["record_id"].startswith("RTN-") and payload["capture_record_id"] == row["record_id"]
    assert payload["request_id"] == request_for(row)["request_id"]
    assert ev["subject"]["unit_id"] == row["unit_id"] and ev["subject"]["org_id"] == row["org_id"]
    assert ev["captured_at"] == row["captured_at"]
    assert payload["source"]["source_sha256"] == SAMPLE_SHA256 == source.source_sha256
    assert payload["source"]["row_number"] == source.row_number
    assert dict(payload["capture"]["raw_fields"]) == row
    assert payload["vision_run"] is None and payload["assessment"]["observation"]["status"] == "unavailable"
    assert all(c["verdict"] == "UNCERTAIN" for c in ev["checks"])
    assert out["status"] == "pending" and out["error"]["code"] == "missing_image"
    assert ev["decision"]["outcome"] == "pending_review" and out["model"]["calls"] == 0
    assert all(i["sha256"] is None for i in ev["inputs"] if i["kind"] == "image")


@pytest.mark.parametrize("ref", ["../photo.jpg", "/etc/passwd", "C:/photo.jpg", "a\\b.jpg",
                               "a/%2e%2e/b", "photo.jpg", "foreign/UNIT-9999.jpg"])
def test_unregistered_or_traversal_refs(ref):
    req = request_for()
    req["inputs"] = [{"ref": ref, "kind": "image"}]
    with pytest.raises(Rejected):
        configured_adapter().handle(req)


def test_synthetic_registered_missing_reference_is_not_image_evidence():
    req = request_for()
    req["inputs"] = [{"ref": ROWS[0][0]["photo_refs"].split(";")[0], "kind": "image", "sha256": None}]
    assert configured_adapter().handle(req)["error"]["code"] == "missing_image"
    req["request_id"] += "-changed"
    req["inputs"][0]["sha256"] = "0" * 64
    with pytest.raises(Rejected, match="input_hash_mismatch"):
        configured_adapter().handle(req)


def test_wrong_tenant_and_client_configuration(existing):
    req = request_for()
    req["subject"]["org_id"] = "other-tenant"
    with pytest.raises(Rejected) as error:
        adapter_for(existing).handle(req)
    assert error.value.status == 404
    existing[0]["tenants"][0]["client_id"] = None
    with pytest.raises(Rejected, match="explicit_client"):
        adapter_for(existing)


def test_source_tampering_is_rejected():
    config = Path(os.environ["RETURNS_CONFIG"])
    with (config.parent / "returns_sample.csv").open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(Rejected, match="organizer_source_tampered"):
        configured_adapter().handle(request_for())


def test_existing_live_uses_engine_and_preserves_source_db(existing):
    provider = MockReal()
    source = existing[2] / "source.sqlite3"
    before = source.read_bytes()
    out = adapter_for(existing, provider).handle(request_for())
    assert provider.calls == 1 and out["status"] == "completed"
    assert out["verdict"] == "UNCERTAIN" and out["error"] is None
    assert out["evidence"]["client_id"] == "test-client"
    assert out["evidence"]["payload"]["vision_run"]["provider_mode"] == "real"
    assert out["evidence"]["payload"]["local_attempt_id"] == 1
    assert source.read_bytes() == before and verify(out["evidence"])


@pytest.mark.parametrize("failure,code", [(TimeoutError, "provider_timeout"), (RuntimeError, "provider_failure")])
def test_provider_failures_preserve_error_category(existing, failure, code):
    out = adapter_for(existing, MockReal(failure)).handle(request_for())
    assert out["status"] == "pending" and out["verdict"] == "UNCERTAIN" and out["error"]["code"] == code
    assert out["model"]["version"] == "unknown"
    assert "private provider diagnostic" not in json.dumps(out)
    assert not errors("agent-output", out)


def test_missing_registered_image_returns_pending_without_provider(existing):
    (existing[2] / "test.png").unlink()
    provider = MockReal()
    out = adapter_for(existing, provider).handle(request_for())
    assert out["error"]["code"] == "missing_image" and provider.calls == 0
    assert out["evidence"]["payload"]["missing_photos"] is True


@pytest.mark.parametrize("mutation", ["ambiguous", "capture_hash", "image_hash", "role", "membership", "path",
                                    "no_selection", "latest", "foreign_client"])
def test_existing_rejections_before_provider(existing, mutation):
    config, _, root = existing
    binding = config["bindings"][0]
    if mutation == "ambiguous":
        config["bindings"].append(deepcopy(binding))
    elif mutation == "capture_hash":
        binding["capture_sha256"] = "0" * 64
    elif mutation == "image_hash":
        (root / "test.png").write_bytes(b"tampered")
    elif mutation == "role":
        binding["images"][0]["role"] = "ordered_product"
    elif mutation == "membership":
        binding["images"][0]["ref"] = "foreign/photo.png"
    elif mutation == "path":
        binding["images"][0]["path"] = "../test.png"
    elif mutation == "no_selection":
        binding["inspection"] = "automatic"
    elif mutation == "latest":
        binding["inspection"], binding["attempt_id"] = "stored", "latest"
    elif mutation == "foreign_client":
        config["tenants"][0]["client_id"] = "other-client"
    provider = MockReal()
    with pytest.raises(Rejected):
        adapter_for(existing, provider).handle(request_for())
    assert provider.calls == 0


def stored_binding(existing):
    config, capture, root = existing
    item = config["bindings"][0]["images"][0]
    image = ImageInput(ObservationScope.from_capture(capture), item["image_id"], item["evidence_id"],
                      item["ref"], item["role"], "genuine", (root / "test.png").read_bytes())
    run = observe(capture, (image,), MockReal())
    result = assess(capture, run.observations)
    with Store(root / "source.sqlite3", capture.tenant) as store:
        attempt_id = store.save_vision_attempt(capture, run, result)
        store.save_vision_attempt(capture, observe(capture, (image,), MockReal(TimeoutError)),
                                  assess(capture, ObservationPlaceholder("provider_timeout")))
    binding = config["bindings"][0]
    binding.update(inspection="stored", attempt_id=attempt_id,
                   attempt_sha256=digest({"run": asdict(run), "assessment": asdict(result)}))
    config.pop("provider")
    return binding


def test_explicit_stored_attempt_never_chooses_latest_or_calls_provider(existing):
    stored_binding(existing)
    provider = MockReal(RuntimeError)
    out = adapter_for(existing, provider).handle(request_for())
    assert out["status"] == "completed" and provider.calls == 0
    assert out["evidence"]["payload"]["selected_attempt_id"] == 1


def test_stored_attempt_tamper_rejected(existing):
    stored_binding(existing)
    with sqlite3.connect(existing[2] / "source.sqlite3") as db:
        db.execute("UPDATE vision_attempts SET assessment='{}' WHERE attempt_id=1")
    with pytest.raises(Rejected, match="attempt_hash_mismatch"):
        adapter_for(existing).handle(request_for())


def test_replay_after_restart_and_changed_content(existing):
    provider = MockReal()
    req = request_for()
    first = adapter_for(existing, provider).handle(req)
    assert adapter_for(existing, provider).handle(req) == first and provider.calls == 1
    req["context"]["new_hint"] = "changed"
    with pytest.raises(Rejected, match="request_content_conflict"):
        adapter_for(existing, provider).handle(req)
    assert provider.calls == 1


def test_concurrent_duplicate_calls_only_invoke_once(existing):
    provider = MockReal()
    adapters = [adapter_for(existing, provider) for _ in range(6)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        outputs = list(pool.map(lambda a: a.handle(request_for()), adapters))
    assert all(o == outputs[0] for o in outputs) and provider.calls == 1


def test_interrupted_reservation_never_retries_inference(tmp_path):
    store = RequestStore(tmp_path / "requests.sqlite3")
    calls = []
    def crash():
        calls.append(1)
        raise RuntimeError("crash")
    with pytest.raises(RuntimeError):
        store.execute({"org": "test"}, "request", "fingerprint", {}, crash)
    with pytest.raises(Rejected, match="reconciliation"):
        RequestStore(store.path).execute({"org": "test"}, "request", "fingerprint", {}, crash)
    assert len(calls) == 1


def test_actual_process_restart_returns_exact_output():
    req = request_for()
    first = configured_adapter().handle(req)
    script = "import json,sys; from agents.returns.app import handle; print(json.dumps(handle(json.load(sys.stdin))))"
    proc = subprocess.run([sys.executable, "-c", script], input=json.dumps(req), text=True,
                          capture_output=True, cwd=ROOT, check=True)
    assert json.loads(proc.stdout) == first


def test_upstream_immutable_and_override_only_changes_context():
    req = request_for()
    upstream = build_record({**req, "stage": "receiving"}, agent_id="test", record_id="RCV-test",
        captured_at=ROWS[0][0]["captured_at"], checks=[check("identity", "FAIL", None)],
        outcome="test", reason="test", model={"name": "rules", "version": "test"})
    req["previous_evidence"] = [upstream]
    req["context"]["overrides"] = [{"supersedes": {"record_id": "RCV-test"}, "target": "decision", "new_verdict": "PASS"}]
    before = deepcopy(req)
    out = configured_adapter().handle(req)
    assert req == before and out["evidence"]["upstream_refs"] == ["RCV-test"]
    context = out["evidence"]["payload"]["upstream_context"][0]
    assert context["automated_verdict"] == "FAIL" and context["effective_verdict"] == "PASS"
    assert out["verdict"] == "UNCERTAIN"
    req["request_id"] += "-tampered"
    req["previous_evidence"][0]["decision"]["verdict"] = "PASS"
    with pytest.raises(Rejected, match="upstream_hash"):
        configured_adapter().handle(req)


def test_real_ollama_transport_is_reachable_without_network(existing):
    calls = []
    def transport(url, payload, timeout):
        calls.append((url, payload, timeout))
        return json.dumps({"message": {"role": "assistant", "content": json.dumps({
            "scope": asdict(ObservationScope.from_capture(existing[1])), "identity": [], "components": [],
            "condition": [], "limitations": ["Explicit mocked transport."]})},
            "model": "test-local", "done": True}).encode()
    provider = OllamaVisionProvider(OllamaConfig(model="test-local", timeout_seconds=10), transport=transport)
    out = adapter_for(existing, provider).handle(request_for())
    assert len(calls) == 1 and out["evidence"]["payload"]["vision_run"]["provider_mode"] == "real"
    assert out["status"] == "completed"


def test_fixture_cannot_replace_live_provider(existing):
    with pytest.raises(Rejected, match="must_be_real"):
        adapter_for(existing, FixtureProvider("{}"))
    existing[0].pop("provider")
    with pytest.raises(Rejected, match="explicit_real_provider"):
        adapter_for(existing)


def test_http_errors_and_explicit_configuration(monkeypatch):
    client = TestClient(app)
    assert client.post("/run", json={}).status_code == 422
    req = request_for()
    req["subject"]["org_id"] = "other"
    assert client.post("/run", json=req).status_code == 404
    req = request_for()
    first = client.post("/run", json=req)
    assert first.status_code == 200 and first.json()["status"] == "pending"
    req["context"]["changed"] = True
    assert client.post("/run", json=req).status_code == 409
    monkeypatch.delenv("RETURNS_CONFIG")
    assert client.get("/health").json()["status"] == "degraded"
    assert client.post("/run", json=request_for()).status_code == 503


def test_collection_ingestion_timestamp_cannot_be_exported(existing):
    config, original, root = existing
    row = dict(original.raw_fields)
    metadata = {"case_id": row["record_id"], "unit_id": row["unit_id"], "order_id": row["order_id"],
                "sku": row["ordered_sku"], "asin": row["ordered_asin"], "independent_annotations": "not_supplied"}
    snapshot = json.dumps({"metadata": metadata, "images": [{"source_path": "test.png"}]})
    source = CollectionLineage("explicit-test-collection", hashlib.sha256(snapshot.encode()).hexdigest(), 2, snapshot)
    for key in ("identity_match", "parts_list", "parts_missing", "observed_state", "amazon_condition", "operator_disposition"):
        row[key] = ""
    row["photo_refs"] = "collection/test.png"
    capture = parse_record(row, original.tenant, source)
    with Store(root / "collection.sqlite3", original.tenant) as store:
        store.save_capture(capture)
    config["bindings"][0].update(database="collection.sqlite3", capture_sha256=digest(asdict(capture)))
    provider = MockReal()
    with pytest.raises(Rejected, match="physical_capture_timestamp_unavailable"):
        adapter_for(existing, provider).handle(request_for())
    assert provider.calls == 0


@pytest.mark.parametrize("field", ["source_sha256", "unit_id", "ordered_sku", "tenant"])
def test_explicit_reference_binding_is_validated(existing, field):
    config, capture, _ = existing
    # Deliberate synthetic reference, not a real attestation.
    reference = asdict(DecisionReference(capture.tenant, capture.record_id, capture.unit.unit_id,
        capture.order.order_id, capture.order.ordered_sku, capture.order.ordered_asin, (),
        False, "test-reference", "Explicit synthetic test source.", "test-operator",
        "2026-01-01T00:00:00Z", "synthetic_demo"))
    reference[field] = {"organization_id": "foreign", "client_id": "test-client"} if field == "tenant" else "wrong"
    config["bindings"][0]["reference"] = reference
    provider = MockReal()
    with pytest.raises(Rejected):
        adapter_for(existing, provider).handle(request_for())
    assert provider.calls == 0


@pytest.mark.parametrize("failure,expected", [
    ("empty", "empty_response"), ("invalid", "invalid_response"),
    ("metadata", "provider_metadata_mismatch"), ("scope", "response_scope_mismatch"),
])
def test_invalid_provider_responses_fail_open(existing, failure, expected):
    class Provider(MockReal):
        def observe(self, request):
            value = response(request)
            if failure == "scope":
                value["scope"]["tenant"]["organization_id"] = "foreign"
            text = "" if failure == "empty" else ("not-json" if failure == "invalid" else json.dumps(value))
            return ProviderResponse(text, "foreign" if failure == "metadata" else self.name, self.mode)
    out = adapter_for(existing, Provider()).handle(request_for())
    assert out["status"] == "pending" and out["error"]["code"] == expected
    assert out["evidence"]["payload"]["vision_run"]["raw_response"] is None


def test_stored_fixture_is_explicit_and_requires_opt_in(existing):
    config, capture, root = existing
    binding = config["bindings"][0]
    item = binding["images"][0]
    item.update(kind="fixture")
    item.pop("sha256")
    item.pop("path")
    image = ImageInput(ObservationScope.from_capture(capture), item["image_id"], item["evidence_id"],
                      item["ref"], item["role"], "fixture")
    raw = json.dumps({"scope": asdict(image.scope), "identity": [], "components": [], "condition": [],
                      "limitations": ["Explicit fixture, no inference."]})
    run = observe(capture, (image,), FixtureProvider(raw))
    result = assess(capture, run.observations)
    with Store(root / "source.sqlite3", capture.tenant) as store:
        attempt_id = store.save_vision_attempt(capture, run, result)
    binding.update(inspection="stored", attempt_id=attempt_id,
                   attempt_sha256=digest({"run": asdict(run), "assessment": asdict(result)}))
    config.pop("provider")
    with pytest.raises(Rejected, match="fixture_mode_not_authorized"):
        adapter_for(existing).handle(request_for())
    config["allow_fixture"] = True
    out = adapter_for(existing).handle(request_for())
    assert out["evidence"]["payload"]["vision_run"]["provider_mode"] == "fixture"
    assert out["verdict"] == "UNCERTAIN"


def test_stored_rules_are_recomputed_even_if_attempt_hash_is_reanchored(existing):
    binding = stored_binding(existing)
    with sqlite3.connect(existing[2] / "source.sqlite3") as db:
        row = db.execute("SELECT payload,assessment FROM vision_attempts WHERE attempt_id=1").fetchone()
        run, result = map(json.loads, row)
        result["identity"]["verdict"] = "PASS"
        db.execute("UPDATE vision_attempts SET assessment=? WHERE attempt_id=1", (json.dumps(result),))
    binding["attempt_sha256"] = digest({"run": run, "assessment": result})
    with pytest.raises(Rejected, match="stored_assessment_tampered"):
        adapter_for(existing).handle(request_for())


def test_source_snapshot_change_conflicts_on_same_request(existing):
    first = adapter_for(existing).handle(request_for())
    existing[0]["provider"]["settings"]["model"] = "different-model"
    with pytest.raises(Rejected, match="request_content_conflict"):
        adapter_for(existing).handle(request_for())
    assert first["status"] == "completed"


def test_processes_share_durable_reservation(tmp_path):
    script = """
import json,sys,time
from pathlib import Path
from agents.returns.request_store import RequestStore
root=Path(sys.argv[1])
def invoke():
    with (root/'calls.txt').open('a') as f: f.write('invoked\\n')
    time.sleep(0.3)
    return {'value':'exact'}
print(json.dumps(RequestStore(root/'multi.sqlite3').execute({'org':'test'},'req','fp',{},invoke)))
"""
    workers = [subprocess.Popen([sys.executable, "-c", script, str(tmp_path)], cwd=ROOT,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(3)]
    outputs = [p.communicate(timeout=20) for p in workers]
    assert all(p.returncode == 0 for p in workers), outputs
    assert all(json.loads(out) == {"value": "exact"} for out, _ in outputs)
    assert (tmp_path / "calls.txt").read_text().splitlines() == ["invoked"]


def test_pinned_engine_source_hashes():
    core = ROOT / "agents/returns/core"
    manifest = json.loads((core / "provenance.json").read_text())
    for name, expected in manifest["files"].items():
        text = (core / "returns_manager" / name).read_text(encoding="utf-8")
        assert hashlib.sha256(text.replace("\r\n", "\n").encode()).hexdigest() == expected, name


@pytest.mark.parametrize("filename", ["requests.sqlite3", "engine.sqlite3"])
def test_runtime_cannot_modify_source_database(existing, filename):
    config, _, root = existing
    target = root / filename
    target.write_bytes((root / "source.sqlite3").read_bytes())
    config["bindings"][0]["database"] = filename
    before = target.read_bytes()
    with pytest.raises(Rejected, match="runtime_must_not_overlap_source"):
        Adapter(config, root, root, provider=MockReal())
    assert target.read_bytes() == before


def test_later_stage_overrides_are_not_treated_as_returns_evidence():
    request = request_for()
    request["context"]["overrides"] = [
        {"supersedes": {"record_id": "RCY-later-stage"}, "target": "decision", "new_verdict": "PASS"}]
    before = deepcopy(request)
    out = configured_adapter().handle(request)
    assert out["verdict"] == "UNCERTAIN"
    assert out["evidence"]["payload"]["upstream_context"] == []
    assert request == before
