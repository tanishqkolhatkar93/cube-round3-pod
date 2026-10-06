from ..models import CheckContext, CheckResult, EvidenceItem
from .base import absence, cited_latency

MIN_DAMAGE_CONF = 0.5

def run(ctx: CheckContext) -> CheckResult:
    found = []
    for p in ctx.observations:
        for d in p.observation.damages:
            if d.target == "carton" and d.confidence >= MIN_DAMAGE_CONF:
                found.append((p, d))
    if found:
        ev = [EvidenceItem(type="visual_damage", image_id=p.image_id,
                           description=(f"{d.damage_type.replace('_', ' ')} at {d.location} "
                                        f"({d.severity})."), strength=d.confidence)
              for p, d in found]
        primary = max(found, key=lambda x: x[1].confidence)[1]
        types = ", ".join(sorted({d.damage_type for _, d in found}))
        return CheckResult(check_key="carton_damage", verdict="FAIL",
                           confidence=max(d.confidence for _, d in found),
                           detail=f"Visible carton damage: {types}.",
                           evidence=ev, model_version=ctx.model_version,
                           summary_value=primary.damage_type,
                           latency_ms=cited_latency(ctx, [e.image_id for e in ev]))
    return CheckResult(check_key="carton_damage", verdict="PASS", confidence=0.7,
                       detail=f"No visible carton damage across {len(ctx.observations)} image(s).",
                       evidence=absence("No visible carton damage in any supplied image.", 0.7),
                       model_version=ctx.model_version, summary_value="none",
                       latency_ms=cited_latency(ctx, [p.image_id for p in ctx.observations]))