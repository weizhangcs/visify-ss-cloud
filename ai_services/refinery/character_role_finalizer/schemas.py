# ai_services/refinery/character_role_finalizer/schemas.py
from typing import List, Optional
from pydantic import BaseModel, Field

class LLMCharacterInfo(BaseModel):
    speaker_id: str
    name: str
    aliases: List[str]
    gender_inference: Optional[str] = Field(None, description="Inferred gender from text/context")

class LLMFinalizedSegment(BaseModel):
    index: int
    speaker_id: str
    reasoning: str

class BatchRoleFinalizationResponse(BaseModel):
    """LLM Output Structure"""
    character_map: List[LLMCharacterInfo]
    # 仅返回需要修正或确认的关键信息，避免重复大段文本
    segments: List[LLMFinalizedSegment]