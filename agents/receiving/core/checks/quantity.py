from ..models import CheckContext, CheckResult, EvidenceItem
from .base import absence, cited_latency

RELIABLE = 0.7  # min count_confidence for a count to be treated as exact

def run(ctx: CheckContext) -> CheckResult:
    exp = ctx.po.qty_ordered

    # 1. Reliable full-contents counts are the observed quantity.
    reliable = [p for p in ctx.observations
                if p.observation.visible_unit_count is not None
                and p.observation.full_contents_visible
                and (p.observation.count_confidence or 0.0) >= RELIABLE]
    if reliable:
        # Conflict detection first: two reliable counts that disagree are a
        # finding, never silently resolved by max/confidence.
        distinct = {p.observation.visible_unit_count for p in reliable}
        if len(distinct) > 1:
            ev = [EvidenceItem(type="visual_count", image_id=p.image_id,
                               description=(f"Full contents visible: "
                                            f"{p.observation.visible_unit_count} units "
                                            f"counted."),
                               strength=p.observation.count_confidence or 0.7)
                  for p in reliable]
            shown = ", ".join(f"{p.observation.visible_unit_count} ({p.image_id})"
                              for p in reliable)
            return CheckResult(check_key="quantity", verdict="UNCERTAIN", confidence=0.4,
                               detail=(f"Reliable counts disagree across images: {shown}; "
                                       f"cannot determine observed quantity against "
                                       f"expected {exp}."),
                               evidence=ev, model_version=ctx.model_version,
                               uncertainty_reason="CONFLICTING_EVIDENCE",
                               summary_value="uncertain",
                               latency_ms=cited_latency(ctx, [p.image_id for p in reliable]))

        best = max(reliable, key=lambda p: p.observation.count_confidence or 0.0)
        n = best.observation.visible_unit_count
        conf = best.observation.count_confidence or 0.7
        ev = [EvidenceItem(type="visual_count", image_id=best.image_id,
                           description=f"{n} units visible; full contents in frame.",
                           strength=conf)]
        if n == exp:
            return CheckResult(check_key="quantity", verdict="PASS", confidence=conf,
                               detail=f"Expected {exp}, observed {exp} (full contents visible).",
                               evidence=ev, model_version=ctx.model_version,
                               latency_ms=cited_latency(ctx, [best.image_id]),
                               summary_value=str(n))
        kind = "short" if n < exp else "overage"
        return CheckResult(check_key="quantity", verdict="FAIL", confidence=conf,
                           detail=f"Expected {exp}, observed {n} ({kind}).",
                           evidence=ev, model_version=ctx.model_version,
                           latency_ms=cited_latency(ctx, [best.image_id]),
                           summary_value=str(n))

    # 2. Partial counts: overage is provable, shortage is not (occlusion).
    partial = [p for p in ctx.observations if p.observation.visible_unit_count is not None]
    if partial:
        best = max(partial, key=lambda p: p.observation.visible_unit_count)
        n = best.observation.visible_unit_count
        ev = [EvidenceItem(type="visual_count", image_id=best.image_id,
                           description=f"{n} units visible; contents not fully visible.",
                           strength=0.5)]
        if n > exp:
            return CheckResult(check_key="quantity", verdict="FAIL", confidence=0.7,
                               detail=f"Expected {exp}, at least {n} units visible (overage).",
                               evidence=ev, model_version=ctx.model_version,
                               latency_ms=cited_latency(ctx, [best.image_id]),
                               summary_value=str(n))
        return CheckResult(check_key="quantity", verdict="UNCERTAIN", confidence=0.4,
                           detail=(f"{n} units visible but full contents not visible; "
                                   f"cannot verify expected {exp}."),
                           evidence=ev, model_version=ctx.model_version,
                           uncertainty_reason="OCCLUSION",
                           latency_ms=cited_latency(ctx, [best.image_id]),
                           summary_value="uncertain")

    # 3. Printed quantity only: documentation, not proof of contents.
    printed = [p for p in ctx.observations if p.observation.printed_quantity is not None]
    if printed:
        p = printed[0]
        q = p.observation.printed_quantity
        ev = [EvidenceItem(type="printed_text", image_id=p.image_id,
                           description=f"Carton label states quantity {q}.", strength=0.6)]
        if q == exp:
            return CheckResult(check_key="quantity", verdict="UNCERTAIN", confidence=0.4,
                               detail=(f"Carton label states {q} (matches expected {exp}), "
                                       "but contents are not visually verifiable."),
                               evidence=ev, model_version=ctx.model_version,
                               uncertainty_reason="INSUFFICIENT_EVIDENCE",
                               latency_ms=cited_latency(ctx, [p.image_id]),
                               summary_value="uncertain")
        return CheckResult(check_key="quantity", verdict="UNCERTAIN", confidence=0.4,
                           detail=(f"Carton label states {q} but PO expects {exp}; "
                                   "contents not visible to resolve the discrepancy."),
                           evidence=ev, model_version=ctx.model_version,
                           uncertainty_reason="CONFLICTING_EVIDENCE",
                           latency_ms=cited_latency(ctx, [p.image_id]),
                           summary_value="uncertain")

    return CheckResult(check_key="quantity", verdict="UNCERTAIN", confidence=0.3,
                       detail="No count evidence available (no visible units, no printed quantity).",
                       evidence=absence("No quantity evidence in any image."),
                       model_version=ctx.model_version, uncertainty_reason="INSUFFICIENT_EVIDENCE",
                       latency_ms=cited_latency(ctx, [p.image_id for p in ctx.observations]),
                       summary_value="uncertain")