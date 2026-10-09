"""Deterministic port of upstream rules.ts with membership/quality corrections."""
import re
from shared.utils.records import check, rollup
from .rulepacks.organizer import CHECKS, applicable


def normalize_label(value):
    # Only surrounding whitespace and letter case. Never delete punctuation,
    # internal spaces, or characters, and never accept a substring as identity.
    return value.strip().upper()


def evaluate(criteria, batch, material=None):
    checks, annotations = [], []
    definitions = [*CHECKS, *[(f"handling_mark_{i + 1}", "handling_mark:" + mark, True, "4.2")
                            for i, mark in enumerate(criteria["required_handling_marks"])]]
    for key, field, expected, clause in definitions:
        if not applicable(field, criteria):
            annotations.append({"check_key": key, "state": "NOT_APPLICABLE", "clause": clause})
            continue
        observations = [o for o in batch["observations"] if o["field"] == field]
        refs = sorted({o["ref"] for o in observations})
        verdict, reason, detail = "UNCERTAIN", "insufficient_evidence", "Required observation is missing."
        if observations:
            values = [normalize_label(o["value"]) if field == "label_text" and o["value"] is not None
                      else o["value"] for o in observations]
            if len(set(values)) > 1:
                reason, detail = "conflicting_evidence", "Authorized images disagree; no observation takes precedence."
            elif any(batch["quality"].get(o["photo_index"]) is not True for o in observations):
                reason, detail = "poor_image", "Missing or unusable photo quality prevents verification."
            elif any(o["confidence"] < 0.8 or not o["detail"].strip() for o in observations) or values[0] in (None, "unknown"):
                detail = "Observation is incomplete or below the confidence threshold."
            elif field == "label_text":
                expected = criteria["expected_fnsku"]
                value = values[0]
                if not re.fullmatch(r"[A-Z0-9]{1,64}", value):
                    detail = "Identifier contains ambiguous formatting."
                elif len(value) < len(expected) and value in expected:
                    detail = "Partial identifier cannot establish identity."
                else:
                    verdict = "PASS" if value == expected else "FAIL"
                    detail = "Exact normalized identifier comparison."
            else:
                verdict = "PASS" if values[0] == expected else "FAIL"
                detail = f"Factual observation compared with requirement {field}."
        checks.append(check(key, verdict, None, expected=expected, observed=[o["value"] for o in observations],
                            detail=f"Organizer implementation clause {clause}: {detail}", evidence_refs=refs,
                            uncertain_reason=reason))
    if criteria["requires_polybag"]:
        if material is None:
            checks.append(check("bag_thickness_material", "UNCERTAIN", None,
                                detail="NOT_VERIFIABLE from photos; registered physical attestation required.",
                                uncertain_reason="insufficient_evidence"))
            annotations.append({"check_key": "bag_thickness_material", "state": "NOT_VERIFIABLE", "clause": "2.4"})
        else:
            ok = material["thickness_mil"] >= 1.5 and material["durable"]
            checks.append(check("bag_thickness_material", "PASS" if ok else "FAIL", None,
                                expected={"minimum_thickness_mil": 1.5, "durable": True},
                                observed={k: material[k] for k in ("thickness_mil", "durable")},
                                detail="Registered operator attestation; not a visual measurement.",
                                evidence_refs=[material["ref"]]))
    else:
        annotations.append({"check_key": "bag_thickness_material", "state": "NOT_APPLICABLE", "clause": "2.4"})
    return checks, annotations, rollup(checks)
