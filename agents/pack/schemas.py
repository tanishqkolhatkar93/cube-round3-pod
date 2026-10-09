from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

__all__ = ['AIAnalysisResult']

class CheckResults(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    all_items_present: bool
    quantities_correct: bool
    no_extra_items: bool

class ItemObservation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    sku: str = Field(min_length=1, max_length=200)
    quantity: int = Field(ge=1, le=100_000)

class ImageObservation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    ref: str = Field(min_length=1, max_length=500)
    usable: bool
    complete: bool
    items: list[ItemObservation] = Field(max_length=1000)

class AIAnalysisResult(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    images: list[ImageObservation] = Field(min_length=1, max_length=8)
    observed_items: str
    checks_performed: CheckResults
    verdict: Literal['SEAL', 'STOP_AND_FIX', 'UNCERTAIN']
    reasoning: str
