from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict
from datetime import datetime


class TaskStatus(Enum):
    RUNNING = 1
    PENDING = 2  
    PAUSED = 3
    COMPLETED = 4
    CANCELLED = 5
    ERROR = 6

class ExecutionType(Enum):
    THREAD = "thread"
    COROUTINE = "coroutine"
    PROCESS = "process"
    SANDBOX = "sandbox"

@dataclass
class Task:
    """任务对象"""
    task_id: str
    priority: int              # 越小优先级越高
    config: Dict[str, Any]     # 任务配置
    type: ExecutionType = ExecutionType.THREAD
    status: TaskStatus = TaskStatus.PENDING
    is_resume: bool = False    # 是否是的恢复任务
    created_at: datetime = field(default_factory=datetime.now)

    # 用于优先队列比较
    def __lt__(self, other):
        if not isinstance(other, Task):
            return NotImplemented
        # 优先级相同，按创建时间先后
        return (self.priority, self.created_at) < (other.priority, other.created_at)