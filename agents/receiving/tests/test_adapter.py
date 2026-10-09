import pytest

from agents.receiving.app import (REASON_MAP, _direct_check, _gate_rejected_checks,
                                  _identity_check, _quality_flags_check, _record_id, handle)
from agents.receiving.core.models import CheckResult

SPEC = {"sku": "SKU-BOTTLE-750", "product_title": "Steel Water Bottle"}


def _req(unit, org, rid="req-t1", inputs=None):
    return {"schema_version": "1.0", "request_id": rid, "workflow_id": f"WF-{org}-{unit}",
            "stage": "receiving", "subject": {"org_id": org, "subject_id": unit, "route": "mfn"},
            "inputs": inputs or [], "previous_evidence": [], "context": {}}


def cr(key, verdict, sv=None, reason=None, conf=0.8):
    return CheckResult(check_key=key, verdict=verdict, confidence=conf, detail="d",
                       model_version="m", summary_value=sv, uncertainty_reason=reason)


def _gate_rejected_jpeg() -> bytes:
    """Deterministically REJECTED by the quality gate: extremely dark (mean
    brightness ~12 << DARK_REJECTED=30 -> 'extremely_dark' -> REJECTED).
    NOTE: a flat *gray* image is only DEGRADED (JPEG noise counts as edges);
    the suite must not rely on flatness. Using this keeps tests offline."""
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (12, 12, 12)).save(buf, "JPEG", quality=60)
    return buf.getvalue()


# ---------------------------------------------------------------- tenancy & fail-open
def test_wrong_org_refused():
    with pytest.raises(LookupError):
        handle(_req("UNIT-0001", "org_demo_bravo"))


def test_unknown_subject_refused():
    with pytest.raises(LookupError):
        handle(_req("UNIT-9999", "org_demo_alpha"))


def test_missing_captures_is_pending_not_fabricated():
    out = handle(_req("UNIT-0001", "org_demo_alpha"))
    ev = out["evidence"]
    assert out["status"] == "pending" and ev["decision"]["verdict"] == "UNCERTAIN"
    assert ev["checks"] == [] and ev["error"]["code"] == "upstream_missing"
    assert ev["decision"]["needs_human"] is True


def test_same_request_same_record_id():
    a = handle(_req("UNIT-0001", "org_demo_alpha", rid="fixed-1"))
    b = handle(_req("UNIT-0001", "org_demo_alpha", rid="fixed-1"))
    assert a["evidence"]["record_id"] == b["evidence"]["record_id"]
    assert _record_id(_req("UNIT-9001", "org_demo_alpha", rid="x")) == \
           _record_id(_req("UNIT-9001", "org_demo_alpha", rid="x"))


# ---------------------------------------------------------------- mapping rolls (pure)
def test_identity_roll_fail_wins():
    by = {"sku_identity": cr("sku_identity", "PASS", "yes"),
          "colour": cr("colour", "FAIL"), "variant": cr("variant", "PASS")}
    c = _identity_check(by, {}, SPEC)
    assert c["verdict"] == "FAIL" and c["observed"] == "no"


def test_identity_roll_uncertain():
    by = {"sku_identity": cr("sku_identity", "UNCERTAIN", "uncertain", "INSUFFICIENT_EVIDENCE"),
          "colour": cr("colour", "NOT_APPLICABLE"), "variant": cr("variant", "NOT_APPLICABLE")}
    c = _identity_check(by, {}, SPEC)
    assert c["verdict"] == "UNCERTAIN" and c["uncertain_reason"] == "insufficient_evidence"


def test_quality_flags_uncertain_when_contributor_uncertain():
    by = {"colour": cr("colour", "UNCERTAIN", "uncertain", "OCCLUSION")}
    c = _quality_flags_check(by, {}, [])
    assert c["verdict"] == "UNCERTAIN" and c["uncertain_reason"] == "occluded"


def test_reason_and_damage_vocab_mapping():
    r = cr("carton_damage", "UNCERTAIN", "uncertain", "OCCLUSION")
    c = _direct_check("carton_damage", r, {}, "none")
    assert c["uncertain_reason"] == "occluded"
    r2 = cr("carton_damage", "FAIL", "tear_or_open")
    assert _direct_check("carton_damage", r2, {}, "none")["observed"] == "tears"


def test_gate_rejected_all_uncertain_poor_image():
    checks = _gate_rejected_checks(["a.jpg"])
    assert len(checks) == 6 and all(c["verdict"] == "UNCERTAIN" for c in checks)
    assert all(c["uncertain_reason"] == "poor_image" for c in checks)


# ---------------------------------------------------------------- review-fix regressions: ref security
def test_safe_rel_rejects_unsafe():
    from agents.receiving.app import _safe_rel
    assert _safe_rel("UNIT-0001/receiving/carton.jpg") is True
    assert _safe_rel("UNIT-0001\\receiving\\carton.jpg") is False      # canonical refs use forward slashes
    assert _safe_rel("/etc/passwd") is False                          # absolute
    assert _safe_rel("C:/Windows/win.ini") is False                   # drive letter
    assert _safe_rel(r"C:\Windows\system32\config") is False
    assert _safe_rel("../../etc/passwd") is False                     # traversal
    assert _safe_rel("UNIT-1/../../../etc/passwd") is False
    assert _safe_rel("") is False


def test_unsafe_refs_surfaced_not_accessed():
    out = handle(_req("UNIT-0001", "org_demo_alpha", inputs=[
        {"ref": "C:/Windows/win.ini", "kind": "image"},
        {"ref": "../../etc/passwd", "kind": "image"}]))
    ev = out["evidence"]
    assert out["status"] == "error" and ev["error"]["code"] == "capture_rejected"
    assert ev["payload"]["diagnostics"]


def test_mixed_safe_and_unsafe_never_silently_drops_required_capture(register):
    inp = register(raw=_gate_rejected_jpeg())
    out = handle(_req("UNIT-9001", "org_demo_alpha", inputs=[inp, {"ref":"/etc/passwd","kind":"image"}]))
    assert out["status"] == "error" and out["error"]["code"] == "capture_rejected"
    assert out["verdict"] == "UNCERTAIN" and out["evidence"]["model"]["calls"] == 0


# ---------------------------------------------------------------- review-fix regressions: idempotency
def test_record_id_scheme_shared_by_pending_and_completed():
    from agents.receiving.app import _pending
    req = _req("UNIT-0001", "org_demo_alpha", rid="stable-1")
    p = _pending(req, code="upstream_missing", message="x")
    assert p["evidence"]["record_id"] == _record_id(req)
    assert p["evidence"]["record_id"].startswith("RCV-")
    assert "PENDING" not in p["evidence"]["record_id"]


def test_capture_arrival_conflicts_with_prior_request_but_new_attempt_works(register):
    from agents.receiving.safety import Rejected
    req = _req("UNIT-9001", "org_demo_alpha", rid="idem-1",
               inputs=[{"ref":"UNIT-9001/receiving/image.jpg","kind":"image"}])
    a = handle(req)
    register(raw=_gate_rejected_jpeg())
    with pytest.raises(Rejected,match="request_content_conflict"):
        handle(req)
    req["request_id"] = "idem-1:r2"
    b = handle(req)
    assert b["status"] == "completed" and b["verdict"] == "UNCERTAIN"
    assert b["evidence"]["record_id"] != a["evidence"]["record_id"]
    assert b["evidence"]["model"]["calls"] == 0
