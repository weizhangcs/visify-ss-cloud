# ai_services/schemas/refinery/dubbing_script_refiner.py

from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, model_validator

# --- Input Schemas ---

class AsrSegment(BaseModel):
    start: float
    end: float
    text: str

class OcrText(BaseModel):
    start_time: float
    end_time: float
    text: str
    avg_score: float

class DubbingScriptRefinerServiceParams(BaseModel):
    """Technical parameters for DEBUG mode"""
    model: Optional[str] = Field(None, description="LLM model name")
    temperature: Optional[float] = Field(None, description="Temperature for LLM")
    max_retries: Optional[int] = Field(None, description="Max retries")
    chunk_duration_seconds: Optional[int] = None
    chunk_overlap_seconds: Optional[int] = None
    alignment_tolerance_seconds: Optional[float] = None

class DubbingScriptRefinerPayload(BaseModel):
    """
    Corresponds to the payload.json file content.
    """
    lang: Literal["zh", "en"] = Field("zh", description="Language code for processing")
    mode: Literal["PROD", "DEBUG"] = Field("PROD", description="Operation mode")
    
    # 数据源 (互斥: PROD用文件路径, DEBUG可用直接数据)
    input_file_path: Optional[str] = Field(None, description="Path to the JSON file containing ASR and OCR data (PROD)")
    asr_segments: Optional[List[AsrSegment]] = Field(None, description="ASR results")
    ocr_texts: Optional[List[OcrText]] = Field(None, description="OCR results")

    service_params: Optional[DubbingScriptRefinerServiceParams] = Field(default_factory=DubbingScriptRefinerServiceParams)

    @model_validator(mode='after')
    def check_debug_params(self):
        # 1. 校验数据源
        if not self.input_file_path and (self.asr_segments is None or self.ocr_texts is None):
            raise ValueError("Either 'input_file_path' or both 'asr_segments' and 'ocr_texts' must be provided.")

        # 2. 校验 PROD 模式下的参数限制
        if self.mode == "PROD" and self.service_params and any(self.service_params.model_dump().values()):
            raise ValueError("In PROD mode, service_params are not allowed in payload.")
        return self

# --- Output Schemas ---

class RefinedSegment(BaseModel):
    start: float
    end: float
    original_asr: Optional[str]
    original_ocr: Optional[str]
    refined_text: Optional[str]
    source_of_truth: str # Keep as string to allow for future values from LLM
    reasoning: str
    confidence_score: Optional[float] = Field(None, description="Confidence score of the refinement (0.0-1.0)")

class Stats(BaseModel):
    processing_time_ms: int
    asr_segments_count: int
    ocr_texts_count: int
    refined_segments_count: int
    avg_confidence_score: Optional[float] = Field(None, description="Average confidence score across all segments")

class DubbingScriptRefinerResponse(BaseModel):
    refined_script: List[RefinedSegment]
    stats: Stats
    usage_report: Dict[str, Any]