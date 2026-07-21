"""记忆工具 — LLM 可在对话过程中读写长期记忆

提供 query_memory（检索）和 save_to_memory（保存）两个工具。
利用 contextvar 中的 task_id 作为 session_id，无需额外传参。
"""

from pydantic import BaseModel, Field

from src.tools.registry import registry
from src.memory.models import MemoryItem
from src.memory.service import get_memory_service
from src.vfs.task_context import get_current_task_id


class QueryMemoryInput(BaseModel):
    query: str = Field(
        description="搜索文本，支持自然语言。如：'用户叫什么'、'用户常用的技术栈'"
    )
    memory_type: str = Field(
        default="all",
        description="类型过滤：all（全部）、preference（偏好/习惯）、semantic（事实）",
    )
    n_results: int = Field(default=3, description="返回结果数，默认 3")


class SaveToMemoryInput(BaseModel):
    memory_type: str = Field(
        description="记忆类型：preference（偏好/习惯）或 semantic（客观事实）"
    )
    value: str = Field(
        description="记忆内容，一句完整可理解的描述，不超过 100 字"
    )
    key: str = Field(
        default="",
        description="仅 preference 类型需要，简短英文 snake_case 键名，如 language、response_style",
    )


async def query_memory(query: str, memory_type: str = "all", n_results: int = 5) -> str:
    """检索长期记忆"""
    service = get_memory_service()
    if not service.enabled:
        return "记忆服务未启用"

    try:
        results = service.store.query(query, n_results=n_results, memory_type=memory_type)
    except Exception:
        return "查询记忆时出错"

    if not results:
        return "没有找到相关记忆"

    lines = []
    for r in results:
        t = r.get("memory_type", "")
        key = r.get("key", "")
        value = r.get("value", "")
        if t == "preference" and key:
            lines.append(f"- **{key}**: {value}")
        else:
            lines.append(f"- {value}")

    return "\n".join(lines)


async def save_to_memory(memory_type: str, value: str, key: str = "") -> str:
    """保存一条记忆到长期存储"""
    if memory_type not in ("preference", "semantic"):
        return f"错误：不支持的记忆类型 '{memory_type}'，请使用 preference 或 semantic"

    if memory_type == "preference" and not key:
        return "错误：preference 类型必须提供 key 字段"

    item = MemoryItem(memory_type=memory_type, value=value, key=key)
    session_id = get_current_task_id()

    added = get_memory_service().store.add([item], session_id)
    if added > 0:
        return f"已保存记忆 [{memory_type}]: {value}"
    return f"跳过（已存在相似记忆）: {value}"


# ============ 注册工具 ============

registry.register(
    name="query_memory",
    description=(
        "检索长期记忆中关于用户的偏好和事实。当你需要了解用户的背景、习惯、"
        "偏好、项目信息，而上下文中却没有这些信息时使用。"
    ),
    handler=query_memory,
    args_schema=QueryMemoryInput,
)

registry.register(
    name="save_memory",
    description=(
        "保存一条信息到长期记忆，当且仅当这条信息值得记住时调用。比如当你了解到用户的偏好、习惯、身份、"
        "项目信息、过往经历等等内容。preference 用于偏好/习惯（必须指定 key），"
        "semantic 用于客观事实。"
    ),
    handler=save_to_memory,
    args_schema=SaveToMemoryInput,
)
