"""Offline adversarial tests: actual adapter/rules, doubles only at inference."""
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import time

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from agents.prep import app as app_module
from agents.prep.adapter import Adapter
from agents.prep.common import Failure, Rejected, canonical, digest
from agents.prep.core.rulepacks.organizer import CHECKS, RULE_VERSION, applicable
from agents.prep.input_resolver import local_path
from agents.prep.request_store import RequestStore
from shared.utils.hashing import seal, verify
from shared.utils.records import build_record, check
from shared.utils.schema import errors


def write_item(root, path, content, ref=None):
    dest = root / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return {"ref": ref or path, "path": path, "sha256": hashlib.sha256(content).hexdigest()}


def image_bytes(color="red"):
    stream = io.BytesIO()
    Image.new("RGB", (12, 12), color).save(stream, format="PNG")
    return stream.getvalue()


def facts(criteria, indices=(1,)):
    observations = []
    for idx in indices:
        for _, field, expected, _ in CHECKS:
            if applicable(field, criteria):
                observations.append({"field": field, "value": criteria["expected_fnsku"] if field == "label_text" else expected,
                                     "photo_index": idx, "confidence": 0.95, "detail": "Explicit synthetic test observation"})
        for mark in criteria["required_handling_marks"]:
            observations.append({"field": "handling_mark:" + mark, "value": True, "photo_index": idx,
                                 "confidence": 0.95, "detail": "Synthetic marking visible"})
    return {"photos": [{"index": idx, "usable": True} for idx in indices], "observations": observations}


class Double:
    def __init__(self, value=None, error=None, delay=0):
        self.value, self.error, self.delay, self.calls = value, error, delay, 0

    def observe(self, images, criteria, deadline_s):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        value = self.value if self.value is not None else facts(criteria, range(1, len(images) + 1))
        return {"text": value if isinstance(value, str) else json.dumps(value), "model_version": "offline-double-v1"}


class Harness:
    def __init__(self, root):
        self.root, self.state = root / "sources", root / "state"
        self.root.mkdir()
        self.criteria = {"criteria_id": "criteria-SKU1", "version": "1", "source": "synthetic test requirements",
                         "rule_pack": RULE_VERSION, "sku": "SKU1", "expected_fnsku": "X001ABC123",
                         "requires_polybag": False, "requires_suffocation_warning": False,
                         "cover_original_barcode": True, "has_expiry": False, "required_handling_marks": []}
        self.config = {"version": 1, "org_id": "org-A", "client_id": "client-A", "bindings": [],
                       "provider": {"kind": "gemini", "model": "offline-test-model", "api_key_env": "PREP_TEST_NONEXISTENT_KEY", "deadline_s": 1}}
        self.binding = {"subject_id": "UNIT-A", "workflow_id": "WF-org-A-UNIT-A", "capture_id": "CAP-A",
                        "captured_at": "2026-10-01T10:00:00Z", "operator_id": "test-operator",
                        "criteria": write_item(self.root, "criteria.json", canonical(self.criteria).encode()),
                        "images": [write_item(self.root, "UNIT-A/prep/front.png", image_bytes())]}
        self.config["bindings"].append(self.binding)
        self.request = {"schema_version": "1.0", "request_id": "request-1", "workflow_id": self.binding["workflow_id"],
                        "stage": "prep", "subject": {"org_id": "org-A", "subject_id": "UNIT-A", "route": "fba"},
                        "inputs": [], "previous_evidence": [], "context": {}}
        self.provider = Double()
        self.constructed = 0

    def factory(self, config):
        self.constructed += 1
        return self.provider

    def update_criteria(self, **changes):
        self.criteria.update(changes)
        self.binding["criteria"] = write_item(self.root, "criteria.json", canonical(self.criteria).encode())

    def adapter(self, **kw):
        return Adapter(self.config, self.root, self.state, provider_factory=kw.get("factory", self.factory))

    def run(self, request=None):
        return self.adapter().handle(request or self.request)

    def material(self, thickness=1.5, durable=True):
        doc = {k: self.binding[k] for k in ("subject_id", "workflow_id", "capture_id", "captured_at")}
        doc.update(org_id=self.config["org_id"], attested_by="test-operator", thickness_mil=thickness, durable=durable)
        self.binding["material"] = write_item(self.root, "material.json", canonical(doc).encode())


@pytest.fixture
def h(tmp_path, monkeypatch):
    monkeypatch.delenv("PREP_TEST_NONEXISTENT_KEY", raising=False)
    return Harness(tmp_path)


def assert_output(out, verdict="PASS", status="completed"):
    assert errors("agent-output", out) == []
    assert verify(out["evidence"])
    assert out["verdict"] == verdict and out["status"] == status
    assert out["evidence"]["record_id"].startswith("PRP-")


def test_real_adapter_canonical_evidence(h):
    out = h.run()
    assert_output(out)
    ev = out["evidence"]
    assert ev["captured_at"] == h.binding["captured_at"]
    assert ev["payload"]["request_id"] == h.request["request_id"]
    assert ev["model"]["version"] == "offline-double-v1"
    assert ev["model"]["calls"] == 1
    assert ev["payload"]["policy_authority"] == "organizer_implementation_not_independently_verified"
    assert all(i["sha256"] for i in ev["inputs"])
    assert {r for c in ev["checks"] for r in c.get("evidence_refs", [])} <= {i["ref"] for i in ev["inputs"]}


@pytest.mark.parametrize("change", ["stage", "schema", "request_id", "extra", "workflow", "subject", "tenant"])
def test_invalid_request_before_provider(h, change):
    req = copy.deepcopy(h.request)
    if change == "stage": req["stage"] = "pack"
    if change == "schema": req["schema_version"] = "99"
    if change == "request_id": req["request_id"] = " "
    if change == "extra": req["product"] = {}
    if change == "workflow": req["workflow_id"] = "WF-foreign"
    if change == "subject": req["subject"]["subject_id"] = "UNIT-B"
    if change == "tenant": req["subject"]["org_id"] = "org-B"
    with pytest.raises(Rejected): h.run(req)
    assert h.constructed == 0


@pytest.mark.parametrize("ref", ["/tmp/x", "C:/x", "C:\\x", "\\\\server\\share", "../x", "a/../x", "a//x", "a/./x", "%2e%2e/x", "a/%252e%252e/x", "a\x00b"])
def test_unsafe_request_and_registration_paths(h, ref):
    req = copy.deepcopy(h.request)
    req["inputs"] = [{"ref": ref, "sha256": h.binding["images"][0]["sha256"]}]
    with pytest.raises(Rejected): h.run(req)
    h.binding["images"][0]["path"] = ref
    with pytest.raises(Rejected): h.run()
    assert h.constructed == 0


def test_foreign_capture_valid_hash_is_not_authorization(h):
    foreign = write_item(h.root, "UNIT-B/prep/front.png", image_bytes("blue"))
    h.request["inputs"] = [{"ref": foreign["ref"], "sha256": foreign["sha256"], "kind": "image"}]
    with pytest.raises(Rejected, match="unregistered"): h.run()
    assert h.constructed == 0


@pytest.mark.parametrize("kind", ["duplicate_request", "duplicate_ref", "duplicate_path", "duplicate_bytes", "hash", "kind", "bytes"])
def test_capture_integrity_before_provider(h, kind):
    item = h.binding["images"][0]
    if kind == "duplicate_request": h.request["inputs"] = [{k: item[k] for k in ("ref", "sha256")}] * 2
    if kind == "duplicate_ref": h.binding["images"].append(dict(item))
    if kind == "duplicate_path": h.binding["images"].append({**item, "ref": "another.png"})
    if kind == "duplicate_bytes": h.binding["images"].append(write_item(h.root, "copy.png", image_bytes()))
    if kind == "hash": h.request["inputs"] = [{"ref": item["ref"], "sha256": "0" * 64}]
    if kind == "kind": h.request["inputs"] = [{"ref": item["ref"], "sha256": item["sha256"], "kind": "video"}]
    if kind == "bytes": (h.root / item["path"]).write_bytes(image_bytes("blue"))
    with pytest.raises(Rejected): h.run()
    assert h.constructed == 0


def test_symlink_escape(h, tmp_path):
    outside = tmp_path / "outside.png"
    outside.write_bytes(image_bytes())
    link = h.root / "escape.png"
    try: link.symlink_to(outside)
    except OSError: pytest.skip("host does not permit creating symlinks")
    h.binding["images"][0]["path"] = "escape.png"
    with pytest.raises(Rejected, match="link"): h.run()
    assert h.constructed == 0


def test_no_silent_capture_truncation(h):
    h.binding["images"] *= 7
    with pytest.raises(Rejected): h.run()
    assert h.constructed == 0


@pytest.mark.parametrize("value", ["unknown", "false", None, 0, 1, [], {}])
def test_unknown_applicability_rejected(h, value):
    h.update_criteria(requires_polybag=value)
    with pytest.raises(Rejected): h.run()
    assert h.constructed == 0


def test_request_context_cannot_disable_requirements(h):
    h.update_criteria(has_expiry=True)
    value = facts(h.criteria)
    next(o for o in value["observations"] if o["field"] == "expiry_visible")["value"] = False
    h.provider.value = value
    h.request["context"] = {"has_expiry": False, "criteria": {"has_expiry": False}}
    assert_output(h.run(), "FAIL")


@pytest.mark.parametrize("field,bad", [(f, False if expected is True else "seam" if f == "fnsku_placement" else "WRONG123") for _, f, expected, _ in CHECKS]
                         + [("handling_mark:Fragile", False), ("handling_mark:This Way Up", False)])
def test_every_applicable_failure_reaches_decision(h, field, bad):
    h.update_criteria(requires_polybag=True, requires_suffocation_warning=True, has_expiry=True,
                      required_handling_marks=["Fragile", "This Way Up"])
    h.material()
    value = facts(h.criteria)
    next(o for o in value["observations"] if o["field"] == field)["value"] = bad
    h.provider.value = value
    out = h.run()
    assert_output(out, "FAIL")
    assert any(c["verdict"] == "FAIL" for c in out["evidence"]["checks"])


def test_material_and_not_applicable(h):
    out = h.run()
    assert any(a["state"] == "NOT_APPLICABLE" for a in out["evidence"]["payload"]["requirement_annotations"])
    h.request["request_id"] = "polybag"
    h.update_criteria(requires_polybag=True)
    out = h.run()
    assert_output(out, "UNCERTAIN")
    assert out["evidence"]["decision"]["needs_human"]
    assert any(a["state"] == "NOT_VERIFIABLE" for a in out["evidence"]["payload"]["requirement_annotations"])


@pytest.mark.parametrize("thickness,durable,verdict", [(1.5, True, "PASS"), (1.0, True, "FAIL"), (2, False, "FAIL")])
def test_registered_nonvisual_material(h, thickness, durable, verdict):
    h.update_criteria(requires_polybag=True)
    h.material(thickness, durable)
    assert_output(h.run(), verdict)


@pytest.mark.parametrize("label,verdict", [("X001ABC123", "PASS"), ("  x001abc123  ", "PASS"), ("ABC", "UNCERTAIN"),
                                          ("X001ABC", "UNCERTAIN"), ("X001ABC1239", "FAIL"), ("WRONG", "FAIL"),
                                          ("X001-ABC123", "UNCERTAIN"), ("X001 ABC123", "UNCERTAIN")])
def test_identity_comparison(h, label, verdict):
    h.provider.value = facts(h.criteria)
    next(o for o in h.provider.value["observations"] if o["field"] == "label_text")["value"] = label
    assert_output(h.run(), verdict)


@pytest.mark.parametrize("value", [999, -1, 0, 1.5, True, None, "1"])
def test_invalid_photo_index(h, value):
    h.provider.value = facts(h.criteria)
    h.provider.value["observations"][0]["photo_index"] = value
    out = h.run()
    assert_output(out, "UNCERTAIN", "pending")
    assert out["error"]["code"] == "invalid_observation"


@pytest.mark.parametrize("mode", ["malformed", "verdict", "missing_citation", "unknown_field", "bad_confidence", "nonfinite", "duplicate", "unsupported", "json_duplicate"])
def test_malformed_observations(h, mode):
    value = facts(h.criteria)
    if mode == "malformed": value = "not JSON"
    if mode == "verdict": value["verdict"] = "PASS"
    if mode == "missing_citation": del value["observations"][0]["photo_index"]
    if mode == "unknown_field": value["observations"][0]["field"] = "made_up"
    if mode == "bad_confidence": value["observations"][0]["confidence"] = 1.1
    if mode == "nonfinite": value = '{"photos":[],"observations":[],"extra":NaN}'
    if mode == "duplicate": value["observations"].append({**value["observations"][0], "value": False})
    if mode == "unsupported": value["observations"][0]["value"] = "met"
    if mode == "json_duplicate": value = '{"photos":[],"photos":[],"observations":[]}'
    h.provider.value = value
    out = h.run()
    assert_output(out, "UNCERTAIN", "pending")
    assert out["error"]["code"] == "invalid_observation"


@pytest.mark.parametrize("mode", ["missing_quality", "unusable", "partial", "low_confidence", "missing_mark", "unknown"])
def test_unresolved_required_observations_preserve_review(h, mode):
    h.update_criteria(required_handling_marks=["Fragile", "This Way Up"])
    value = facts(h.criteria)
    if mode == "missing_quality": value["photos"] = []
    if mode == "unusable": value["photos"][0]["usable"] = False
    if mode == "partial": value["observations"] = []
    if mode == "low_confidence": value["observations"][0]["confidence"] = 0.2
    if mode == "unknown": value["observations"][0]["value"] = None
    if mode == "missing_mark": value["observations"] = [o for o in value["observations"] if o["field"] != "handling_mark:This Way Up"]
    h.provider.value = value
    out = h.run()
    assert_output(out, "UNCERTAIN")
    assert out["evidence"]["decision"]["needs_human"]


@pytest.mark.parametrize("field", ["fnsku_present", "label_text"])
def test_cross_image_contradiction(h, field):
    h.binding["images"].append(write_item(h.root, "UNIT-A/prep/back.png", image_bytes("blue")))
    value = facts(h.criteria, (1, 2))
    next(o for o in value["observations"] if o["field"] == field and o["photo_index"] == 2)["value"] = "OTHER123" if field == "label_text" else False
    h.provider.value = value
    out = h.run()
    assert_output(out, "UNCERTAIN")
    assert any(c.get("uncertain_reason") == "conflicting_evidence" for c in out["evidence"]["checks"])


@pytest.mark.parametrize("mode,code", [("missing", "missing_image"), ("empty", "missing_image"), ("invalid", "invalid_image")])
def test_bad_images_do_not_construct_provider(h, mode, code):
    item = h.binding["images"][0]
    if mode == "missing": (h.root / item["path"]).unlink()
    if mode == "empty": h.binding["images"] = []
    if mode == "invalid": h.binding["images"][0] = write_item(h.root, item["path"], b"not an image")
    out = h.run()
    assert_output(out, "UNCERTAIN", "pending")
    assert out["error"]["code"] == code and h.constructed == 0


def test_missing_api_key(h):
    out = Adapter(h.config, h.root, h.state).handle(h.request)
    assert_output(out, "UNCERTAIN", "pending")
    assert out["error"]["code"] == "provider_unconfigured"
    assert out["model"]["calls"] == 0


@pytest.mark.parametrize("error,code", [(Failure("provider_unavailable"), "provider_unavailable"),
                                       (Failure("provider_timeout"), "provider_timeout"),
                                       (Failure("provider_rejected"), "provider_rejected"),
                                       (RuntimeError("SECRET_KEY_DO_NOT_PERSIST"), "provider_failure")])
def test_provider_failures_sanitized(h, error, code):
    h.provider.error = error
    out = h.run()
    assert_output(out, "UNCERTAIN", "pending")
    assert out["error"]["code"] == code
    assert "SECRET_KEY" not in canonical(out)


def test_deadline_and_late_result_cannot_rewrite_replay(h):
    h.config["provider"]["deadline_s"] = 0.02
    h.provider.delay = 0.1
    start = time.monotonic()
    out = h.run()
    assert time.monotonic() - start < 0.5
    assert_output(out, "UNCERTAIN", "pending")
    assert out["error"]["code"] == "provider_timeout"
    time.sleep(0.12)
    assert h.run() == out and h.provider.calls == 1


def test_replay_restart_and_defensive_copy(h):
    first = h.run()
    second = h.adapter().handle(h.request)
    assert first == second and h.provider.calls == 1
    second["evidence"]["payload"]["criteria"]["sku"] = "changed"
    assert h.run() == first


@pytest.mark.parametrize("mode", ["request", "criteria", "provider"])
def test_replay_conflict(h, mode):
    h.run()
    if mode == "request": h.request["context"]["new"] = 1
    if mode == "criteria": h.update_criteria(version="2")
    if mode == "provider": h.config["provider"]["model"] = "changed"
    with pytest.raises(Rejected, match="conflict"): h.run()
    assert h.provider.calls == 1


@pytest.mark.parametrize("scope", ["tenant", "subject", "workflow"])
def test_request_ids_are_scope_independent(h, scope):
    first = h.run()
    if scope == "tenant":
        h.config["org_id"] = h.request["subject"]["org_id"] = "org-B"
    if scope == "subject":
        h.binding["subject_id"] = h.request["subject"]["subject_id"] = "UNIT-B"
    if scope == "workflow":
        h.binding["workflow_id"] = h.request["workflow_id"] = "WF-new"
    second = h.run()
    assert first["evidence"]["record_id"] != second["evidence"]["record_id"] and h.provider.calls == 2


def test_concurrent_duplicate_has_one_inference(h):
    h.provider.delay = 0.1
    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs = list(pool.map(lambda _: h.run(), range(4)))
    assert all(o == outputs[0] for o in outputs)
    assert h.provider.calls == 1


def test_interrupted_reservation_requires_reconciliation(h):
    ledger = RequestStore(h.state / "prep-requests.sqlite3")
    def interrupted(): raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt): ledger.execute({"org_id": "A"}, "r", "f", {}, interrupted)
    with pytest.raises(Rejected, match="reconciliation"):
        ledger.execute({"org_id": "A"}, "r", "f", {}, lambda: pytest.fail("must not retry"))


def test_replay_corruption_rejected(h):
    h.run()
    with sqlite3.connect(h.state / "prep-requests.sqlite3") as db:
        db.execute("UPDATE requests SET output='{}'")
    with pytest.raises(Rejected, match="integrity"): h.run()
    assert h.provider.calls == 1


@pytest.mark.parametrize("mode", ["tenant", "subject", "workflow", "hash", "duplicate"])
def test_upstream_boundary(h, mode):
    req = {**h.request, "stage": "receiving"}
    rec = build_record(req, agent_id="test@1", record_id="RCV-1", captured_at=h.binding["captured_at"],
                       checks=[check("identity", "PASS", None)], outcome="accepted", reason="test", model={"name": "test", "version": "1"})
    if mode == "tenant": rec["subject"]["org_id"] = "other"
    if mode == "subject": rec["subject"]["subject_id"] = "other"
    if mode == "workflow": rec["workflow_id"] = "other"
    if mode != "hash": rec = seal(rec)
    else: rec["decision"]["reason"] = "tampered"
    h.request["previous_evidence"] = [rec, rec] if mode == "duplicate" else [rec]
    with pytest.raises(Rejected): h.run()
    assert h.constructed == 0


def test_real_inproc_client_and_orchestrator_validation(h, monkeypatch):
    from orchestration.clients import InProcClient, load_manifest
    from orchestration.orchestrator import _validate
    monkeypatch.setattr(app_module, "configured_adapter", h.adapter)
    out = InProcClient(load_manifest("prep")).run(h.request, 30)
    wf = {"workflow_id": h.request["workflow_id"], **h.request["subject"]}
    assert _validate(out, wf, "prep", h.request) == []


def test_http_contract_and_errors(h, monkeypatch):
    monkeypatch.setattr(app_module, "configured_adapter", h.adapter)
    with TestClient(app_module.app) as client:
        assert client.get("/health").json()["contract_version"] == "1.0"
        assert h.constructed == 0
        assert_output(client.post("/run", json=h.request).json())
        assert client.post("/run", json={}).status_code == 422
        assert client.post("/run", content="not JSON").status_code == 422
        assert client.post("/run", content='{"stage":"prep","stage":"pack"}').status_code == 422
        assert client.post("/run", json={**h.request, "stage": "pack"}).status_code == 422
        other = copy.deepcopy(h.request); other["subject"]["org_id"] = "other"
        assert client.post("/run", json=other).status_code == 404


def test_storage_failure_cannot_be_success(h, monkeypatch):
    def unavailable(*args): raise sqlite3.OperationalError("SECRET storage path")
    monkeypatch.setattr(RequestStore, "connect", unavailable)
    with pytest.raises(RuntimeError, match="prep_storage_unavailable"): h.run()
    assert h.constructed == 0
    monkeypatch.setattr(app_module, "configured_adapter", h.adapter)
    with TestClient(app_module.app) as client:
        response = client.post("/run", json=h.request)
        assert response.status_code == 503 and "SECRET" not in response.text


@pytest.mark.parametrize("mode,expected_status,expected_outcome", [("pass", "COMPLETED", "CLEAN"),
    ("partial", "BLOCKED", "NEEDS_REVIEW"), ("failure", "FAILED", "INCOMPLETE"), ("business", "COMPLETED", "EXCEPTION")])
def test_real_orchestration_rollup(h, monkeypatch, mode, expected_status, expected_outcome):
    from orchestration.clients import InProcClient, load_manifest
    from orchestration.orchestrator import run_workflow
    from orchestration.store import MemoryStore
    from tests.helpers import Fake
    if mode == "partial": h.provider.value = {"photos": [], "observations": []}
    if mode == "failure": h.provider.error = Failure("provider_unavailable")
    if mode == "business":
        h.provider.value = facts(h.criteria)
        h.provider.value["observations"][0]["value"] = False
    monkeypatch.setattr(app_module, "configured_adapter", h.adapter)
    flow = {"flow_id": "prep-test-only", "steps": [{"stage": "prep"}, {"stage": "recovery"}]}
    wf = run_workflow({"org_id": "org-A", "unit_id": "UNIT-A", "route": "fba"}, flow, MemoryStore(),
                      {"prep": InProcClient(load_manifest("prep")), "recovery": Fake("PASS")})
    assert (wf["status"], wf["final_outcome"]["outcome"]) == (expected_status, expected_outcome)


def test_recovery_consumes_real_prep_without_changes(h):
    from agents.recovery.rules import _deterministic_position
    def position(line, request):
        evidence = [{**r, "effective_verdict": r["decision"]["verdict"]}
                    for r in request["previous_evidence"] if r["status"] == "completed"]
        return _deterministic_position({**line, "amount_usd": 4.25}, evidence)
    out = h.run()
    request = {**h.request, "stage": "recovery", "previous_evidence": [out["evidence"]]}
    assert position({"charge_type": "inbound_defect_fee"}, request)[0] == "CONTRADICTS"
    h.request["request_id"] = "new-attempt"
    h.provider.error = Failure("provider_unavailable")
    request["previous_evidence"] = [h.run()["evidence"]]
    assert position({"charge_type": "inbound_defect_fee"}, request)[0] == "SILENT"
    assert position({"charge_type": "fulfilment_fee_weight_tier"}, request)[0] == "SILENT"


def test_registered_config_entry_point_without_factory_override(h, monkeypatch):
    """Real environment loading, with the default provider safely unconfigured."""
    filename = h.root / "registration.json"
    filename.write_text(canonical(h.config), encoding="utf-8")
    monkeypatch.setenv("PREP_CONFIG", str(filename))
    monkeypatch.setenv("PREP_STATE_DIR", str(h.state))
    out = app_module.handle(h.request)
    assert_output(out, "UNCERTAIN", "pending")
    assert out["error"]["code"] == "provider_unconfigured"


def test_unconfigured_service_is_degraded(h, monkeypatch):
    monkeypatch.delenv("PREP_CONFIG", raising=False)
    monkeypatch.delenv("PREP_STATE_DIR", raising=False)
    with TestClient(app_module.app) as client:
        assert client.get("/health").json()["status"] == "degraded"
        assert client.post("/run", json=h.request).status_code == 503


@pytest.mark.parametrize("mode", ["missing_document", "bad_hash", "missing_requirement", "unknown_pack", "bad_timestamp", "ambiguous_binding"])
def test_trusted_registration_validation(h, mode):
    if mode == "missing_document": (h.root / "criteria.json").unlink()
    if mode == "bad_hash": h.binding["criteria"]["sha256"] = "0" * 64
    if mode == "missing_requirement":
        del h.criteria["has_expiry"]
        h.update_criteria()
    if mode == "unknown_pack": h.update_criteria(rule_pack="unregistered@9")
    if mode == "bad_timestamp": h.binding["captured_at"] = "2026-10-01"
    if mode == "ambiguous_binding": h.config["bindings"].append(copy.deepcopy(h.binding))
    with pytest.raises(Rejected): h.run()
    assert h.constructed == 0


def test_material_scope_cannot_be_borrowed(h):
    h.update_criteria(requires_polybag=True)
    h.material()
    doc = json.loads((h.root / "material.json").read_text())
    doc["subject_id"] = "UNIT-B"
    h.binding["material"] = write_item(h.root, "material.json", canonical(doc).encode())
    with pytest.raises(Rejected, match="material_scope"): h.run()
    assert h.constructed == 0


@pytest.mark.parametrize("value", [-1, "1.5", True])
def test_invalid_material_measurement(h, value):
    h.update_criteria(requires_polybag=True)
    h.material(value)
    with pytest.raises(Rejected): h.run()


def test_no_cherry_picking_requested_subset(h):
    extra = write_item(h.root, "UNIT-A/prep/back.png", image_bytes("blue"))
    h.binding["images"].append(extra)
    first = h.binding["images"][0]
    h.request["inputs"] = [{"ref": first["ref"], "kind": "image", "sha256": first["sha256"]}]
    value = facts(h.criteria, (1, 2))
    next(o for o in value["observations"] if o["field"] == "label_text" and o["photo_index"] == 2)["value"] = "WRONG"
    h.provider.value = value
    assert_output(h.run(), "UNCERTAIN")


def test_fail_with_unresolved_requirement_still_requires_human(h):
    h.update_criteria(requires_polybag=True)
    value = facts(h.criteria)
    next(o for o in value["observations"] if o["field"] == "polybag_sealed")["value"] = False
    h.provider.value = value
    out = h.run()
    assert_output(out, "FAIL")
    assert out["evidence"]["decision"]["needs_human"]


def test_invalid_output_is_never_published_or_reinferred(h, monkeypatch):
    import agents.prep.adapter as adapter_module
    monkeypatch.setattr(adapter_module, "build_output", lambda record: {"verdict": "PASS"})
    with pytest.raises(Rejected): h.run()
    with pytest.raises(Rejected, match="reconciliation"): h.run()
    assert h.provider.calls == 1


def test_constructor_exception_is_sanitized_pending(h):
    def broken(config): raise RuntimeError("SECRET_TOKEN")
    out = h.adapter(factory=broken).handle(h.request)
    assert_output(out, "UNCERTAIN", "pending")
    assert out["error"]["code"] == "prep_exception"
    assert "SECRET_TOKEN" not in canonical(out)


def test_process_restart_replays_without_inference(h):
    """A separate Python process reads the durable ledger, not a Python cache."""
    import subprocess
    import sys
    first = h.run()
    config_file = h.root / "registration.json"
    config_file.write_text(canonical(h.config), encoding="utf-8")
    script = '''import json,sys
from agents.prep.adapter import Adapter
config,root,state,request=json.loads(sys.stdin.read())
def forbidden(config): raise AssertionError("provider constructed on replay")
print(json.dumps(Adapter(config,root,state,provider_factory=forbidden).handle(request)))
'''
    result = subprocess.run([sys.executable, "-B", "-c", script], input=canonical([h.config, str(h.root), str(h.state), h.request]),
                            text=True, capture_output=True, check=True, timeout=20)
    assert json.loads(result.stdout) == first


def test_running_reservation_after_crash_never_auto_retries(h):
    ledger = RequestStore(h.state / "prep-requests.sqlite3")
    scope = {"org_id": "A", "subject_id": "U"}
    with ledger.connect() as db:
        db.execute("INSERT INTO requests VALUES (?,?,?,?,'running',NULL,NULL)", (canonical(scope), "r", "f", "{}"))
    with pytest.raises(Rejected, match="in_progress_or_interrupted"):
        ledger.execute(scope, "r", "f", {}, lambda: pytest.fail("must not reinfer"), wait_seconds=0)


def test_full_standard_handoff_with_real_returns_and_recovery(h, monkeypatch, tmp_path):
    from orchestration.orchestrator import load_flow, run_workflow, bundle
    from orchestration.store import MemoryStore
    from shared.utils import sample_data
    case = next(c for c in json.loads((Path(__file__).resolve().parents[3] / "data/sample/cases.json").read_text())
                if c["unit_id"] == "UNIT-0014")
    root = Path(__file__).resolve().parents[3]
    h.config["org_id"] = case["org_id"]
    h.config["client_id"] = None
    h.binding["subject_id"] = case["unit_id"]
    h.binding["workflow_id"] = f"WF-{case['org_id']}-{case['unit_id']}"
    returns_config = tmp_path / "returns-config.json"
    returns_config.write_text(canonical({"mode": "synthetic", "csv": "returns_sample.csv",
                                       "tenants": [{"organization_id": case["org_id"], "client_id": None}]}))
    (tmp_path / "returns_sample.csv").write_bytes((root / "data/sample/returns_sample.csv").read_bytes())
    monkeypatch.setenv("RETURNS_CONFIG", str(returns_config))
    monkeypatch.setenv("RETURNS_STATE_DIR", str(tmp_path / "returns-state"))
    monkeypatch.setenv("ORCH_MODE", "inproc")
    monkeypatch.setattr(app_module, "configured_adapter", h.adapter)
    from tests.integration.pack_recovery_support import Scenarios
    Scenarios(tmp_path / "registered-commerce", monkeypatch, [case])
    from agents.receiving import app as receiving
    capture_root = tmp_path / "receiving-input"
    capture_root.mkdir(exist_ok=True)
    monkeypatch.setenv("INPUT_DIR", str(capture_root))
    monkeypatch.setattr(receiving, "DATA_INPUT", capture_root)
    monkeypatch.setenv("RECEIVING_STATE_DIR", str(tmp_path / "receiving-state"))
    store = MemoryStore()
    wf = run_workflow(case, load_flow(root / "orchestration/flow.json"), store)
    records = bundle(wf, store)["evidence"]
    prep = next(r for r in records.values() if r["stage"] == "prep")
    returns = next(r for r in records.values() if r["stage"] == "returns")
    recovery = next(r for r in records.values() if r["stage"] == "recovery")
    assert prep["decision"]["verdict"] == "PASS"
    assert prep["record_id"] in returns["upstream_refs"]
    assert prep["record_id"] in recovery["upstream_refs"]
    assert wf["status"] == "FAILED"  # Missing Returns photos are still visible.
    assert wf["final_outcome"]["outcome"] == "CLAIM_RECOMMENDED"
    assert wf["final_outcome"]["provisional"]
    assert all(verify(r) and not errors("evidence", r) for r in records.values())
