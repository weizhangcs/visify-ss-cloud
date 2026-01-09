from typing import List
from pydantic import BaseModel

# --- Stage 1: Batch Inference ---

class RoleMapping(BaseModel):
    index: int
    speaker: str

class BatchRoleInferenceResponse(BaseModel):
    mappings: List[RoleMapping]

# --- Stage 2: Normalization ---

class NormalizationItem(BaseModel):
    original_name: str
    normalized_name: str

class SpeakerNormalizationResponse(BaseModel):
    normalization_items: List[NormalizationItem]