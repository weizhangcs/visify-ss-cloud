from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from ai_services.schemas.refinery.visual_analyzer import ShotType

class LLMVisualAnalysisData(BaseModel):
    """
    LLM 返回的原始数据结构，shot_type 保持为 Enum。
    """
    shot_type: Optional[ShotType] = Field(None, description="Main shot size")
    environment: Optional[str] = Field(None, description="Physical environment")
    subject: Optional[str] = None
    action: Optional[str] = None
    lighting_time: Optional[str] = Field(None, description="Time or lighting characteristics")
    visual_mood_tags: List[str] = Field(default_factory=list)
    
    model_config = ConfigDict(extra='allow')

class FrameAnalysisResult(BaseModel):
    frame_id: str
    visual_analysis: LLMVisualAnalysisData

class BatchVisualOutput(BaseModel):
    results: List[FrameAnalysisResult]