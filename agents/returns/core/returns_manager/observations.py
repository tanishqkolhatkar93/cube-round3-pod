"""Strict internal observation contract; not an official wire schema or policy.

Fixture evidence is explicitly synthetic. Genuine evidence descriptors are supplied
by the image boundary, never created from provider assertions.
"""

import json
import math
from dataclasses import asdict, dataclass

from .domain import Capture, TenantContext, TenantMismatch, ValidationError, identifier, validate_unicode_scalars
from .validation import validate_capture


@dataclass(frozen=True)
class ObservationScope:
    tenant: TenantContext
    unit_id: str
    record_id: str

    @classmethod
    def from_capture(cls, capture: Capture):
        return cls(capture.tenant, capture.unit.unit_id, capture.record_id)


@dataclass(frozen=True)
class ImageDescriptor:
    scope: ObservationScope
    image_id: str
    evidence_id: str
    reference: str
    image_role: str
    source_relationship: str
    kind: str
    availability: str
    sha256: str | None = None


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    provider_name: str
    mode: str
    model_version: str | None = None
    request_id: str | None = None
    latency_ms: float | None = None
    token_usage: int | None = None


@dataclass(frozen=True)
class IdentityObservation:
    field: str
    state: str
    values: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class ComponentObservation:
    component: str
    presence: str
    visibility: str
    quantity: int | None
    quantity_reliable: bool
    absence_basis: str | None
    evidence_refs: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class ConditionObservation:
    feature: str
    state: str
    description: str | None
    evidence_refs: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class ObservationBatch:
    scope: ObservationScope
    images: tuple[ImageDescriptor, ...]
    provider_name: str
    provider_mode: str
    identity: tuple[IdentityObservation, ...]
    components: tuple[ComponentObservation, ...]
    condition: tuple[ConditionObservation, ...]
    limitations: tuple[str, ...]
    conflicts: tuple[str, ...]


IDENTITY_FIELDS = frozenset({"brand", "model", "sku", "asin", "model_number", "product_name",
                             "markings", "packaging_identifiers", "physical_characteristics", "ocr_text"})
CONDITION_FEATURES = frozenset({"scratches", "scuffs", "cracks", "dents", "deformation", "stains",
                                "tears", "wear", "discoloration", "broken_parts", "packaging_damage",
                                "signs_of_use", "surface_condition"})
STATES = frozenset({"observed", "not_observed", "not_visible", "unknown", "conflicting"})
VISIBILITY = frozenset({"visible", "partial", "occluded", "not_visible", "unknown", "conflicting"})
ROLES = frozenset({"returned_product", "returned_packaging"})


class EvidenceMismatch(ValidationError):
    pass


def object_fields(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise ValidationError("missing or unexpected observation fields")


def sequence(value):
    if type(value) is not list or len(value) > 200:
        raise ValidationError("bounded observation list required")
    return value


def text(value):
    identifier(value, "observation text")
    if len(value) > 8192:
        raise ValidationError("observation text too long")
    return value


def strings(value):
    return tuple(text(item) for item in sequence(value))


def choice(value, choices):
    if type(value) is not str or value not in choices:
        raise ValidationError("unsupported observation value")
    return value


def validate_images(capture, images, mode):
    scope = ObservationScope.from_capture(capture)
    if type(images) is not tuple or len(images) > 20:
        raise ValidationError("at most 20 image descriptors required")
    image_ids, evidence_ids, references = set(), set(), set()
    for image in images:
        if not isinstance(image, ImageDescriptor):
            raise ValidationError("ImageDescriptor required")
        if image.scope != scope:
            raise TenantMismatch("image organization/client/unit/record mismatch")
        for value in (image.image_id, image.evidence_id, image.reference):
            text(value)
        if image.reference not in {i.reference for i in capture.images}:
            raise EvidenceMismatch("image reference does not belong to capture")
        if image.image_id in image_ids or image.evidence_id in evidence_ids or image.reference in references:
            raise ValidationError("duplicate image identity/reference")
        image_ids.add(image.image_id)
        evidence_ids.add(image.evidence_id)
        references.add(image.reference)
        choice(image.image_role, ROLES)
        if image.source_relationship != "capture_photo_ref":
            raise ValidationError("unsupported source relationship")
        choice(image.kind, {"fixture", "genuine"})
        choice(image.availability, {"fixture_only", "available", "missing", "unreadable", "decoder_unavailable"})
        if image.kind == "fixture":
            if mode != "fixture" or image.availability != "fixture_only" or image.sha256 is not None:
                raise ValidationError("fixture descriptor cannot claim real image evidence")
        else:
            if image.availability == "fixture_only":
                raise ValidationError("genuine descriptor cannot be fixture_only")
            if image.availability == "available":
                if (type(image.sha256) is not str or len(image.sha256) != 64
                        or any(c not in "0123456789abcdef" for c in image.sha256)):
                    raise ValidationError("available image needs actual content digest")
            elif image.sha256 is not None:
                raise ValidationError("unavailable image cannot claim validated content digest")


def validate_response(response):
    if not isinstance(response, ProviderResponse):
        raise ValidationError("ProviderResponse required")
    text(response.provider_name)
    choice(response.mode, {"real", "fixture"})
    if type(response.text) is not str or len(response.text) > 1_000_000:
        raise ValidationError("bounded raw text required")
    validate_unicode_scalars(response.text)
    for value in (response.model_version, response.request_id):
        if value is not None:
            text(value)
    if response.latency_ms is not None:
        try:
            valid_latency = (type(response.latency_ms) in (int, float)
                             and math.isfinite(response.latency_ms) and response.latency_ms >= 0)
        except OverflowError as exc:
            raise ValidationError("invalid actual latency") from exc
        if not valid_latency:
            raise ValidationError("invalid actual latency")
    if response.token_usage is not None and (type(response.token_usage) is not int or response.token_usage < 0):
        raise ValidationError("invalid actual token usage")
    if response.mode == "fixture" and any(v is not None for v in (
        response.model_version, response.request_id, response.latency_ms, response.token_usage
    )):
        raise ValidationError("fixture provider cannot claim model telemetry")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("duplicate JSON key")
        result[key] = value
    return result


def parse_response(capture: Capture, images: tuple[ImageDescriptor, ...], response: ProviderResponse) -> ObservationBatch:
    validate_capture(capture)
    validate_response(response)
    validate_images(capture, images, response.mode)
    if not response.text.strip():
        raise ValidationError("empty provider response")
    try:
        payload = json.loads(response.text, object_pairs_hook=_unique_object,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValidationError("nonfinite JSON")))
    except (ValueError, RecursionError) as exc:
        raise ValidationError("malformed provider JSON") from exc
    object_fields(payload, {"scope", "identity", "components", "condition", "limitations"})
    scope = ObservationScope.from_capture(capture)
    if payload["scope"] != asdict(scope):
        raise TenantMismatch("provider organization/client/unit/record mismatch")
    usable = {image.evidence_id for image in images if image.availability in {"available", "fixture_only"}}

    def refs(value, required=False, conflicting=False):
        result = strings(value)
        if len(set(result)) != len(result) or not set(result).issubset(usable):
            raise EvidenceMismatch("unknown, duplicated or unavailable evidence reference")
        if required and not result:
            raise EvidenceMismatch("substantive observation needs supplied evidence")
        if conflicting and len(result) < 2:
            raise EvidenceMismatch("conflicting observation needs multiple evidence items")
        return result

    identities, components, conditions = [], [], []
    for item in sequence(payload["identity"]):
        object_fields(item, {"field", "state", "values", "evidence_refs", "limitations"})
        name, state = choice(item["field"], IDENTITY_FIELDS), choice(item["state"], STATES)
        values, limits = strings(item["values"]), strings(item["limitations"])
        if (state == "observed" and not values) or (state == "conflicting" and len(set(values)) < 2):
            raise ValidationError("observed/conflicting identity needs explicit values")
        if state in {"unknown", "not_visible", "not_observed"} and values:
            raise ValidationError("unavailable identity cannot assert values")
        if state != "observed" and not limits:
            raise ValidationError("uncertain identity needs limitations")
        identities.append(IdentityObservation(name, state, values,
            refs(item["evidence_refs"], state != "unknown", state == "conflicting"), limits))

    for item in sequence(payload["components"]):
        object_fields(item, {"component", "presence", "visibility", "quantity", "quantity_reliable",
                             "absence_basis", "evidence_refs", "limitations"})
        name = text(item["component"])
        presence = choice(item["presence"], {"present", "absent", "unknown", "conflicting"})
        visibility = choice(item["visibility"], VISIBILITY)
        quantity, reliable, basis = item["quantity"], item["quantity_reliable"], item["absence_basis"]
        limits = strings(item["limitations"])
        if type(reliable) is not bool:
            raise ValidationError("quantity_reliable must be boolean")
        if quantity is not None and (type(quantity) is not int or quantity < 0):
            raise ValidationError("quantity must be nonnegative integer or null")
        if reliable != (quantity is not None):
            raise ValidationError("unreliable quantity must remain null")
        if quantity is not None and (visibility != "visible" or presence not in {"present", "absent"}):
            raise ValidationError("quantity cannot be inferred from obscured/conflicting evidence")
        if presence == "present" and (visibility not in {"visible", "partial"} or quantity == 0):
            raise ValidationError("present component needs visibility")
        if presence == "absent":
            if visibility != "visible" or quantity != 0 or basis != "full_expected_area_visible" or not limits:
                raise ValidationError("absence needs explicit full coverage basis and explanation")
        elif basis is not None:
            raise ValidationError("absence basis only applies to an absence assertion")
        if presence in {"unknown", "conflicting"} and not limits:
            raise ValidationError("uncertain component needs limitations")
        components.append(ComponentObservation(name, presence, visibility, quantity, reliable, basis,
            refs(item["evidence_refs"], presence != "unknown", presence == "conflicting"), limits))

    for item in sequence(payload["condition"]):
        object_fields(item, {"feature", "state", "description", "evidence_refs", "limitations"})
        name, state = choice(item["feature"], CONDITION_FEATURES), choice(item["state"], STATES)
        description, limits = item["description"], strings(item["limitations"])
        if description is not None:
            text(description)
        if state in {"observed", "not_observed", "conflicting"} and description is None:
            raise ValidationError("visible finding needs a provider description")
        if state in {"unknown", "not_visible"} and description is not None:
            raise ValidationError("unavailable condition cannot assert a finding")
        if state != "observed" and not limits:
            raise ValidationError("negative/uncertain finding needs visible-scope limitations")
        conditions.append(ConditionObservation(name, state, description,
            refs(item["evidence_refs"], state != "unknown", state == "conflicting"), limits))

    conflicts = set()
    # Preserve every assertion, and flag contradictory assertions instead of choosing a winner.
    for name in {i.field for i in identities}:
        entries = [i for i in identities if i.field == name]
        states = {i.state for i in entries}
        if ("conflicting" in states or {"observed", "not_observed"}.issubset(states)
                or len({i.values for i in entries if i.state == "observed"}) > 1):
            conflicts.add("identity:" + name)
    for name in {c.component for c in components}:
        entries = [c for c in components if c.component == name]
        known = {(c.presence, c.quantity) for c in entries if c.presence in {"present", "absent"}}
        if any(c.presence == "conflicting" for c in entries) or len(known) > 1:
            conflicts.add("component:" + name)
    for name in {c.feature for c in conditions}:
        entries = [c for c in conditions if c.feature == name]
        if any(c.state == "conflicting" for c in entries) or len({c.state for c in entries if c.state in {"observed", "not_observed"}}) > 1:
            conflicts.add("condition:" + name)
    return ObservationBatch(scope, images, response.provider_name, response.mode, tuple(identities),
                            tuple(components), tuple(conditions), strings(payload["limitations"]), tuple(sorted(conflicts)))


def validate_batch(capture: Capture, batch: ObservationBatch) -> None:
    """Reparse even manually constructed dataclasses at deterministic/storage boundaries."""
    if not isinstance(batch, ObservationBatch):
        raise ValidationError("validated ObservationBatch required")
    payload = {"scope": asdict(batch.scope), "identity": [asdict(i) for i in batch.identity],
               "components": [asdict(c) for c in batch.components],
               "condition": [asdict(c) for c in batch.condition], "limitations": batch.limitations}
    try:
        reparsed = parse_response(capture, batch.images,
                                  ProviderResponse(json.dumps(payload), batch.provider_name, batch.provider_mode))
    except (TypeError, AttributeError) as exc:
        raise ValidationError("malformed internal observation") from exc
    if reparsed != batch:
        raise ValidationError("internal observation does not match validation")
