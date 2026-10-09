from pydantic import BaseModel

__all__ = ['AIAnalysisResult']

class CheckResults(BaseModel):
    all_items_present: bool
    quantities_correct: bool
    no_extra_items: bool

class AIAnalysisResult(BaseModel):
    observed_items: str
    checks_performed: CheckResults
    verdict: str  # SEAL, STOP_AND_FIX, UNCERTAIN
    reasoning: str
