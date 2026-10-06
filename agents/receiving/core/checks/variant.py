from ..models import CheckContext, CheckResult, EvidenceItem
from .base import absence, cited_latency

def _m(expected: str, observed: str) -> bool:
    e, o = expected.strip().lower(), observed.strip().lower()
    return e == o or e in o or o in e

def _na(v) -> bool:
    return v is None or v.strip().lower() in ("", "n/a", "na")

def run(ctx: CheckContext) -> CheckResult:
    exp = ctx.po.spec_variant
    if _na(exp):
        return CheckResult(check_key="variant", verdict="NOT_APPLICABLE", confidence=1.0,
                           detail="PO spec has no variant requirement.", evidence=[],
                           model_version=ctx.model_version)

    # Non-colour variants (size/model/version) are only reliably provable from
    # printed text; visual "looks like 750ml" is not evidence.
    labels = [(p, p.observation.label_variant_text) for p in ctx.observations
              if p.observation.label_variant_text]
    if labels:
        match = [(p, t) for p, t in labels if _m(exp, t)]
        if match:
            p, t = match[0]
            return CheckResult(check_key="variant", verdict="PASS", confidence=0.85,
                               detail=f"Expected variant '{exp}'; label reads '{t}'.",
                               evidence=[EvidenceItem(type="label_text", image_id=p.image_id,
                                                      quote=t, description=f"Variant text '{t}' on label.",
                                                      strength=0.85)],
                               model_version=ctx.model_version,
                               latency_ms=cited_latency(ctx, [p.image_id]))
        p, t = labels[0]
        return CheckResult(check_key="variant", verdict="FAIL", confidence=0.8,
                           detail=f"Expected variant '{exp}' but label reads '{t}'.",
                           evidence=[EvidenceItem(type="label_text", image_id=p.image_id,
                                                  quote=t, description=f"Label states variant '{t}'.",
                                                  strength=0.8)],
                           model_version=ctx.model_version,
                           latency_ms=cited_latency(ctx, [p.image_id]))

    return CheckResult(check_key="variant", verdict="UNCERTAIN", confidence=0.3,
                       detail=f"No readable variant text; cannot verify variant '{exp}'.",
                       evidence=absence("No variant label evidence in any image."),
                       model_version=ctx.model_version, uncertainty_reason="INSUFFICIENT_EVIDENCE",
                       latency_ms=cited_latency(ctx, [p.image_id for p in ctx.observations]))