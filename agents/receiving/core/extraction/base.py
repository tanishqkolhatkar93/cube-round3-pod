from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..models import ImageObservation

@dataclass
class VisionRequest:
    image_bytes: list[bytes] # processed JPEGs for one receiving unit
    prompt_text: str
    prompt_version: str
    schema_model: Any       # pydantic class the response MUST validate against

@dataclass
class VisionResponse:
    parsed: Any
    raw_text: str
    model_id: str
    prompt_version: str
    latency_ms: int
    tokens: int

class VisionProvider(ABC):
    """The ONLY provider-aware code in the system. Checks and the decision
    engine never import anything from a provider."""
    name: str

    @abstractmethod
    def analyze(self, req: VisionRequest) -> VisionResponse: ...