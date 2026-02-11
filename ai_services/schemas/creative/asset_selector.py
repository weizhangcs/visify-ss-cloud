from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, model_validator

# 引用 Refinery 的产出作为输入
from ai_services.schemas.refinery.slice_regrouper import MultimodalSlice

class DubbingSegment(BaseModel):
    """
    [Input] 单段解说词/配音片段
    """
    index: int
    text: str
    duration: float
    semantic_requirements: List[str] = Field(default_factory=list, description="预定义的语义需求标签")
    ref_scene_id: Optional[int] = Field(None, description="关联的源场景ID (如果有)")

class AssetSelectorServiceParams(BaseModel):
    """Technical parameters for DEBUG mode"""
    model: Optional[str] = Field(None, description="LLM model name")
    temperature: Optional[float] = Field(None, description="Temperature for LLM")
    max_retries: Optional[int] = Field(None, description="Max retries")
    top_k: int = Field(5, description="Number of candidates to select per segment")

class AssetSelectorPayload(BaseModel):
    lang: str = Field("zh", description="Language code")
    mode: Literal["PROD", "DEBUG"] = Field("PROD", description="Operation mode")
    
    # Inputs
    dubbing_script: List[DubbingSegment] = Field(..., description="List of narration segments")
    
    # Asset Inventory (Refinery Output)
    slices_file_path: Optional[str] = Field(None, description="Path to slices JSON file (Production)")
    slices: Optional[List[MultimodalSlice]] = Field(None, description="Direct list of slices (Debug)")
    
    # Debug Params
    service_params: Optional[AssetSelectorServiceParams] = Field(default_factory=AssetSelectorServiceParams)

    @model_validator(mode='after')
    def check_data_source(self):
        if not self.slices and not self.slices_file_path:
            raise ValueError("Either 'slices' or 'slices_file_path' must be provided.")
        
        if self.mode == "PROD":
            sp = self.service_params
            if sp and (sp.model or sp.temperature or sp.max_retries):
                raise ValueError("In PROD mode, technical parameters are not allowed in payload.")
        return self

class SelectedCandidate(BaseModel):
    slice_id: str = Field(..., description="Slice UUID")
    score: int = Field(..., description="Relevance score (1-10)")
    reason: str = Field(..., description="Reason for selection")
    duration: float = Field(..., description="Duration of the slice in seconds")

class SegmentSelection(BaseModel):
    segment_index: int
    candidates: List[SelectedCandidate]

class AssetSelectorResponse(BaseModel):
    selections: List[SegmentSelection]
    stats: Dict[str, Any]
    usage_report: Dict[str, Any]