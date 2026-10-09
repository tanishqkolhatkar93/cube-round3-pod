from ..models import CheckContext, CheckResult, EvidenceItem
from .base import absence, cited_latency

RELIABLE = 0.7

def run(ctx: CheckContext) -> CheckResult:
    exp = ctx.po.units_per_carton_ordered
    if exp is None:
        return CheckResult(check_key="units_per_carton", verdict="NOT_APPLICABLE",
                           confidence=1.0, detail="PO does not specify units per carton.",
                           evidence=[], model_version=ctx.model_version, latency_ms=0)

    # 1. One carton photographed with full contents visible -> direct count.
    for p in ctx.observations:
        o = p.observation
        if (o.cartons_visible == 1 and o.full_contents_visible
                and o.visible_unit_count is not None
                and (o.count_confidence or 0.0) >= RELIABLE):
            n = o.visible_unit_count
            ev = [EvidenceItem(type="visual_count", image_id=p.image_id,
                               description=(f"Single carton, full contents visible: "
                                            f"{n} units."),
                               strength=o.count_confidence or 0.7)]
            if n == exp:
                return CheckResult(check_key="units_per_carton", verdict="PASS",
                                   confidence=0.75,
                                   detail=f"Expected {exp} units per carton; counted {n}.",
                                   evidence=ev, model_version=ctx.model_version,
                                   summary_value=str(n),
                                   latency_ms=cited_latency(ctx, [p.image_id]))
            return CheckResult(check_key="units_per_carton", verdict="FAIL",
                               confidence=0.7,
                               detail=f"Expected {exp} units per carton but counted {n}.",
                               evidence=ev, model_version=ctx.model_version,
                               summary_value=str(n),
                               latency_ms=cited_latency(ctx, [p.image_id]))

    # 2. Derived: whole-shipment count divided by visible cartons (must divide evenly).
    reliable = [p for p in ctx.observations
                if p.observation.full_contents_visible
                and p.observation.visible_unit_count is not None
                and (p.observation.count_confidence or 0.0) >= RELIABLE]
    if reliable:
        best = max(reliable, key=lambda p: p.observation.count_confidence or 0.0)
        total = best.observation.visible_unit_count
        cartons = best.observation.cartons_visible or max(
            (p.observation.cartons_visible for p in ctx.observations), default=0)
        if cartons > 0 and total % cartons == 0:
            n = total // cartons
            ev = [EvidenceItem(type="derived_count", image_id=best.image_id,
                               description=(f"Derived: {total} units across {cartons} "
                                            f"cartons = {n} per carton."), strength=0.55)]
            if n == exp:
                return CheckResult(check_key="units_per_carton", verdict="PASS",
                                   confidence=0.55,
                                   detail=(f"Derived {n} units per carton "
                                           f"({total}/{cartons}), matches expected {exp}."),
                                   evidence=ev, model_version=ctx.model_version,
                                   summary_value=str(n),
                                   latency_ms=cited_latency(ctx, [best.image_id]))
            return CheckResult(check_key="units_per_carton", verdict="UNCERTAIN",
                               confidence=0.45,
                               detail=(f"Derived {n} units per carton ({total}/{cartons}) "
                                       f"but expected {exp}; packing may be uneven — "
                                       "needs human confirmation."),
                               evidence=ev, model_version=ctx.model_version,
                               uncertainty_reason="CONFLICTING_EVIDENCE",
                               summary_value="uncertain",
                               latency_ms=cited_latency(ctx, [best.image_id]))
        return CheckResult(check_key="units_per_carton", verdict="UNCERTAIN", confidence=0.4,
                           detail=("Whole-shipment count does not divide evenly by visible "
                                   "cartons; per-carton count unresolved."),
                           evidence=absence("Per-carton count not resolvable from photographs."),
                           model_version=ctx.model_version,
                           uncertainty_reason="INSUFFICIENT_EVIDENCE",
                           summary_value="uncertain",
                           latency_ms=cited_latency(ctx, [best.image_id]))

    return CheckResult(check_key="units_per_carton", verdict="UNCERTAIN", confidence=0.3,
                       detail="Carton contents not fully visible; per-carton count unverifiable.",
                       evidence=absence("No per-carton count evidence in any image."),
                       model_version=ctx.model_version,
                       uncertainty_reason="INSUFFICIENT_EVIDENCE",
                       summary_value="uncertain",
                       latency_ms=cited_latency(ctx, [p.image_id for p in ctx.observations]))