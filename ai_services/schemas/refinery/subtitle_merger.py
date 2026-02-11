from typing import List, Optional, Literal
from pydantic import BaseModel, Field, model_validator

class SubtitleItem(BaseModel):
    index: int = Field(..., description="Original subtitle index")
    id: Optional[str] = Field(None, description="UUID for tracking the subtitle line")
    start_time: float = Field(..., description="Start time in seconds")
    end_time: float = Field(..., description="End time in seconds")
    content: str = Field(..., description="Subtitle text content")

class SubtitleMergerServiceParams(BaseModel):
    """技术参数封装"""
    model: Optional[str] = Field(None, description="LLM model name")
    batch_size: Optional[int] = Field(None, description="Batch size for processing")
    temperature: Optional[float] = Field(None, description="Temperature for LLM")
    max_retries: Optional[int] = Field(None, description="Max retries for LLM calls")

class SubtitleMergerPayload(BaseModel):
    lang: str = Field("zh", description="Language code (zh, en)")
    mode: Literal["PROD", "DEBUG"] = Field("PROD",description="运行模式: PROD 使用配置中心模型, DEBUG 允许载荷指定模型")
    service_params: Optional[SubtitleMergerServiceParams] = Field(default_factory=SubtitleMergerServiceParams, description="Technical parameters (Debug mode overrides)")
    subtitles: Optional[List[SubtitleItem]] = Field(None, description="List of subtitles to process (Debug)")
    subtitle_file_path: Optional[str] = Field(None,description="Path to external JSON file containing subtitles (Production)")

    @model_validator(mode='after')
    def check_data_source(self):
        if not self.subtitles and not self.subtitle_file_path:
            raise ValueError("Either 'subtitles' or 'subtitle_file_path' must be provided.")
        # [架构升级] 校验模型参数
        if self.mode == "PROD":
            sp = self.service_params
            if sp and (sp.model or sp.batch_size or sp.temperature or sp.max_retries):
                raise ValueError(
                    "In PROD mode, technical parameters (service_params) are not allowed in payload. They are sourced from config.")

        return self

class MergedSubtitleItem(BaseModel):
    id: Optional[str] = Field(None, description="UUID for the merged subtitle line")
    index: int
    start_time: float
    end_time: float
    content: str
    original_indices: List[int] = Field(default_factory=list, description="List of original indices merged into this item")

class SubtitleMergerResponse(BaseModel):
    merged_subtitles: List[MergedSubtitleItem]
    stats: dict
    usage_report: dict