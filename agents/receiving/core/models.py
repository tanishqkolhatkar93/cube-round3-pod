from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()

# ---------- purchase order (aligned to reference contract) ----------

class POLineItem(BaseModel):
    sku: str
    asin: Optional[str] = None
    product_title: Optional[str] = None
    spec_colour: Optional[str] = None        # None or "n/a" -> colour check NOT_APPLICABLE
    spec_variant: Optional[str] = None       # non-colour variant (e.g. "750ml", "6ft")
    spec_components: Optional[List[str]] = None
    cartons_ordered: Optional[int] = None
    units_per_carton_ordered: Optional[int] = None
    qty_ordered: int

class POCreate(BaseModel):
    unit_id: str                  # cross-stage join key (Round 3)
    po_number: str
    po_line: int = 1
    supplier: Optional[str] = None
    operator_id: Optional[str] = None
    line_items: List[POLineItem]  # MVP: exactly 1 (enforced in API)

# ---------- extraction (per image, blind to the PO) ----------

class DamageObs(BaseModel):
    damage_type: Literal["crushing", "dent", "tear_or_open", "water", "other"]
    target: Literal["carton", "unit"]
    location: str
    severity: Literal["minor", "major"]
    confidence: float = Field(ge=0, le=1)

class ImageObservation(BaseModel):
    visible_sku_text: Optional[str] = None
    visible_product_text: Optional[str] = None
    printed_quantity: Optional[int] = None
    visible_unit_count: Optional[int] = None
    count_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    full_contents_visible: bool = False
    cartons_visible: int = 0
    dominant_product_color: Optional[str] = None
    color_reliability: Literal["good", "poor"] = "good"
    label_colour_text: Optional[str] = None
    label_variant_text: Optional[str] = None
    visible_components: Optional[List[str]] = None
    contents_open_for_inspection: bool = False
    damages: List[DamageObs] = []
    quality_issues: List[str] = []
    notes: Optional[str] = None

class IndexedImageObservation(BaseModel):
    image_index: int = Field(ge=0)
    observation: ImageObservation

class ImageObservationBatch(BaseModel):
    images: List[IndexedImageObservation]

class ObsProvenance(BaseModel):
    image_id: str
    sha256: str
    observation: ImageObservation
    barcodes: List[str] = []        # decoded locally by pyzbar (deterministic tier)
    quality: Optional[dict] = None  # deterministic quality-gate result (quality.py)
    latency_ms: int = 0
    tokens: int = 0

# ---------- checks ----------

class EvidenceItem(BaseModel):
    type: str
    image_id: Optional[str] = None
    quote: Optional[str] = None
    description: str
    strength: float = Field(ge=0, le=1)

class CheckResult(BaseModel):
    check_key: str
    verdict: Literal["PASS", "FAIL", "UNCERTAIN", "NOT_APPLICABLE"]
    confidence: float
    detail: str
    evidence: List[EvidenceItem] = []
    model_version: str
    latency_ms: int = 0
    uncertainty_reason: Optional[str] = None
    summary_value: Optional[str] = None   # contract vocabulary for receiving_summary

class CheckContext(BaseModel):
    po: POLineItem
    observations: List[ObsProvenance]
    model_version: str

# ---------- human override (Session 6) ----------

class OverrideRequest(BaseModel):
    override_by: str
    override_reason: str
    new_decision: Literal["PASS", "FAIL", "UNCERTAIN"]