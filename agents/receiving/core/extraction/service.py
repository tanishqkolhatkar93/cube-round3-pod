import hashlib
import io
import json

from PIL import Image, ImageOps

from ..config import CFG
from ..models import ImageObservation, ObsProvenance
from ..quality import assess_quality
from .base import VisionProvider, VisionRequest
from .barcode import decode_barcodes

PROMPT_FILE = "observe_carton.v2.txt"
PROMPT_VERSION = "observe_carton@v2"


def load_prompt() -> str:
    return (CFG.prompts_dir / PROMPT_FILE).read_text(encoding="utf-8")


def process_image(raw: bytes) -> bytes:
    """EXIF-rotate (phone photos!), downscale to <=1280px, re-encode JPEG."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    if max(img.size) > 1280:
        img.thumbnail((1280, 1280))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()


class ExtractionService:
    """Quality gate BEFORE the provider call: rejected photos never consume
    VLM quota and never produce claims. VLM cache above the provider.
    Round 3 adaptation: `stats` collects honest model-call accounting for
    the contract's model {calls} (cache hits are not counted as calls)."""

    def __init__(self, provider: VisionProvider):
        self.provider = provider
        CFG.cache_dir.mkdir(parents=True, exist_ok=True)

    def observe(self, original_sha: str, image_id: str, raw: bytes, stats: dict | None = None):
        processed = process_image(raw)
        quality = assess_quality(processed)
        barcodes = decode_barcodes(processed)

        if quality["verdict"] == "REJECTED":
            if stats:
                stats["rejected"] = stats.get("rejected", 0) + 1
            return (ObsProvenance(image_id=image_id, sha256=original_sha,
                                  observation=ImageObservation(),
                                  barcodes=barcodes, quality=quality,
                                  latency_ms=0, tokens=0),
                    "quality-gate-rejected")

        key = hashlib.sha256(
            f"{self.provider.name}|{CFG.gemini_model}|{PROMPT_VERSION}|"
            f"{hashlib.sha256(processed).hexdigest()}".encode()
        ).hexdigest()[:24]
        cache_file = CFG.cache_dir / f"{key}.json"

        if cache_file.exists():
            if stats:
                stats["cached"] = stats.get("cached", 0) + 1
            d = json.loads(cache_file.read_text())
            return (ObsProvenance(image_id=image_id, sha256=original_sha,
                                  observation=ImageObservation(**d["parsed"]),
                                  latency_ms=0, tokens=d["tokens"],
                                  barcodes=barcodes, quality=quality),
                    d["model_id"])

        resp = self.provider.analyze(VisionRequest(
            image_bytes=processed, prompt_text=load_prompt(),
            prompt_version=PROMPT_VERSION, schema_model=ImageObservation))
        if stats:
            stats["calls"] = stats.get("calls", 0) + 1
            stats.setdefault("model_ids", []).append(resp.model_id)
        cache_file.write_text(json.dumps({
            "parsed": resp.parsed.model_dump(),
            "model_id": resp.model_id, "tokens": resp.tokens}))
        return (ObsProvenance(image_id=image_id, sha256=original_sha,
                              observation=resp.parsed,
                              latency_ms=resp.latency_ms, tokens=resp.tokens,
                              barcodes=barcodes, quality=quality),
                resp.model_id)