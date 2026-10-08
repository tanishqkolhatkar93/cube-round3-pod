from ..models import CheckContext, CheckResult, EvidenceItem
from .base import absence, cited_latency

MIN_CONF = 0.5

def run(ctx: CheckContext) -> CheckResult:
    found = []
    for p in ctx.observations:
        for d in p.observation.damages:
            if d.damage_type == "other" and d.confidence >= MIN_CONF:
                found.append((p, d))
    if found:
        ev = [EvidenceItem(type="visual_damage", image_id=p.image_id,
                           description=f"Other visible issue at {d.location} ({d.severity}).",
                           strength=d.confidence) for p, d in found]
        return CheckResult(check_key="other_quality", verdict="FAIL",
                           confidence=max(d.confidence for _, d in found),
                           detail="Other visible quality issue(s) detected.",
                           evidence=ev, model_version=ctx.model_version,
                           summary_value="obvious_defect",
                           latency_ms=cited_latency(ctx, [e.image_id for e in ev]))
    return CheckResult(check_key="other_quality", verdict="PASS", confidence=0.6,
                       detail=(f"No other visible quality issues across "
                               f"{len(ctx.observations)} image(s)."),
                       evidence=absence("No other visible quality issues.", 0.6),
                       model_version=ctx.model_version, summary_value="none",
                       latency_ms=cited_latency(ctx, [p.image_id for p in ctx.observations]))