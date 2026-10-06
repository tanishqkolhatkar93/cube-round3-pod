import pytest

from agents.receiving.app import (REASON_MAP, _direct_check, _gate_rejected_checks,
                                  _identity_check, _quality_flags_check, _record_id, handle)
from agents.receiving.core.models import CheckResult


def _req(unit, org, rid="req-t1", inputs=None):
    return {"schema_version": "1.0", "request_id": rid, "workflow_id": f"WF-{org}-{unit}",
            "stage": "receiving", "subject": {"org_id": org, "subject_id": unit, "route": "mfn"},
            "inputs": inputs or [], "previous_evidence": [], "context": {}}


def cr(key, verdict, sv=None, reason=None, conf=0.8):
    return CheckResult(check_key=key, verdict=verdict, confidence=conf, detail="d",
                       model_version="m", summary_value=sv, uncertainty_reason=reason)


SPEC = {"sku": "SKU-BOTTLE-750", "product_title": "Steel Water Bottle"}


# ---- tenancy & fail-open (run against the pod's sample data) ----
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


# ---- mapping rolls (pure) ----
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