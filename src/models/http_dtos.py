from typing import Optional

from pydantic import BaseModel, Field

from src.models.task import Priority


class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None  # 前端传，不传则后端生成
    model_id: Optional[str] = None  # 模型配置 ID，不传则使用默认模型
    project_id: Optional[str] = None  # 项目 ID，仅新会话首条消息时生效（归属后不变）


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
    project_id: Optional[str] = None


# ========== 项目 DTO ==========

class ProjectDTO(BaseModel):
    project_id: str
    name: str
    work_dir: str
    session_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., description="项目名称")
    work_dir: str = Field(..., description="工作目录的绝对路径")


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    work_dir: Optional[str] = None


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
    temperature: Optional[float] = Field(default=0.7, description="采样温度")
    max_iterations: Optional[int] = Field(default=30, description="ReAct 最大迭代次数")
    think: Optional[bool] = Field(default=True, description="是否启用 DeepSeek 思考模式")
    reasoning_effort: Optional[str] = Field(default=None, description="OpenAI 推理强度: low/medium/high")
    approval_timeout: Optional[int] = Field(default=120, description="审批等待超时秒数，None 或 0 表示无限等待")
    approval_timeout_auto_approve: bool = Field(default=False, description="超时后是否自动通过")


class UpdateModelRequest(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    max_context_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    max_tool_calls: Optional[int] = None
    temperature: Optional[float] = None
    max_iterations: Optional[int] = None
    think: Optional[bool] = None
    reasoning_effort: Optional[str] = None
    approval_timeout: Optional[int] = None
    approval_timeout_auto_approve: Optional[bool] = None


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
    temperature: float = 0.7
    max_iterations: int = 30
    think: int = 1
    reasoning_effort: Optional[str] = None
    approval_timeout: Optional[int] = 120
    approval_timeout_auto_approve: bool = False
    created_at: str = ""
    updated_at: str = ""
