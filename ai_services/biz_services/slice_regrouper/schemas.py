from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, model_validator

# ==============================================================================
# 1. 输入侧 Schemas (对齐 Edge 端 MultimodalSlice 结构)
# ==============================================================================

class AudioAnalysis(BaseModel):
    gender: str = Field(default="Unknown")
    model_config = ConfigDict(extra='ignore')

class SubtitleItem(BaseModel):
    index: int
    content: str
    start_time: float
    end_time: float
    speaker: str = "Unknown"
    audio_analysis: Optional[AudioAnalysis] = None
    model_config = ConfigDict(extra='ignore')

class VisualAnalysisData(BaseModel):
    shot_type: Optional[str] = None
    environment: Optional[str] = None
    subject: Optional[str] = None
    action: Optional[str] = None
    visual_mood_tags: List[str] = Field(default_factory=list)
    model_config = ConfigDict(extra='ignore')

class FrameDataInput(BaseModel):
    frame_id: str
    timestamp: float
    path: str
    digest: Optional[str] = None
    visual_analysis: Optional[VisualAnalysisData] = None
    model_config = ConfigDict(extra='ignore')

class MultimodalSlice(BaseModel):
    """
    [核心容器] 多模态切片。
    对应 Edge 端上传的 JSON 列表元素。
    """
    slice_id: int
    start_time: float
    end_time: float
    type: str
    text_contents: List[SubtitleItem] = Field(default_factory=list)
    visual_contents: List[FrameDataInput] = Field(default_factory=list)
    model_config = ConfigDict(extra='ignore')

# ==============================================================================
# 2. 任务 Payload
# ==============================================================================

class SliceRegrouperPayload(BaseModel):
    lang: str = Field("zh", description="Language code")
    model: str = Field(..., description="LLM model name (e.g. gemini-2.5-flash)")
    slices_file_path: Optional[str] = Field(None, description="Path to the rich slices JSON file (Production)")
    slices: Optional[List[MultimodalSlice]] = Field(None, description="Direct list of slices (Debug)")

    @model_validator(mode='after')
    def check_data_source(self):
        if not self.slices and not self.slices_file_path:
            raise ValueError("Either 'slices' or 'slices_file_path' must be provided.")
        return self

# ==============================================================================
# 3. 输出侧 Schemas (场景定义)
# ==============================================================================

class SceneType(str, Enum):
    DIALOGUE = "dialogue"
    ACTION = "action"
    MONTAGE = "montage"
    ESTABLISHING = "establishing"
    EMOTIONAL = "emotional"
    UNKNOWN = "unknown"

class SceneContent(BaseModel):
    narrative_action: str = Field(..., description="Core event or physical action.")
    location: str = Field(..., description="Primary location.")
    scene_type: SceneType = Field(..., description="Functional type of the scene.")
    visual_mood_tags: List[str] = Field(default_factory=list, description="Dominant visual mood tags.")
    camera_logic: str = Field(..., description="Editing/Camera logic summary.")
    character_dynamics: str = Field(..., description="Relationship status or tension.")
    reason: str = Field(..., description="Reason for grouping.")

class LLMScene(BaseModel):
    """
    [LLM Output] LLM 返回的原始场景结构。
    不包含时间戳，时间戳由 Python 后处理计算。
    """
    scene_id: int = Field(..., description="Sequential ID")
    content: SceneContent
    slice_ids: List[int] = Field(..., description="List of slice IDs included in this scene")

class RegroupingResponse(BaseModel):
    """LLM 响应容器"""
    scenes: List[LLMScene]

class Scene(BaseModel):
    """
    [Final Output] 最终交付给前端的场景结构。
    包含计算后的时间戳。
    """
    scene_id: int
    start_time: float
    end_time: float
    content: SceneContent
    slice_ids: List[int]

class SliceRegrouperResult(BaseModel):
    scenes: List[Scene]
    stats: Dict[str, Any]
    usage_report: Dict[str, Any]