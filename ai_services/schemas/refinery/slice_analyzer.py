from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, model_validator


# ==============================================================================
# 1. 输入侧 Schemas (MultimodalSlice - Local Copy for Isolation)
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


class MultimodalSlice(BaseModel):
    """
    [Input] 多模态切片输入。
    """
    slice_id: int
    start_time: float
    end_time: float
    type: str
    text_contents: List[SubtitleItem] = Field(default_factory=list)
    visual_contents: List[FrameDataInput] = Field(default_factory=list)
    model_config = ConfigDict(extra='ignore')


# ==============================================================================
# 2. 输出侧 Schemas (Slice Analysis)
# ==============================================================================

class SliceAnalysis(BaseModel):
    narrative_summary: str = Field(..., description="Summary of the narrative content (dialogue/action).")
    visual_summary: str = Field(..., description="Summary of visual elements (shot/lighting/composition).")
    tags: List[str] = Field(default_factory=list,
                            description="Semantic tags (e.g. Reaction_Shot, Close_Up, Emotional).")


class AnalyzedSlice(BaseModel):
    slice_id: int
    slice_analysis: SliceAnalysis


class SliceAnalyzerResponse(BaseModel):
    analyzed_slices: List[AnalyzedSlice]
    stats: Dict[str, Any]
    usage_report: Dict[str, Any]


# ==============================================================================
# 3. 任务 Payload
# ==============================================================================

class SliceAnalyzerServiceParams(BaseModel):
    """Technical parameters for DEBUG mode"""
    model: Optional[str] = Field(None, description="LLM model name")
    batch_size: Optional[int] = Field(None, description="Slices per batch")
    temperature: Optional[float] = Field(None, description="Temperature for LLM")
    max_retries: Optional[int] = Field(None, description="Max retries")


class SliceAnalyzerPayload(BaseModel):
    lang: str = Field("zh", description="Language code")
    mode: Literal["PROD", "DEBUG"] = Field("PROD", description="Operation mode")

    # Data Source
    slices_file_path: Optional[str] = Field(None, description="Path to the rich slices JSON file (Production)")
    slices: Optional[List[MultimodalSlice]] = Field(None, description="Direct list of slices (Debug)")

    # Debug Params
    service_params: Optional[SliceAnalyzerServiceParams] = Field(default_factory=SliceAnalyzerServiceParams)

    @model_validator(mode='after')
    def check_data_source(self):
        if not self.slices and not self.slices_file_path:
            raise ValueError("Either 'slices' or 'slices_file_path' must be provided.")

        if self.mode == "PROD":
            sp = self.service_params
            if sp and (sp.model or sp.batch_size or sp.temperature or sp.max_retries):
                raise ValueError("In PROD mode, technical parameters are not allowed in payload.")
        return self