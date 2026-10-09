"""Immutable internal types. No grades, observations or confidence are inferred."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .observations import ObservationBatch


class ValidationError(ValueError):
    """Malformed or unsupported input; caller must correct it."""


class TenantMismatch(PermissionError):
    """Input does not belong to the caller's trusted context."""


def validate_unicode_scalars(value: str) -> None:
    """Reject surrogate code points without replacing or normalizing input."""
    if not isinstance(value, str) or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValidationError("text containing only valid Unicode scalars required")


def identifier(value: str, name: str) -> str:
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValidationError(f"{name}: nonempty text without edge whitespace/control characters required")
    validate_unicode_scalars(value)
    return value


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNCERTAIN = "UNCERTAIN"


class Disposition(str, Enum):
    RESTOCK = "restock"
    REFURBISH = "refurbish"
    LIQUIDATE = "liquidate"
    DISPOSE = "dispose"
    PENDING_REVIEW = "pending_review"


@dataclass(frozen=True)
class TenantContext:
    # Must come from trusted caller configuration, never from a submitted row.
    organization_id: str
    client_id: str | None = None

    def __post_init__(self):
        identifier(self.organization_id, "organization_id")
        if self.client_id is not None:
            identifier(self.client_id, "client_id")


@dataclass(frozen=True)
class Unit:
    unit_id: str

    def __post_init__(self):
        identifier(self.unit_id, "unit_id")


@dataclass(frozen=True)
class OrderContext:
    order_id: str
    ordered_sku: str
    ordered_asin: str

    def __post_init__(self):
        for name in ("order_id", "ordered_sku", "ordered_asin"):
            identifier(getattr(self, name), name)


@dataclass(frozen=True)
class Component:
    raw: str
    name: str
    quantity: int | None

    def __post_init__(self):
        identifier(self.raw, "component.raw")
        identifier(self.name, "component.name")
        if self.quantity is not None and (type(self.quantity) is not int or self.quantity <= 0):
            raise ValidationError("component.quantity: positive integer or unknown required")


@dataclass(frozen=True)
class ProductReference:
    ordered_sku: str
    ordered_asin: str
    components: tuple[Component, ...]
    # The CSV is not an authoritative catalogue, even when it lists parts.
    status: str = field(default="unverified_synthetic_reference", init=False)


@dataclass(frozen=True)
class EvidenceReference:
    reference: str
    # No loader or image-serving API exists in Phase 1. Never dereference input paths.
    status: str = field(default="unavailable", init=False)
    reason: str = field(default="synthetic_csv_placeholder_not_image_evidence", init=False)

    def __post_init__(self):
        identifier(self.reference, "photo_refs")


@dataclass(frozen=True)
class SourceLineage:
    source_name: str
    source_sha256: str
    row_number: int
    kind: str = field(default="synthetic_test_fixture", init=False)

    def __post_init__(self):
        identifier(self.source_name, "source_name")
        if (not isinstance(self.source_sha256, str) or len(self.source_sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.source_sha256)):
            raise ValidationError("source_sha256: lowercase SHA-256 digest required")
        if type(self.row_number) is not int or self.row_number < 2:
            raise ValidationError("row_number: CSV data line (>=2) required")


@dataclass(frozen=True)
class CollectionLineage(SourceLineage):
    """Real files with supplier statements and synthetic collection order labels.

    row_number is the stable product index + 1, not a claim of a source CSV row.
    captured_at records ingestion time; no camera timestamp is inferred.
    """
    metadata_snapshot: str
    kind: str = field(default="real_product_collection", init=False)
    timestamp_kind: str = field(default="ingested_at_not_photographed_at", init=False)

    def __post_init__(self):
        super().__post_init__()
        validate_unicode_scalars(self.metadata_snapshot)
        if len(self.metadata_snapshot) > 100_000:
            raise ValidationError("collection metadata snapshot too large")
        import json
        def pairs(items):
            result = {}
            for key, item in items:
                if key in result:
                    raise ValidationError("duplicate collection metadata key")
                result[key] = item
            return result
        try:
            value = json.loads(self.metadata_snapshot, object_pairs_hook=pairs)
        except (ValueError, RecursionError):
            raise ValidationError("invalid collection metadata JSON") from None
        if (not isinstance(value, dict) or not isinstance(value.get("metadata"), dict)
                or value["metadata"].get("independent_annotations") != "not_supplied"):
            raise ValidationError("collection source snapshot required")
        if hashlib.sha256(self.metadata_snapshot.encode()).hexdigest() != self.source_sha256:
            raise ValidationError("collection snapshot digest mismatch")


@dataclass(frozen=True)
class CollectionReference(ProductReference):
    status: str = field(default="unverified_supplier_collection_reference", init=False)


@dataclass(frozen=True)
class CollectionEvidenceReference(EvidenceReference):
    reason: str = field(default="collection_file_requires_image_validation", init=False)


def lineage_from_dict(value):
    """Rehydrate only recognized lineage types; never accept arbitrary source kinds."""
    from dataclasses import fields, asdict
    kind = value.get("kind")
    cls = CollectionLineage if kind == "real_product_collection" else SourceLineage
    source = cls(**{f.name: value[f.name] for f in fields(cls) if f.init})
    if asdict(source) != value:
        raise ValidationError("unrecognized or altered source lineage")
    return source


@dataclass(frozen=True)
class Capture:
    record_id: str
    tenant: TenantContext
    unit: Unit
    order: OrderContext
    reference: ProductReference
    operator_id: str
    captured_at: str
    images: tuple[EvidenceReference, ...]
    source: SourceLineage
    # Exact CSV values (including historical labels) are lineage only.
    raw_fields: tuple[tuple[str, str], ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class ObservationPlaceholder:
    reason: str = "observation_not_available"
    status: str = field(default="unavailable", init=False)

    def __post_init__(self):
        identifier(self.reason, "observation.reason")


@dataclass(frozen=True)
class DecisionReference:
    """Trusted caller's order/catalogue attestation, never a model assertion.

    The source snapshot and its digest provide lineage, not proof of truth.
    Bind it to exactly one capture and retain who verified it. No CSV auto-promotion.
    """
    tenant: TenantContext
    record_id: str
    unit_id: str
    order_id: str
    ordered_sku: str
    ordered_asin: str
    components: tuple[Component, ...]
    parts_list_complete: bool
    source_name: str
    source_document: str
    verified_by: str
    verified_at: str
    reference_status: str = "operator_attested"
    source_sha256: str = field(init=False)

    def __post_init__(self):
        from datetime import datetime, timedelta
        if self.reference_status not in ("operator_attested", "synthetic_demo"):
            raise ValidationError("unsupported reference status")
        if not isinstance(self.tenant, TenantContext):
            raise ValidationError("reference tenant required")
        TenantContext(self.tenant.organization_id, self.tenant.client_id)
        for name in ("record_id", "unit_id", "order_id", "ordered_sku", "ordered_asin",
                     "source_name", "verified_by", "verified_at"):
            value = identifier(getattr(self, name), name)
            if len(value) > 8192:
                raise ValidationError("reference text too long")
        validate_unicode_scalars(self.source_document)
        if (not self.source_document.strip() or len(self.source_document) > 8192
                or any((ord(c) < 32 and c not in "\r\n\t") or ord(c) == 127 for c in self.source_document)):
            raise ValidationError("bounded source document text required")
        try:
            stamp = datetime.fromisoformat(self.verified_at.replace("Z", "+00:00"))
            if "T" not in self.verified_at or stamp.utcoffset() != timedelta(0):
                raise ValueError()
        except ValueError:
            raise ValidationError("reference verification timestamp must be UTC") from None
        if type(self.parts_list_complete) is not bool or type(self.components) is not tuple or len(self.components) > 200:
            raise ValidationError("bounded component tuple and explicit parts-list coverage required")
        for component in self.components:
            if not isinstance(component, Component):
                raise ValidationError("reference Component required")
            Component(component.raw, component.name, component.quantity)
        if len({c.name.casefold() for c in self.components}) != len(self.components):
            raise ValidationError("duplicate reference component")
        object.__setattr__(self, "source_sha256", hashlib.sha256(self.source_document.encode("utf-8")).hexdigest())


@dataclass(frozen=True)
class IdentityResult:
    reasons: tuple[str, ...]
    verdict: Verdict = Verdict.UNCERTAIN
    confidence: None = field(default=None, init=False)
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompletenessResult:
    unknown_components: tuple[str, ...]
    reasons: tuple[str, ...]
    verdict: Verdict = Verdict.UNCERTAIN
    missing_components: tuple[str, ...] = ()
    confidence: None = field(default=None, init=False)
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConditionResult:
    reasons: tuple[str, ...]
    verdict: Verdict = field(default=Verdict.UNCERTAIN, init=False)
    grade: None = field(default=None, init=False)
    confidence: None = field(default=None, init=False)
    evidence: tuple[str, ...] = ()
    policy_source: str = field(default="https://sell.amazon.com/blog/amazon-condition-guidelines", init=False)
    policy_status: str = field(default="category_and_nonvisual_checks_unresolved", init=False)


@dataclass(frozen=True)
class DispositionResult:
    decision: Disposition
    reasons: tuple[str, ...]

    def __post_init__(self):
        try:
            object.__setattr__(self, "decision", Disposition(self.decision))
        except (ValueError, TypeError) as exc:
            raise ValidationError("unsupported disposition") from exc


@dataclass(frozen=True)
class ReviewState:
    reasons: tuple[str, ...]
    status: str = field(default="pending_review", init=False)


@dataclass(frozen=True)
class Assessment:
    identity: IdentityResult
    completeness: CompletenessResult
    condition: ConditionResult
    disposition: DispositionResult
    review: ReviewState
    observation: ObservationPlaceholder | ObservationBatch
    decision_reference: DecisionReference | None = None
    rule_version: str = field(default="scoped-reference-checks-2", init=False)
    format_notice: str = field(default="internal_only_not_official_wire_contract", init=False)
