from typing import List
from pydantic import BaseModel, Field

# --- LLM Interaction Schemas (Instruction-Based) ---
# These are internal implementation details, not exposed in the public API.

class MergeInstruction(BaseModel):
    """A single instruction from the LLM on how to merge a group of subtitles."""
    original_indices: List[int] = Field(..., description="A list of original subtitle indices that should be merged into one.")
    new_content: str = Field(..., description="The new, merged, and punctuated content for this group.")

class MergePlanResponse(BaseModel):
    """The complete merge plan for a batch, as returned by the LLM."""
    merge_plan: List[MergeInstruction]