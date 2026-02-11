from typing import List
from pydantic import BaseModel, Field

class LLMSelectedCandidate(BaseModel):
    """LLM 返回的候选结果 (不含 duration，由代码补全)"""
    slice_id: int
    score: int = Field(..., description="Relevance score (1-10)")
    reason: str = Field(..., description="Reason for selection")

class LLMSegmentSelection(BaseModel):
    """LLM 返回的单段选择结果"""
    segment_index: int
    candidates: List[LLMSelectedCandidate]

class BatchSelectionResponse(BaseModel):
    """LLM 返回的批处理结果"""
    results: List[LLMSegmentSelection]