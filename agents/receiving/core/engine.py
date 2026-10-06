"""The Round 2 inspection pipeline as one callable.
Quality gate -> per-image extraction (QR + cached-or-live VLM) -> observations."""
import hashlib

from .extraction.service import ExtractionService
from .extraction.gemini import GeminiProvider


def run_engine(images):
    """images: list[(ref, bytes)]. Returns (provenances, stats, errors).
    REJECTED photos are returned with empty observations + quality dict.
    Per-image provider failures are caught and listed, never raised."""
    svc = ExtractionService(GeminiProvider())
    stats = {"calls": 0, "cached": 0, "rejected": 0, "model_ids": []}
    provs, errors = [], []
    for i, (ref, raw) in enumerate(images):
        image_id = f"img_{i+1}"
        sha = hashlib.sha256(raw).hexdigest()
        try:
            prov, _mid = svc.observe(sha, image_id, raw, stats=stats)
            provs.append(prov)
        except Exception as e:
            errors.append((image_id, f"{type(e).__name__}: {str(e)[:120]}"))
    return provs, stats, errors