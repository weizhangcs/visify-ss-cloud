# task_manager/schemas.py
from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from .models import Task

class TaskCreateRequest(BaseModel):
    """
    任务创建请求 Schema
    """
    task_type: str = Field(..., description="任务类型 (e.g., GENERATE_NARRATION)")
    payload: Dict[str, Any] = Field(default_factory=dict, description="任务参数载荷")

    @field_validator('task_type')
    @classmethod
    def validate_task_type(cls, v: str) -> str:
        # 定义允许云端接收的任务白名单
        allowed = Task.TaskType.values
        if v not in allowed:
            raise ValueError(f"Invalid task_type: {v}. Allowed: {allowed}")
        return v

class TaskError(BaseModel):
    """
    任务执行异常信息 Schema
    """
    code: str = Field(..., description="错误码")
    message: str = Field(..., description="错误描述")
    details: Optional[Dict[str, Any]] = Field(None, description="详细错误上下文")

class TaskResponse(BaseModel):
    """
    任务详情返回 Schema
    """
    id: int
    status: str
    task_type: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[TaskError] = Field(None, description="任务执行失败时的异常信息")
    created: datetime
    modified: datetime
    download_url: Optional[str] = None # 自定义计算字段