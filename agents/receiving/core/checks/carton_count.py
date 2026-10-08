from ..models import CheckContext, CheckResult, EvidenceItem
from .base import absence, cited_latency

def run(ctx: CheckContext) -> CheckResult:
    exp = ctx.po.cartons_ordered
    if exp is None:
        return CheckResult(check_key="carton_count", verdict="NOT_APPLICABLE", confidence=1.0,
                           detail="PO does not specify a carton count.", evidence=[],
                           model_version=ctx.model_version)
    counts = [(p, p.observation.cartons_visible) for p in ctx.observations
              if p.observation.cartons_visible]
    if not counts:
        return CheckResult(check_key="carton_count", verdict="UNCERTAIN", confidence=0.3,
                           detail="No cartons visible in any photograph.",
                           evidence=absence("No carton count evidence."),
                           model_version=ctx.model_version, uncertainty_reason="INSUFFICIENT_EVIDENCE",
                           summary_value="uncertain",
                           latency_ms=cited_latency(ctx, [p.image_id for p in ctx.observations]))
    # Multiple photos may show the same cartons; the max is the safest aggregate.
    best, n = max(counts, key=lambda x: x[1])
    ev = [EvidenceItem(type="visual_count", image_id=best.image_id,
                       description=f"{n} carton(s) visible in this photograph.", strength=0.6)]
    if n == exp:
        return CheckResult(check_key="carton_count", verdict="PASS", confidence=0.6,
                           detail=f"Expected {exp} cartons, {n} visible.",
                           evidence=ev, model_version=ctx.model_version,
                           summary_value=str(n), latency_ms=cited_latency(ctx, [best.image_id]))
    if n > exp:
        return CheckResult(check_key="carton_count", verdict="FAIL", confidence=0.7,
                           detail=f"Expected {exp} cartons but {n} are visible.",
                           evidence=ev, model_version=ctx.model_version,
                           summary_value=str(n), latency_ms=cited_latency(ctx, [best.image_id]))
    return CheckResult(check_key="carton_count", verdict="UNCERTAIN", confidence=0.4,
                       detail=(f"{n} carton(s) visible; photographs may not show the complete "
                               f"delivery (expected {exp})."),
                       evidence=ev, model_version=ctx.model_version,
                       uncertainty_reason="OCCLUSION", summary_value="uncertain",
                       latency_ms=cited_latency(ctx, [best.image_id]))