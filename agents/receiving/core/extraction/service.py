"""Local gate + SQLite extraction cache, separate from request replay."""
import hashlib
import io
import json
import sqlite3
import time
from PIL import Image, ImageOps
from ..config import CFG
from ..models import ImageObservation, ObsProvenance
from ..quality import assess_quality
from ..failures import Failure
from .base import VisionRequest
from .barcode import decode_barcodes

PROMPT_FILE = "observe_carton.v2.txt"
PROMPT_VERSION = "observe_carton@v2"

def load_prompt():
    return (CFG.prompts_dir / PROMPT_FILE).read_text(encoding="utf-8")

def process_image(raw):
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
        if max(img.size) > 1280:
            img.thumbnail((1280, 1280))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=85)
        return out.getvalue()
    except Exception:
        raise Failure("invalid_image") from None

class ExtractionService:
    def __init__(self, provider=None):
        self.provider = provider

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self.provider is not None and hasattr(self.provider, "close"):
            self.provider.close()

    def observe(self, original_sha, image_id, raw, stats=None, deadline=None):
        stats = stats if stats is not None else {"calls":0,"cached":0,"rejected":0,"model_ids":[],"attempts":[]}
        deadline = deadline if deadline is not None else time.monotonic()+CFG.timeout_s
        processed = process_image(raw)
        quality = assess_quality(processed)
        barcodes = decode_barcodes(processed)
        if quality["verdict"] == "REJECTED":
            stats["rejected"] += 1
            return ObsProvenance(image_id=image_id, sha256=original_sha, observation=ImageObservation(),
                                 quality=quality, barcodes=barcodes), "quality-gate-rejected"
        # Same-host transaction serializes misses and atomically publishes parsed JSON.
        CFG.cache_dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(json.dumps([CFG.gemini_model, CFG.gemini_fallback_models,
             PROMPT_VERSION, load_prompt(), hashlib.sha256(processed).hexdigest()]).encode()).hexdigest()
        with sqlite3.connect(CFG.cache_dir / "observations.sqlite3", timeout=max(.001, deadline-time.monotonic()), isolation_level=None) as db:
            db.execute("CREATE TABLE IF NOT EXISTS observations (identity TEXT PRIMARY KEY, body TEXT NOT NULL)")
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM observations WHERE identity=?", (key,)).fetchone()
            latency, tokens = 0, 0
            if row:
                try:
                    data = json.loads(row[0])
                    observation = ImageObservation.model_validate(data["parsed"])
                    mid = data["model_id"]
                    if not isinstance(mid, str) or not mid:
                        raise ValueError()
                except Exception:
                    raise Failure("cache_integrity_error") from None
                stats["cached"] += 1
            else:
                if time.monotonic() >= deadline:
                    raise Failure("agent_timeout")
                if self.provider is None:
                    from .gemini import GeminiProvider
                    self.provider = GeminiProvider()
                resp = self.provider.analyze(VisionRequest(image_bytes=processed, prompt_text=load_prompt(),
                    prompt_version=PROMPT_VERSION, schema_model=ImageObservation), stats=stats, deadline=deadline)
                observation = ImageObservation.model_validate(resp.parsed.model_dump())
                mid, latency, tokens = resp.model_id, resp.latency_ms, resp.tokens
                db.execute("INSERT INTO observations VALUES (?,?)", (key,json.dumps({"parsed":observation.model_dump(),"model_id":mid})))
            db.commit()
        stats["model_ids"].append(mid)
        return ObsProvenance(image_id=image_id,sha256=original_sha,observation=observation,
                             latency_ms=latency,tokens=tokens,barcodes=barcodes,quality=quality), mid
