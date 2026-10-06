import re

from ..models import CheckContext, CheckResult, EvidenceItem
from .base import absence, cited_latency

SKU_MARK = re.compile(r"SKU[-_]", re.IGNORECASE)

def _n(s: str) -> str:
    return s.strip().upper()

def run(ctx: CheckContext) -> CheckResult:
    expected = _n(ctx.po.sku)

    # ---- Tier 1: machine-readable barcode/QR (deterministic, pyzbar) ----
    for p in ctx.observations:
        for code in p.barcodes:
            n = _n(code)
            if expected in n or (n in expected and len(n) >= 4):
                return CheckResult(
                    check_key="sku_identity", verdict="PASS", confidence=0.95,
                    detail=(f"Barcode/QR on {p.image_id} decodes to '{code}', matching "
                            f"expected SKU '{ctx.po.sku}' (deterministic decode)."),
                    evidence=[EvidenceItem(type="barcode", image_id=p.image_id, quote=code,
                                           description=f"Decoded barcode/QR payload: '{code}'.",
                                           strength=0.95)],
                    model_version=ctx.model_version,
                    latency_ms=cited_latency(ctx, [p.image_id]))
            if SKU_MARK.search(code):
                # A code that carries a SKU identifier, but a different one.
                return CheckResult(
                    check_key="sku_identity", verdict="FAIL", confidence=0.9,
                    detail=(f"Barcode/QR on {p.image_id} decodes to '{code}', which does "
                            f"not match expected SKU '{ctx.po.sku}'."),
                    evidence=[EvidenceItem(type="barcode", image_id=p.image_id, quote=code,
                                           description=f"Decoded barcode/QR payload: '{code}'.",
                                           strength=0.9)],
                    model_version=ctx.model_version,
                    latency_ms=cited_latency(ctx, [p.image_id]))
            # NOTE: numeric UPC/EAN payloads that don't match are deliberately
            # ignored — we cannot map retail barcodes to SKUs without a
            # catalogue; a non-matching UPC is not evidence of a wrong SKU.

    # ---- Tier 2: printed label text (VLM-read) ----
    matches, reads = [], []
    for p in ctx.observations:
        t = p.observation.visible_sku_text
        if not t:
            continue
        reads.append((p, t))
        n = _n(t)
        if expected in n or (n in expected and len(n) >= 4):
            matches.append((p, t))

    if matches:
        ev = [EvidenceItem(type="label_text", image_id=p.image_id, quote=t,
                           description=f"Visible SKU text '{t}' matches expected '{ctx.po.sku}'.",
                           strength=0.9) for p, t in matches]
        return CheckResult(check_key="sku_identity", verdict="PASS", confidence=0.9,
                           detail=f"Expected SKU '{ctx.po.sku}' confirmed by readable label text.",
                           evidence=ev, model_version=ctx.model_version,
                           latency_ms=cited_latency(ctx, [e.image_id for e in ev]))

    if reads:
        p, t = reads[0]
        return CheckResult(check_key="sku_identity", verdict="FAIL", confidence=0.8,
                           detail=f"Expected SKU '{ctx.po.sku}' but label reads '{t}'.",
                           evidence=[EvidenceItem(type="label_text", image_id=p.image_id,
                                                  quote=t,
                                                  description=f"Visible SKU text '{t}' differs from expected.",
                                                  strength=0.8)],
                           model_version=ctx.model_version,
                           latency_ms=cited_latency(ctx, [p.image_id]))

    return CheckResult(check_key="sku_identity", verdict="UNCERTAIN", confidence=0.3,
                       detail="No readable SKU identifier in any image; product identity unverified.",
                       evidence=absence("No SKU text or barcode detected in any supplied image."),
                       model_version=ctx.model_version, uncertainty_reason="INSUFFICIENT_EVIDENCE",
                       latency_ms=cited_latency(ctx, [p.image_id for p in ctx.observations]))