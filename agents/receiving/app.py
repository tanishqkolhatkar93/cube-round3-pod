"""Receiving Manager — Round 3 adapter over the Round 2 judgment core.

Contract rules honoured here (EVIDENCE-CONTRACT.md):
- Same request_id in -> same record_id out (hash scheme, resume-safe).
- Fail open: unresolvable captures or model failure -> pending record, never a crash.
- Tenancy: unknown subject or wrong org -> LookupError -> 404, never a cross-tenant answer.
- captured_at never silently "now" (source recorded in payload).
- A check that does not apply is omitted; every UNCERTAIN carries a reason.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from shared.utils import sample_data
from shared.utils.records import (build_output, build_record, check, pending_output,
                                  rollup, utcnow)
from shared.utils.server import make_app

from .core.config import CFG, REPO_ROOT
from .core.engine import run_engine
from .core.models import POLineItem, CheckContext, CheckResult

STAGE = "receiving"
AGENT_ID = "receiving-manager@1.0.0"
VERSION = "1.0.0"

REGISTRY = Path(__file__).resolve().parent / "fixtures" / "units.json"
DATA_INPUT = REPO_ROOT / "data" / "input"

REASON_MAP = {"INSUFFICIENT_EVIDENCE": "insufficient_evidence", "OCCLUSION": "occluded",
              "LOW_IMAGE_QUALITY": "poor_image", "CONFLICTING_EVIDENCE": "conflicting_evidence",
              "EXTRACTION_FAILED": "model_error"}
DAMAGE_VOCAB = {"tear_or_open": "tears", "crushing": "crushing", "water": "water",
                "dent": "dent", "other": "other", "none": "none"}


def load_registry() -> dict:
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8")).get("units", {})
    return {}


def _lookup(subject_id: str, org_id: str):
    """Tenancy: fixture registry (org-checked) then sample rows (org-scoped)."""
    u = load_registry().get(subject_id)
    if u is not None:
        if u.get("org_id") != org_id:
            raise LookupError(f"{subject_id} is not in {org_id}")
        return u, "fixture"
    return sample_data.row("receiving", subject_id, org_id), "sample"   # LookupError -> 404


def _na(v):
    return None if (v is None or str(v).strip().lower() in ("", "n/a", "na")) else v


def _spec_of(unit, source) -> dict:
    if source == "fixture":
        r = unit
    else:  # sample CSV row -> shared shape
        r = {"sku": unit["sku"], "asin": unit.get("asin"), "product_title": unit.get("product_title"),
             "spec_colour": _na(unit.get("spec_colour")), "spec_variant": _na(unit.get("spec_variant")),
             "spec_components": [c.strip() for c in unit["spec_components"].split(";") if c.strip()] or None
                if unit.get("spec_components") else None,
             "cartons_ordered": int(unit["cartons_ordered"]) if unit.get("cartons_ordered") else None,
             "units_per_carton_ordered": int(unit["units_per_carton_ordered"]) if unit.get("units_per_carton_ordered") else None,
             "qty_ordered": int(unit["qty_ordered"]), "po_number": unit.get("po_number"),
             "po_line": unit.get("po_line"), "supplier": unit.get("supplier"),
             "operator_id": unit.get("operator_id"), "captured_at": unit.get("captured_at")}
    return {"sku": r["sku"], "asin": r.get("asin"), "product_title": r.get("product_title"),
            "spec_colour": _na(r.get("spec_colour")), "spec_variant": _na(r.get("spec_variant")),
            "spec_components": r.get("spec_components") or None,
            "cartons_ordered": r.get("cartons_ordered"),
            "units_per_carton_ordered": r.get("units_per_carton_ordered"),
            "qty_ordered": int(r["qty_ordered"]), "po_number": r.get("po_number"),
            "po_line": r.get("po_line"), "supplier": r.get("supplier"),
            "operator_id": r.get("operator_id"), "captured_at": r.get("captured_at")}


def _resolve_inputs(request, subject_id):
    """Find each input's bytes. Order: data/input/<ref>, repo/<ref>,
    data/input/<subject_id>/receiving/<name>. Hash mismatch -> treated as missing."""
    found, missing = [], []
    for inp in request.get("inputs") or []:
        ref = inp.get("ref", "")
        cands = [DATA_INPUT / ref, REPO_ROOT / ref,
                 DATA_INPUT / subject_id / STAGE / Path(ref).name]
        data = next((c.read_bytes() for c in cands if c.exists()), None)
        if data is None:
            missing.append(ref)
        elif inp.get("sha256") and hashlib.sha256(data).hexdigest() != inp["sha256"]:
            missing.append(f"{ref} (sha256 mismatch)")
        else:
            found.append((inp, data))
    return found, missing


def _record_id(request) -> str:
    """Idempotent per the contract: hash of request_id. Resume gets a fresh id."""
    return "RCV-" + hashlib.sha256(request["request_id"].encode()).hexdigest()[:12]


def _captured_at(request, spec):
    for cand, src in (((request.get("context") or {}).get("captured_at"), "case_facts"),
                      (spec.get("captured_at"), "recorded")):
        if cand:
            return cand, src
    return utcnow(), "defaulted_to_produced_at"   # flagged in payload, never silent


def _refs_for(result, ref_of):
    out = []
    for e in result.evidence:
        r = ref_of.get(e.image_id) if e.image_id else None
        if r and r not in out:
            out.append(r)
    return out or list(ref_of.values())


def _identity_check(by, ref_of, spec):
    parts = [by[k] for k in ("sku_identity", "colour", "variant")
             if k in by and by[k].verdict != "NOT_APPLICABLE"]
    exp = spec["sku"] + (f" ({spec['product_title']})" if spec.get("product_title") else "")
    fails = [p for p in parts if p.verdict == "FAIL"]
    uns = [p for p in parts if p.verdict == "UNCERTAIN"]
    if fails:
        p = fails[0]
        return check("identity_match", "FAIL", p.confidence, expected=exp, observed="no",
                     detail=p.detail, evidence_refs=_refs_for(p, ref_of))
    if uns:
        p = uns[0]
        return check("identity_match", "UNCERTAIN", p.confidence, expected=exp, observed="uncertain",
                     detail=p.detail, evidence_refs=_refs_for(p, ref_of),
                     uncertain_reason=REASON_MAP.get(p.uncertainty_reason, "insufficient_evidence"))
    p = parts[0]
    return check("identity_match", "PASS", p.confidence, expected=exp, observed="yes",
                 detail=p.detail, evidence_refs=_refs_for(p, ref_of))


def _direct_check(key, r, ref_of, expected):
    sv = r.summary_value
    if key in ("carton_damage", "unit_damage"):
        observed = DAMAGE_VOCAB.get(sv, sv) if sv else "uncertain"
    else:
        observed = sv if sv is not None else ("uncertain" if r.verdict == "UNCERTAIN" else None)
    kw = dict(expected=expected, observed=observed, detail=r.detail,
              evidence_refs=_refs_for(r, ref_of))
    if r.verdict == "UNCERTAIN":
        kw["uncertain_reason"] = REASON_MAP.get(r.uncertainty_reason, "insufficient_evidence")
    return check(key, r.verdict, r.confidence, **kw)


def _quality_flags_check(by, ref_of, flags):
    contributors = [by[k] for k in ("colour", "variant", "missing_components", "other_quality")
                    if k in by and by[k].verdict != "NOT_APPLICABLE"]
    refs = _refs_for(contributors[0], ref_of) if contributors else list(ref_of.values())
    fails = [c for c in contributors if c.verdict == "FAIL"]
    uns = [c for c in contributors if c.verdict == "UNCERTAIN"]
    if fails:
        return check("quality_flags", "FAIL", fails[0].confidence, expected=[], observed=flags,
                     detail="; ".join(c.detail for c in fails), evidence_refs=refs)
    if uns:
        return check("quality_flags", "UNCERTAIN", uns[0].confidence, expected=[], observed=[],
                     detail=f"flags not fully verifiable: {uns[0].detail}", evidence_refs=refs,
                     uncertain_reason=REASON_MAP.get(uns[0].uncertainty_reason, "insufficient_evidence"))
    return check("quality_flags", "PASS", 0.7, expected=[], observed=[],
                 detail="no quality flags raised across applicable checks", evidence_refs=refs)


def _contract_checks(by, ref_of, spec, summary):
    out = [_identity_check(by, ref_of, spec)]
    for key, exp in (("carton_count", spec.get("cartons_ordered")),
                     ("quantity", spec["qty_ordered"]),
                     ("carton_damage", "none"), ("unit_damage", "none")):
        r = by.get(key)
        if r and r.verdict != "NOT_APPLICABLE":          # N/A -> omitted, per contract
            out.append(_direct_check(key, r, ref_of, exp))
    out.append(_quality_flags_check(by, ref_of, summary["quality_flags"]))
    return out


def _gate_rejected_checks(refs):
    detail = "every capture was rejected by the deterministic image-quality gate; nothing could be verified"
    return [check(k, "UNCERTAIN", None, expected=e, observed=o, detail=detail,
                  evidence_refs=refs, uncertain_reason="poor_image")
            for k, e, o in (("identity_match", None, "uncertain"), ("carton_count", None, "uncertain"),
                            ("quantity", None, "uncertain"), ("carton_damage", "none", "uncertain"),
                            ("unit_damage", "none", "uncertain"))] + [
        check("quality_flags", "UNCERTAIN", None, expected=[], observed=[],
              detail="image quality prevents verifying the absence of quality flags",
              evidence_refs=refs, uncertain_reason="poor_image")]


def _model_info(stats):
    return {"name": "gemini",
            "version": (stats["model_ids"][0] if stats["model_ids"] else CFG.gemini_model),
            "provider": "google", "prompt_version": "observe_carton@v2",
            "calls": stats["calls"], "cost_usd": None}   # free tier: cost honestly null


def handle(request: dict) -> dict:
    s = request["subject"]
    unit, source = _lookup(s["subject_id"], s["org_id"])        # tenancy -> 404 path
    spec = _spec_of(unit, source)

    found, missing = _resolve_inputs(request, s["subject_id"])
    if not found:
        return pending_output(request, code="upstream_missing", agent_id=AGENT_ID,
                              message=f"no resolvable captures for {s['subject_id']} "
                                      f"(missing: {', '.join(missing) or 'no inputs supplied'})")

    inputs_list, images, ref_of = [], [], {}
    for i, (inp, raw) in enumerate(found):
        sha = hashlib.sha256(raw).hexdigest()
        inputs_list.append({"ref": inp["ref"], "sha256": sha, "kind": "image"})
        images.append((inp["ref"], raw))
        ref_of[f"img_{i+1}"] = inp["ref"]

    t0 = time.time()
    provs, stats, errors = run_engine(images)
    usable = [p for p in provs if (p.quality or {}).get("verdict") != "REJECTED"]

    if not usable and errors:
        return pending_output(request, code="model_error", agent_id=AGENT_ID,
                              message=f"vision extraction failed for every usable capture: {errors[0][1]}")

    if not usable:
        contract, summary = _gate_rejected_checks(list(ref_of.values())), None
        payload = {"granular_checks": [],
                   "photo_quality": {p.image_id: p.quality for p in provs if p.quality},
                   "model_notes": {"vlm_calls": 0, "rejected_by_gate": len(provs)}}
    else:
        from .core.checks import CHECKS              # registry import kept off the fail-open path
        from .core.summary import build_receiving_summary
        po = POLineItem(sku=spec["sku"], asin=spec.get("asin"), product_title=spec.get("product_title"),
                         spec_colour=spec.get("spec_colour"), spec_variant=spec.get("spec_variant"),
                         spec_components=spec.get("spec_components"),
                         cartons_ordered=spec.get("cartons_ordered"),
                         units_per_carton_ordered=spec.get("units_per_carton_ordered"),
                         qty_ordered=spec["qty_ordered"])
        ctx = CheckContext(po=po, observations=usable,
                           model_version=f"gemini:{stats['model_ids'][0] if stats['model_ids'] else CFG.gemini_model}")
        ours = [fn(ctx) for fn in CHECKS.values()]
        by = {r.check_key: r for r in ours}
        summary = build_receiving_summary(ours, po)
        contract = _contract_checks(by, ref_of, spec, summary)
        payload = {"supplier": spec.get("supplier"), "qty_ordered": spec["qty_ordered"],
                   "qty_received": summary["qty_received"],
                   "shortfall_units": (spec["qty_ordered"] - int(summary["qty_received"]))
                                      if summary["qty_received"].isdigit() else None,
                   "quality_flags": summary["quality_flags"], "receiving_summary": summary,
                   "granular_checks": [r.model_dump() for r in ours],
                   "photo_quality": {p.image_id: p.quality for p in provs if p.quality},
                   "model_notes": {"vlm_calls": stats["calls"], "cached_extractions": stats["cached"],
                                   "rejected_by_gate": stats["rejected"], "per_image_models": stats["model_ids"]},
                   "extraction_errors": [f"{i}: {m}" for i, m in errors] or None}

    verdict = rollup(contract)
    outcome = {"PASS": "accept", "FAIL": "accept_with_exceptions", "UNCERTAIN": "pending_review"}[verdict]
    failed = [c["check_key"] for c in contract if c["verdict"] == "FAIL"]
    unsure = [c["check_key"] for c in contract if c["verdict"] == "UNCERTAIN"]
    reason = ("all checks passed" if not (failed or unsure) else
              "; ".join([f"{k}=FAIL" for k in failed] + [f"{k}=UNCERTAIN" for k in unsure]))

    cap, cap_src = _captured_at(request, spec)
    payload["captured_at_source"] = cap_src
    payload["sample_record_id"] = unit.get("record_id") if source == "sample" else None

    confs = [c.get("confidence") for c in contract if c.get("confidence") is not None]
    record = build_record(
        request, agent_id=AGENT_ID, record_id=_record_id(request), captured_at=cap,
        checks=contract, outcome=outcome, reason=reason, model=_model_info(stats),
        unit_scope="po_line",
        refs={"po_number": spec.get("po_number"), "po_line": spec.get("po_line"),
              "sku": spec["sku"], "asin": spec.get("asin")},
        operator_id=spec.get("operator_id"), inputs=inputs_list, payload=payload,
        latency_ms=int((time.time() - t0) * 1000),
        confidence=round(sum(confs) / len(confs), 2) if confs else None)
    return build_output(record)


app = make_app(STAGE, handle, version=VERSION)