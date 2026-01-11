from typing import List
from pydantic import BaseModel
from ai_services.schemas.refinery.slice_analyzer import SliceAnalysis

class LLMSliceAnalysisResult(BaseModel):
    """LLM 返回的单条分析结果"""
    slice_id: int
    analysis: SliceAnalysis

class BatchSliceAnalysisResponse(BaseModel):
    """LLM 返回的批处理结果"""
    results: List[LLMSliceAnalysisResult]