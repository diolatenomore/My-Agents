from typing import Optional

from pydantic import BaseModel, Field

from src.models.task import Priority


class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None  # 前端传，不传则后端生成


class ChatResponse(BaseModel):
    code: int
    message: str
    type: str
    session_id: Optional[str] = None  # 后端返回，前端需保存后续使用
    review_tree: Optional[dict] = None  # merge 后的审批树，无文件变更时为 None


class SessionDTO(BaseModel):
    session_id: str
    title: str = ""
    message_count: int = 0
    created_at: str = ""
    updated_at: str = ""


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
