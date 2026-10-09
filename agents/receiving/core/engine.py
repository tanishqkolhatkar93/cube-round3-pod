"""Deterministic image gate, extraction cache, then lazy provider observations."""
import hashlib
import time
from .config import CFG
from .extraction.service import ExtractionService
from .failures import classify

def run_engine(images):
    stats = {"calls": 0, "cached": 0, "rejected": 0, "model_ids": [], "attempts": []}
    provs, errors = [], []
    deadline = time.monotonic() + CFG.timeout_s
    # Context exit can fail after successful observations. Keep the accumulated
    # statistics and earlier failures instead of losing them in the adapter fallback.
    try:
        with ExtractionService() as svc:
            for i, (ref, raw) in enumerate(images):
                image_id = f"img_{i+1}"
                try:
                    prov, mid = svc.observe(hashlib.sha256(raw).hexdigest(), image_id, raw, stats=stats, deadline=deadline)
                    provs.append(prov)
                except Exception as exc:
                    errors.append({"image_id": image_id, "code": classify(exc)})
    except Exception as exc:
        errors.append({"code": classify(exc)})
    return provs, stats, errors
