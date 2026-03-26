# ai_services/refinery/dubbing_script_refiner/schemas.py
from typing import List, Optional
from pydantic import BaseModel, Field

class LLMRefinedSegment(BaseModel):
    """
    The structure the LLM is expected to return for a single dialogue unit.
    This matches the public RefinedSegment, as the LLM is responsible for all fields.
    """
    start: float
    end: float
    refined_text: Optional[str]
    source_of_truth: str = Field(..., description="e.g. TRUST_OCR_CORRECTION, TRUST_ASR_RAW, DISCARD_NOISE")

class BatchRefinementResponse(BaseModel):
    """
    The root object the LLM should return for a batch of dialogue units.
    """
    refined_script: List[LLMRefinedSegment]