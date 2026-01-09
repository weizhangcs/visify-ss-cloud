from typing import List
from pydantic import BaseModel, Field
from ai_services.schemas.refinery.slice_regrouper import SceneType

class LLMSceneContent(BaseModel):
    """
    LLM 返回的原始场景内容，scene_type 为 Enum。
    """
    narrative_action: str
    location: str
    scene_type: SceneType
    visual_mood_tags: List[str] = Field(default_factory=list)
    camera_logic: str
    character_dynamics: str
    reason: str

class LLMScene(BaseModel):
    """
    [LLM Output] LLM 返回的原始场景结构。
    """
    scene_id: int = Field(..., description="Sequential ID")
    content: LLMSceneContent
    slice_ids: List[int] = Field(..., description="List of slice IDs included in this scene")

class RegroupingResponse(BaseModel):
    """LLM 响应容器"""
    scenes: List[LLMScene]