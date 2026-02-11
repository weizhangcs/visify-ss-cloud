from typing import List, Optional, Literal, Dict, Any, Tuple
from enum import Enum
from pydantic import BaseModel, Field, model_validator

from ai_services.schemas.creative.asset_selector import SegmentSelection, DubbingSegment

class EditingActionType(str, Enum):
    USE_SLICE = "USE_SLICE"       # 使用现有切片 (可能涉及裁剪/变速)
    GENERATE = "GENERATE"         # 生成新素材 (Veo3)
    FREEZE_FRAME = "FREEZE_FRAME" # 定帧 (通常用于补足时长)
    EMPTY = "EMPTY"               # 留白 (无画面)

class EditingDecision(BaseModel):
    """
    [Output] 单个片段的剪辑决策指令
    """
    segment_index: int
    action: EditingActionType
    
    # --- USE_SLICE 参数 ---
    slice_id: Optional[int] = Field(None, description="Selected slice ID")
    source_range: Optional[Tuple[float, float]] = Field(None, description="(Start, End) time in the original slice")
    speed_rate: float = Field(1.0, description="Playback speed (1.0 = normal, 0.5 = slow)")
    
    # --- GENERATE 参数 ---
    generation_prompt: Optional[str] = Field(None, description="Prompt for video generation")
    
    # --- 通用参数 ---
    target_duration: float = Field(..., description="Required duration for this segment")
    reason: str = Field(..., description="Reason for this decision")

class EditingDirectorServiceParams(BaseModel):
    """Technical parameters"""
    # 策略阈值
    min_speed_rate: float = Field(0.5, description="Minimum allowed speed (slow motion limit)")
    max_speed_rate: float = Field(1.5, description="Maximum allowed speed (fast forward limit)")
    generation_threshold: float = Field(0.3, description="If source duration < 30% of target, trigger generation")

class EditingDirectorPayload(BaseModel):
    lang: str = Field("zh", description="Language code")
    mode: Literal["PROD", "DEBUG"] = Field("PROD", description="Operation mode")
    
    # Inputs
    dubbing_script: List[DubbingSegment] = Field(..., description="Original dubbing script with durations")
    selections: List[SegmentSelection] = Field(..., description="Candidates from Asset Selector")
    
    # Debug Params
    service_params: Optional[EditingDirectorServiceParams] = Field(default_factory=EditingDirectorServiceParams)

    @model_validator(mode='after')
    def check_consistency(self):
        # 简单校验索引一致性
        script_indices = {s.index for s in self.dubbing_script}
        selection_indices = {s.segment_index for s in self.selections}
        # 允许 selections 少于 script (未匹配到的情况)，但不应多出
        if not selection_indices.issubset(script_indices):
            raise ValueError("Selections contain indices not present in dubbing script.")
        return self

class EditingDirectorResponse(BaseModel):
    decisions: List[EditingDecision]
    stats: Dict[str, Any]