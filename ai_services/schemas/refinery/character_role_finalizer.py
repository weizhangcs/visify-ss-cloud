# ai_services/schemas/refinery/character_role_finalizer.py
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, model_validator

# --- Input Schemas ---

class InputSegment(BaseModel):
    """来自 Edge 侧 Fusion 算子的输入片段"""
    start: float
    end: float
    refined_text: Optional[str]
    speaker: Optional[str] = Field(None, description="Physical speaker ID (e.g., PERSON_00)")
    fusion_score: Optional[float] = Field(None, description="Confidence score from physical fusion")
    # 允许透传其他字段
    original_asr: Optional[str] = None
    original_ocr: Optional[str] = None

class CharacterRoleFinalizerServiceParams(BaseModel):
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_retries: Optional[int] = None

class CharacterRoleFinalizerPayload(BaseModel):
    lang: Literal["zh", "en"] = "zh"
    mode: Literal["PROD", "DEBUG"] = "PROD"
    
    # 数据源 (互斥: PROD用文件路径, DEBUG可用直接数据)
    input_file_path: Optional[str] = Field(None, description="Path to the JSON file containing segments data (PROD)")
    segments: Optional[List[InputSegment]] = Field(None, description="List of script segments with physical speaker IDs")
    
    service_params: Optional[CharacterRoleFinalizerServiceParams] = Field(default_factory=CharacterRoleFinalizerServiceParams)

    @model_validator(mode='after')
    def check_params(self):
        # 1. 校验数据源
        if not self.input_file_path and self.segments is None:
            raise ValueError("Either 'input_file_path' or 'segments' must be provided.")

        # 2. 校验 PROD 模式下的参数限制
        if self.mode == "PROD" and self.service_params and any(self.service_params.model_dump().values()):
            raise ValueError("In PROD mode, service_params are not allowed in payload.")
        return self

# --- Output Schemas ---

class FinalizedSegment(BaseModel):
    start: float
    end: float
    text: str
    speaker_id: str = Field(..., description="Corrected Speaker ID (e.g., PERSON_00)")
    character_name: Optional[str] = Field(None, description="Normalized Character Name (e.g., 安然)")
    reasoning: Optional[str] = Field(None, description="Reason for correction if changed")

class CharacterMapItem(BaseModel):
    speaker_id: str
    name: str
    aliases: List[str] = Field(default_factory=list, description="Detected aliases (e.g., 安总, 安然小姐)")

class Stats(BaseModel):
    processing_time_ms: int
    total_segments: int
    corrected_segments_count: int

class CharacterRoleFinalizerResponse(BaseModel):
    finalized_script: List[FinalizedSegment]
    character_map: List[CharacterMapItem]
    stats: Stats
    usage_report: Dict[str, Any]