from typing import List, Optional

from ..models import CheckContext, EvidenceItem

def cited_latency(ctx: CheckContext, image_ids: List[Optional[str]]) -> int:
    """VLM latency attributable to the images a check's evidence relies on."""
    ids = {i for i in image_ids if i}
    return sum(p.latency_ms for p in ctx.observations if p.image_id in ids)

def absence(desc: str, strength: float = 0.3) -> List[EvidenceItem]:
    return [EvidenceItem(type="absence", description=desc, strength=strength)]