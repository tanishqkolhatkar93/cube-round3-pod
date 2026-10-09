"""Pure evidence/reference checks. No I/O, model calls or guessed resale policy."""

from .domain import (
    Assessment, Capture, CompletenessResult, ConditionResult, Disposition,
    DispositionResult, IdentityResult, ObservationPlaceholder, ReviewState,
    ValidationError, Verdict, DecisionReference,
)
from .validation import validate_capture, validate_decision_reference
from .observations import ObservationBatch, validate_batch


def _citations(items):
    return tuple(sorted({ref for item in items for ref in item.evidence_refs}))


def _identity(reference, batch):
    # Packaging identifiers, product names and general resemblance are not item identity.
    expected = {"sku": reference.ordered_sku, "asin": reference.ordered_asin}
    entries = [i for i in batch.identity if i.field in expected]
    product_evidence = {i.evidence_id for i in batch.images if i.image_role == "returned_product"}
    if (not entries or any(c.startswith("identity:") for c in batch.conflicts)
            or any(i.state != "observed" or len(i.values) != 1 or i.limitations
                   or not set(i.evidence_refs).issubset(product_evidence) for i in entries)):
        return IdentityResult(("identity_evidence_ambiguous_or_not_product_bound",), evidence=_citations(entries))
    if any(i.values[0] != expected[i.field] and i.values[0].casefold() == expected[i.field].casefold() for i in entries):
        return IdentityResult(("identifier_case_policy_unresolved",), evidence=_citations(entries))
    matches = {i.values[0] == expected[i.field] for i in entries}
    if len(matches) != 1:
        return IdentityResult(("identity_identifiers_disagree",), evidence=_citations(entries))
    match = matches.pop()
    return IdentityResult(("exact_order_identifier_match" if match else "explicit_order_identifier_mismatch",),
                          Verdict.PASS if match else Verdict.FAIL, _citations(entries))


def _completeness(reference, batch, identity):
    names = tuple(c.name for c in reference.components)
    if identity.verdict != Verdict.PASS:
        return CompletenessResult(names, ("expected_product_identity_not_established",))
    if not reference.parts_list_complete or not names:
        return CompletenessResult(names, ("complete_parts_reference_required",))
    missing, unknown, evidence = [], [], set()
    product_evidence = {i.evidence_id for i in batch.images if i.image_role == "returned_product"}
    for component in reference.components:
        entries = [c for c in batch.components if c.component == component.name]
        if (not entries or "component:" + component.name in batch.conflicts
                or component.quantity is None
                or any(c.presence in {"unknown", "conflicting"} or c.visibility != "visible"
                       or not c.quantity_reliable or not set(c.evidence_refs).issubset(product_evidence) for c in entries)):
            unknown.append(component.name)
            continue
        # Do not sum counts across photos: two views may depict the same accessory.
        quantities = {c.quantity for c in entries}
        if len(quantities) != 1:
            unknown.append(component.name)
        elif all(c.presence == "absent" and c.absence_basis == "full_expected_area_visible" for c in entries):
            missing.append(component.name)
            evidence.update(_citations(entries))
        elif all(c.presence == "present" and not c.limitations for c in entries) and next(iter(quantities)) >= component.quantity:
            evidence.update(_citations(entries))
        else:
            # A smaller visible count does not prove the rest are absent off-camera.
            unknown.append(component.name)
    verdict = Verdict.FAIL if missing else Verdict.UNCERTAIN if unknown else Verdict.PASS
    reason = "required_components_absent" if missing else "component_evidence_incomplete" if unknown else "required_components_present"
    return CompletenessResult(tuple(unknown), (reason,), verdict, tuple(missing), tuple(sorted(evidence)))


def assess(capture: Capture, observation: ObservationPlaceholder | ObservationBatch,
           reference: DecisionReference | None = None) -> Assessment:
    validate_capture(capture)
    if reference is not None:
        validate_decision_reference(capture, reference)
    if isinstance(observation, ObservationBatch):
        validate_batch(capture, observation)
        reason = "visual_observations_are_not_business_verdicts"
        extra = ("fixture_observations_only",) if observation.provider_mode == "fixture" else ()
        extra += tuple("conflict:" + c for c in observation.conflicts)
        extra += ("observation_limitations_present",) if observation.limitations else ()
    elif isinstance(observation, ObservationPlaceholder):
        reason, extra = observation.reason, ()
    else:
        raise ValidationError("validated observations or unavailable placeholder required")
    identity = IdentityResult((reason, "catalogue_reference_unverified"))
    completeness = CompletenessResult(
        tuple(c.raw for c in capture.reference.components),
        (reason, "parts_reference_unverified"),
    )
    condition_reasons = [reason, "condition_policy_unavailable", "category_specific_condition_requirements_unresolved",
                         "nonvisual_condition_evidence_unavailable"]
    condition_evidence = ()
    if isinstance(observation, ObservationBatch) and observation.provider_mode == "real":
        condition_evidence = _citations(observation.condition)
        if any(c.startswith("condition:") for c in observation.conflicts):
            condition_reasons.append("conflicting_condition_observations")
    condition = ConditionResult(tuple(condition_reasons), condition_evidence)
    if reference is not None:
        unavailable = (not isinstance(observation, ObservationBatch) or observation.provider_mode != "real"
                       or not observation.images or any(i.availability != "available" for i in observation.images))
        if reference.reference_status == "synthetic_demo" or unavailable or observation.limitations:
            identity = IdentityResult(("synthetic_reference_not_real_catalogue" if reference.reference_status == "synthetic_demo"
                                       else "genuine_unambiguous_observations_required",))
            completeness = CompletenessResult(tuple(c.name for c in reference.components), identity.reasons)
        else:
            identity = _identity(reference, observation)
            completeness = _completeness(reference, observation, identity)
    blockers = capture.blockers
    if isinstance(observation, ObservationBatch) and observation.provider_mode == "real" and observation.images:
        if all(i.availability == "available" for i in observation.images):
            blockers = tuple(b for b in blockers if b != "image_evidence_unavailable")
    if reference is not None:
        blockers = tuple(b for b in blockers if b not in {"catalogue_reference_unverified", "parts_reference_missing",
                                                         "component_quantities_unverified"})
    reasons = tuple(dict.fromkeys((*blockers, reason, *extra, *identity.reasons, *completeness.reasons,
                                  *condition.reasons, "disposition_policy_unavailable")))
    disposition = DispositionResult(Disposition.PENDING_REVIEW, reasons)
    return Assessment(identity, completeness, condition, disposition, ReviewState(reasons), observation, reference)
