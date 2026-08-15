"""TODO 任务管理工具 — 支持 Plan-and-Execute 模式

提供 todo 工具让 LLM 在执行复杂任务前先规划，在执行过程中追踪进度。
TodoStore 为纯内存存储，通过对话历史间接持久化。
"""

import json
from typing import List, Optional

from pydantic import BaseModel, Field

from src.tools.registry import registry

# ========== 数据模型 ==========

class TodoItem(BaseModel):
    """单条 TODO 项"""
    id: str = Field(description="唯一标识符，如 'task-1'、'task-2'")
    content: str = Field(description="任务描述，一句话概括。")
    status: str = Field(
        default="pending",
        description="当前状态",
        enum=["pending", "in_progress", "completed", "cancelled"],
    )


class TodoInput(BaseModel):
    """todo 工具输入参数"""
    todos: Optional[List[TodoItem]] = Field(
        default=None,
        description="要写入的任务列表。不传则只读取当前列表。",
    )
    merge: bool = Field(
        default=False,
        description="true: 按 id 增量更新已有项并追加新项；false: 全量替换整个列表",
    )


# ========== TodoStore ==========

class TodoStore:
    """纯内存任务列表，仿 Hermes 的 TodoStore 实现

    状态流转：
        pending ──→ in_progress ──→ completed
           │              │
           └──────────────┴──→ cancelled
    """

    def __init__(self):
        self._items: List[dict] = []

    def read(self) -> dict:
        """读取当前 Todo 列表并返回统计摘要"""
        todos = list(self._items)  # 浅拷贝
        return {"todos": todos}

    def write(self, todos: List[dict], merge: bool = False) -> dict:
        """写入 Todo 列表

        Args:
            todos: 要写入的 Todo 项列表
            merge: false=全量替换，true=按 id 增量更新

        Returns:
            {"todos": [...]}
        """
        if merge:
            # 按 id 增量更新
            existing_map = {item["id"]: item for item in self._items}
            for new_item in todos:
                item_id = new_item["id"]
                if new_item.get("status") == "cancelled":
                    # cancelled → 直接删除
                    existing_map.pop(item_id, None)
                elif item_id in existing_map:
                    # 已存在 → 只更新传了的字段
                    existing_map[item_id].update(new_item)
                else:
                    # 新 id → 追加
                    self._items.append(new_item)
        else:
            # 全量替换（过滤掉 cancelled 项）
            self._items = [dict(item) for item in todos if item.get("status") != "cancelled"]

        return self.read()

    def restore_from_json(self, json_str: str) -> bool:
        """从 JSON 字符串恢复状态（用于 hydration）"""
        try:
            data = json.loads(json_str)
            todos = data.get("todos", [])
            if todos:
                self._items = todos
                return True
        except (json.JSONDecodeError, TypeError):
            pass
        return False


# ========== 工具处理函数 ==========

async def _handle_todo(
    todos: Optional[List[dict]] = None,
    merge: bool = False,
    _todo_store: Optional[TodoStore] = None,
) -> str:
    """todo 工具处理函数

    内部参数 _todo_store 由 react_loop 注入，不作为工具 input schema。
    """
    if _todo_store is None:
        return json.dumps(
            {"error": "TODO store 不可用，子智能体不支持任务规划"},
            ensure_ascii=False,
        )

    if todos is None:
        # 读取模式
        result = _todo_store.read()
    else:
        # 写入模式
        result = _todo_store.write(todos, merge=merge)

    return json.dumps(result, ensure_ascii=False)


# ========== 工具注册 ==========

registry.register(
    name="todo",
    description=(
        "管理当前会话的任务列表。用于复杂任务（3 个以上步骤）或用户提供了多个任务时。"
        "不传参数则读取当前列表。\n\n"
        "写入：\n"
        "- 提供 'todos' 数组来创建/更新任务项\n"
        "- merge=false：全量替换整个列表为新计划\n"
        "- merge=true：按 id 增量更新已有项，自动追加新项\n\n"
        "若某项失败或不再需要，将其标记为 cancelled，该项会被自动删除。\n\n"
        "每次调用都返回完整的当前列表。"
    ),
    handler=_handle_todo,
    args_schema=TodoInput,
    requires_approval=False,
)