from typing import Optional

from pydantic import BaseModel, Field

from src.models.task import Priority


class ChatRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    code: int
    message: str
    type: str

class GetTaskStatusResponse(BaseModel):
    code: int
    status: str
    result: Optional[str]

class UpdateTaskPriorityRequest(BaseModel):
    priority: Priority = Field(..., ge=0, le=4, description="任务优先级，0-4之间的整数，数值越小优先级越高")

class TaskChangeResponse(BaseModel):
    code: int
    message: str

class TaskManagerStatus(BaseModel):
    running: bool
    max_workers: int
    pending_tasks: int
    paused_tasks: int
    active_workers: int

class GetStatsResponse(BaseModel):
    code: int
    data: TaskManagerStatus