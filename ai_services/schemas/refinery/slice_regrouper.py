from typing import List, Optional, Dict, Any, Literal, Union
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, model_validator

# ==============================================================================
# 1. 输入侧 Schemas (MultimodalSlice)
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
    # 兼容上游 Visual Analyzer 的输出 (可能是 LabelItem 字典，也可能是旧的字符串)
    shot_type: Optional[Any] = None 
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

class SliceAnalysis(BaseModel):
    narrative_summary: str = Field(..., description="Summary of the narrative content.")
    visual_summary: str = Field(..., description="Summary of visual elements.")
    tags: List[str] = Field(default_factory=list, description="Semantic tags.")
    model_config = ConfigDict(extra='ignore')

class MultimodalSlice(BaseModel):
    """
    [核心容器] 多模态切片。
    """
    slice_id: int
    start_time: float
    end_time: float
    type: str
    text_contents: List[SubtitleItem] = Field(default_factory=list)
    visual_contents: List[FrameDataInput] = Field(default_factory=list)
    # [新增] 上游 Slice Analyzer 的分析结果
    slice_analysis: Optional[SliceAnalysis] = None
    model_config = ConfigDict(extra='ignore')

# ==============================================================================
# 2. 任务 Payload
# ==============================================================================

class SliceRegrouperServiceParams(BaseModel):
    """Technical parameters for DEBUG mode"""
    model: Optional[str] = Field(None, description="LLM model name")
    max_slices_per_batch: Optional[int] = Field(None, description="Slices per batch")
    temperature: Optional[float] = Field(None, description="Temperature for LLM")
    max_retries: Optional[int] = Field(None, description="Max retries")

class SliceRegrouperPayload(BaseModel):
    lang: str = Field("zh", description="Language code")
    mode: Literal["PROD", "DEBUG"] = Field("PROD", description="Operation mode")
    
    # Data Source
    slices_file_path: Optional[str] = Field(None, description="Path to the rich slices JSON file (Production)")
    slices: Optional[List[MultimodalSlice]] = Field(None, description="Direct list of slices (Debug)")
    
    # Debug Params
    service_params: Optional[SliceRegrouperServiceParams] = Field(default_factory=SliceRegrouperServiceParams)

    @model_validator(mode='after')
    def check_data_source(self):
        if not self.slices and not self.slices_file_path:
            raise ValueError("Either 'slices' or 'slices_file_path' must be provided.")
        
        if self.mode == "PROD":
            sp = self.service_params
            if sp and (sp.model or sp.max_slices_per_batch or sp.temperature or sp.max_retries):
                raise ValueError("In PROD mode, technical parameters are not allowed in payload.")
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

# 官方翻译映射表
SCENE_TYPE_LABELS = {
    "zh": {
        SceneType.DIALOGUE: "对话场景",
        SceneType.ACTION: "动作场景",
        SceneType.MONTAGE: "蒙太奇",
        SceneType.ESTABLISHING: "铺垫场景",
        SceneType.EMOTIONAL: "情感场景",
        SceneType.UNKNOWN: "未知类型"
    },
    "en": {
        SceneType.DIALOGUE: "Dialogue",
        SceneType.ACTION: "Action",
        SceneType.MONTAGE: "Montage",
        SceneType.ESTABLISHING: "Establishing",
        SceneType.EMOTIONAL: "Emotional",
        SceneType.UNKNOWN: "Unknown"
    }
}

class LabelItem(BaseModel):
    value: str
    label: str

class SceneContent(BaseModel):
    narrative_action: str = Field(..., description="Core event or physical action.")
    location: str = Field(..., description="Primary location.")
    # [核心变更] 使用 LabelItem (Value + Label)
    scene_type: LabelItem = Field(..., description="Functional type of the scene.")
    visual_mood_tags: List[str] = Field(default_factory=list, description="Dominant visual mood tags.")
    camera_logic: str = Field(..., description="Editing/Camera logic summary.")
    character_dynamics: str = Field(..., description="Relationship status or tension.")
    reason: str = Field(..., description="Reason for grouping.")

class Scene(BaseModel):
    scene_id: int
    start_time: float
    end_time: float
    content: SceneContent
    slice_ids: List[int]

class SliceRegrouperResponse(BaseModel):
    scenes: List[Scene]
    stats: Dict[str, Any]
    usage_report: Dict[str, Any]