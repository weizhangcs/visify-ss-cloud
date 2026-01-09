from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, model_validator, ConfigDict

class AudioAnalysis(BaseModel):
    gender: str = Field("Unknown", description="Predicted gender: Male, Female, or Unknown")
    # 允许额外的字段存在但不校验，以保持兼容性
    model_config = ConfigDict(extra='ignore')

class SubtitleItem(BaseModel):
    index: int = Field(..., description="Original subtitle index")
    start_time: float = Field(..., description="Start time in seconds")
    end_time: float = Field(..., description="End time in seconds")
    content: str = Field(..., description="Subtitle text content")
    # 多模态输入：声学特征分析
    audio_analysis: Optional[AudioAnalysis] = Field(None, description="Acoustic analysis data")

class CharacterIdentifierServiceParams(BaseModel):
    """Technical parameters for DEBUG mode"""
    model: Optional[str] = Field(None, description="LLM model name")
    batch_size: Optional[int] = Field(None, description="Batch size for processing")
    temperature: Optional[float] = Field(None, description="Temperature for LLM")
    max_retries: Optional[int] = Field(None, description="Max retries for LLM calls")

class CharacterIdentifierPayload(BaseModel):
    lang: str = Field("zh", description="Language code")
    mode: Literal["PROD", "DEBUG"] = Field("PROD", description="Operation mode")

    # 业务上下文
    known_characters: List[str] = Field(default_factory=list, description="Known VIP characters")
    video_title: Optional[str] = Field(None, description="Video title for context")

    # 数据源 (互斥)
    subtitle_file_path: Optional[str] = Field(None, description="Path to subtitle file (PROD)")
    subtitles: Optional[List[SubtitleItem]] = Field(None, description="Direct subtitle list (DEBUG)")

    # 调试参数
    service_params: Optional[CharacterIdentifierServiceParams] = Field(default_factory=CharacterIdentifierServiceParams)

    @model_validator(mode='after')
    def check_data_source(self):
        if not self.subtitles and not self.subtitle_file_path:
            raise ValueError("Either 'subtitles' or 'subtitle_file_path' must be provided.")

        if self.mode == "PROD":
            sp = self.service_params
            if sp and (sp.model or sp.batch_size or sp.temperature or sp.max_retries):
                raise ValueError("In PROD mode, technical parameters are not allowed in payload.")
        return self

class IdentifiedSubtitleItem(BaseModel):
    """识别结果项"""
    index: int
    speaker: str
    reasoning: Optional[str] = None

class CharacterIdentifierResponse(BaseModel):
    identified_subtitles: List[IdentifiedSubtitleItem]
    stats: Dict[str, Any]
    usage_report: Dict[str, Any]