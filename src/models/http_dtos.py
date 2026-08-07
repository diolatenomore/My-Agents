from typing import Optional

from pydantic import BaseModel, Field

from src.models.task import Priority


class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None  # 前端传，不传则后端生成
    model_id: Optional[str] = None  # 模型配置 ID，不传则使用默认模型


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


class MemoryItemDTO(BaseModel):
    id: str
    memory_type: str          # "preference" | "fact" | "identity"
    value: str
    key: str = ""
    session_id: str = ""
    created_at: str = ""


class UpdateMemoryRequest(BaseModel):
    value: str
    key: str = ""


# ========== 模型配置 DTO ==========

class CreateModelRequest(BaseModel):
    name: str
    base_url: str
    model: str
    api_key: str
    max_context_tokens: Optional[int] = Field(default=200000, description="上下文窗口 token 上限")
    max_output_tokens: Optional[int] = Field(default=64000, description="单次输出最大 token 数")
    max_tool_calls: Optional[int] = Field(default=50, description="单次对话最大工具调用次数")


class UpdateModelRequest(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    max_context_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    max_tool_calls: Optional[int] = None


class ModelConfigDTO(BaseModel):
    id: str
    name: str
    base_url: str
    model: str
    env_var_name: str
    is_active: int = 1
    max_context_tokens: int = 200000
    max_output_tokens: int = 64000
    max_tool_calls: int = 50
    created_at: str = ""
    updated_at: str = ""
