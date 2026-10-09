from ..models import CheckContext, CheckResult, EvidenceItem
from .base import absence, cited_latency

def _base(token: str) -> str:
    """'candle x3' -> 'candle', 'mug x2' -> 'mug', 'gift box' -> 'gift box'."""
    return token.lower().split(" x")[0].strip()

def _match(expected_base: str, visible: str) -> bool:
    v = visible.lower()
    return expected_base == v or expected_base in v or v in expected_base

def run(ctx: CheckContext) -> CheckResult:
    spec = ctx.po.spec_components
    if not spec:
        return CheckResult(check_key="missing_components", verdict="NOT_APPLICABLE",
                           confidence=1.0, detail="PO does not enumerate components.",
                           evidence=[], model_version=ctx.model_version, latency_ms=0)

    open_obs = [p for p in ctx.observations if p.observation.contents_open_for_inspection]
    if not open_obs:
        # Sealed packaging is NOT evidence of missing components.
        return CheckResult(check_key="missing_components", verdict="UNCERTAIN",
                           confidence=0.3,
                           detail=("Packaging not opened in any photograph; internal "
                                   "components cannot be verified. Not visible is not missing."),
                           evidence=absence("No photograph shows opened packaging."),
                           model_version=ctx.model_version,
                           uncertainty_reason="INSUFFICIENT_EVIDENCE",
                           summary_value="uncertain",
                           latency_ms=cited_latency(ctx, [p.image_id for p in ctx.observations]))

    present = {}   # visible component name -> first image_id it was seen in
    for p in open_obs:
        for comp in (p.observation.visible_components or []):
            present.setdefault(comp, p.image_id)

    missing = [c for c in spec if not any(_match(_base(c), v) for v in present)]
    found_ev = [EvidenceItem(type="visual_component", image_id=iid,
                             description=f"Component visible: '{comp}'.", strength=0.7)
                for comp, iid in present.items()]

    if not missing:
        return CheckResult(check_key="missing_components", verdict="PASS", confidence=0.8,
                           detail=(f"All {len(spec)} expected components visible in opened "
                                   f"packaging: {', '.join(spec)}."),
                           evidence=found_ev, model_version=ctx.model_version,
                           summary_value="none_missing",
                           latency_ms=cited_latency(ctx, list(present.values())))

    if any(p.observation.full_contents_visible for p in open_obs):
        missing_ev = [EvidenceItem(type="absence",
                                   description=f"'{m}' not observed in opened contents.",
                                   strength=0.75)
                      for m in missing]
        return CheckResult(check_key="missing_components", verdict="FAIL", confidence=0.75,
                           detail=(f"Opened packaging with full contents visible; expected "
                                   f"component(s) not observed: {', '.join(missing)}."),
                           evidence=found_ev + missing_ev,
                           model_version=ctx.model_version,
                           summary_value="missing",
                           latency_ms=cited_latency(ctx, [p.image_id for p in open_obs]))

    return CheckResult(check_key="missing_components", verdict="UNCERTAIN", confidence=0.4,
                       detail=(f"Packaging opened but contents only partially visible; "
                               f"cannot confirm presence of: {', '.join(missing)}."),
                       evidence=found_ev, model_version=ctx.model_version,
                       uncertainty_reason="OCCLUSION", summary_value="uncertain",
                       latency_ms=cited_latency(ctx, [p.image_id for p in open_obs]))