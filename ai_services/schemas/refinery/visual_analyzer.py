from typing import List, Optional, Literal, Dict, Any, Union
from enum import Enum
from pydantic import BaseModel, Field, model_validator, ConfigDict

class VisualFrameInput(BaseModel):
    frame_id: str = Field(..., description="Unique identifier for the frame")
    path: str = Field(..., description="GCS URI (gs://) or local path to the image")
    digest: Optional[str] = Field(None, description="Optional file digest")

class VisualAnalyzerServiceParams(BaseModel):
    """Technical parameters for DEBUG mode"""
    model: Optional[str] = Field(None, description="Gemini model name")
    batch_size: Optional[int] = Field(None, description="Batch size for processing")
    max_workers: Optional[int] = Field(None, description="Max concurrent workers")
    temperature: Optional[float] = Field(None, description="Temperature for LLM")
    max_retries: Optional[int] = Field(None, description="Max retries for LLM calls")

class VisualAnalyzerPayload(BaseModel):
    lang: str = Field("en", description="Language code for prompt and response")
    mode: Literal["PROD", "DEBUG"] = Field("PROD", description="Operation mode")
    
    # Data Source
    frames_file_path: Optional[str] = Field(None, description="Path to external JSON file containing frames list (Production)")
    frames: Optional[List[VisualFrameInput]] = Field(None, description="Direct list of frames (Debug/Small Batch)")
    
    # Debug Params
    service_params: Optional[VisualAnalyzerServiceParams] = Field(default_factory=VisualAnalyzerServiceParams)

    @model_validator(mode='after')
    def check_data_source(self):
        if not self.frames and not self.frames_file_path:
            raise ValueError("Either 'frames' or 'frames_file_path' must be provided.")
        
        if self.mode == "PROD":
            sp = self.service_params
            if sp and (sp.model or sp.batch_size or sp.max_workers or sp.temperature or sp.max_retries):
                raise ValueError("In PROD mode, technical parameters are not allowed in payload.")
        return self

class ShotType(str, Enum):
    EXTREME_CLOSE_UP = "extreme_close_up"
    CLOSE_UP = "close_up"
    MEDIUM_CLOSE_UP = "medium_close_up"
    MEDIUM_SHOT = "medium_shot"
    MEDIUM_LONG_SHOT = "medium_long_shot"
    LONG_SHOT = "long_shot"
    EXTREME_LONG_SHOT = "extreme_long_shot"
    ESTABLISHING_SHOT = "establishing_shot"
    OTHER = "other"

# 官方翻译映射表
SHOT_TYPE_LABELS = {
    "zh": {
        ShotType.EXTREME_CLOSE_UP: "大特写",
        ShotType.CLOSE_UP: "特写",
        ShotType.MEDIUM_CLOSE_UP: "近景",
        ShotType.MEDIUM_SHOT: "中景",
        ShotType.MEDIUM_LONG_SHOT: "中远景",
        ShotType.LONG_SHOT: "远景",
        ShotType.EXTREME_LONG_SHOT: "大远景",
        ShotType.ESTABLISHING_SHOT: "建立镜头",
        ShotType.OTHER: "其他"
    },
    "en": {
        ShotType.EXTREME_CLOSE_UP: "Extreme Close Up",
        ShotType.CLOSE_UP: "Close Up",
        ShotType.MEDIUM_CLOSE_UP: "Medium Close Up",
        ShotType.MEDIUM_SHOT: "Medium Shot",
        ShotType.MEDIUM_LONG_SHOT: "Medium Long Shot",
        ShotType.LONG_SHOT: "Long Shot",
        ShotType.EXTREME_LONG_SHOT: "Extreme Long Shot",
        ShotType.ESTABLISHING_SHOT: "Establishing Shot",
        ShotType.OTHER: "Other"
    }
}

class LabelItem(BaseModel):
    value: str
    label: str

class VisualAnalysisData(BaseModel):
    shot_type: Optional[LabelItem] = Field(None, description="Main shot size (Value + Label)")
    environment: Optional[str] = Field(None, description="Physical environment")
    subject: Optional[str] = None
    action: Optional[str] = None
    lighting_time: Optional[str] = Field(None, description="Time or lighting characteristics")
    visual_mood_tags: List[str] = Field(default_factory=list)
    
    model_config = ConfigDict(extra='allow')

class AnnotatedFrame(BaseModel):
    frame_id: str
    visual_analysis: VisualAnalysisData

class VisualAnalyzerResponse(BaseModel):
    annotated_frames: List[AnnotatedFrame]
    stats: Dict[str, Any]
    usage_report: Dict[str, Any]