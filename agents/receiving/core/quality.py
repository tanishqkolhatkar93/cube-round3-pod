"""Deterministic image-quality gate.

Metrics (PIL only, no CV dependency):
- edge_energy: variance of edge intensity (sharpness proxy; higher = sharper)
- brightness: mean luminance 0-255
- min_side: smaller image dimension in pixels

Thresholds are PROVISIONAL heuristics — validate with scripts/quality_probe.py
against real receiving photos, then record confirmed values in EVALUATION.md.
They are constants (never model outputs), so the gate is deterministic and
reproducible.
"""
import io

from PIL import Image, ImageFilter, ImageStat

# --- provisional thresholds (validate before submission) ---
BLUR_DEGRADED = 150.0     # edge_energy below -> soft focus
BLUR_REJECTED = 60.0      # edge_energy below -> unusable for visual judgement
DARK_DEGRADED = 50.0      # mean brightness below -> too dark
DARK_REJECTED = 30.0
CLIP_DEGRADED = 240.0     # mean brightness above -> blown highlights
MIN_SIDE_DEGRADED = 400   # px
MIN_SIDE_REJECTED = 200

_SEVERE = {"resolution_too_low", "severely_blurry", "extremely_dark"}


def classify(edge_energy: float, brightness: float, min_side: int):
    """Pure function: metrics -> (verdict, reasons). Deterministic, unit-tested."""
    reasons = []
    if min_side < MIN_SIDE_REJECTED:
        reasons.append("resolution_too_low")
    elif min_side < MIN_SIDE_DEGRADED:
        reasons.append("low_resolution")
    if edge_energy < BLUR_REJECTED:
        reasons.append("severely_blurry")
    elif edge_energy < BLUR_DEGRADED:
        reasons.append("blurry")
    if brightness < DARK_REJECTED:
        reasons.append("extremely_dark")
    elif brightness < DARK_DEGRADED:
        reasons.append("too_dark")
    if brightness > CLIP_DEGRADED:
        reasons.append("highlights_clipped")
    if any(r in _SEVERE for r in reasons):
        return "REJECTED", reasons
    if reasons:
        return "DEGRADED", reasons
    return "ACCEPTABLE", []


def assess_quality(jpeg_bytes: bytes) -> dict:
    img = Image.open(io.BytesIO(jpeg_bytes))
    w, h = img.size
    gray = img.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_std = ImageStat.Stat(edges).stddev[0]
    edge_energy = edge_std * edge_std
    brightness = ImageStat.Stat(gray).mean[0]
    verdict, reasons = classify(edge_energy, brightness, min(w, h))
    return {"verdict": verdict,
            "edge_energy": round(edge_energy, 1),
            "brightness": round(brightness, 1),
            "reasons": reasons}