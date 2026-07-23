"""MemoryService — 长期记忆的提取、检索、格式化编排"""

import threading
from typing import Optional

from src.memory.models import MemoryItem
from src.memory.store import MemoryStore
from src.memory.extraction import extract_memories
from src.config import MEMORY_EXTRACTION_INTERVAL
from src.utils.common import logger


class MemoryService:
    """长期记忆服务：编排提取和检索流程。

    用法：
        # 对话结束后，fire-and-forget:
        asyncio.create_task(service.extract_from_messages(session_id, query, response))

        # 对话开始前，检索相关记忆:
        block = service.retrieve(query)
    """

    def __init__(self, store: MemoryStore):
        self.store = store
        self.enabled = True
        self._extraction_rounds: dict[str, int] = {}
        self._extraction_interval = MEMORY_EXTRACTION_INTERVAL

    def should_extract(self, session_id: str) -> bool:
        """检查是否需要对 session 执行记忆提取（按轮次间隔控制）。"""
        counter = self._extraction_rounds.get(session_id, 0) + 1
        self._extraction_rounds[session_id] = counter
        if counter < self._extraction_interval:
            return False
        self._extraction_rounds[session_id] = 0
        return True

    async def extract_from_messages(
        self, session_id: str, messages: list[dict], model_id: str
    ) -> None:
        """审阅完整对话历史，提取记忆并写入 ChromaDB（fire-and-forget）。

        将完整消息列表作为上下文送给 LLM，LLM 审阅后决定哪些值得记住。
        调用者应用 asyncio.create_task 包装，不阻塞主流程。
        """
        if not self.enabled:
            return

        try:
            items = await extract_memories(messages, model_id)
            if not items:
                return

            memory_items = [MemoryItem(
                memory_type=item["type"],
                key=item.get("key", ""),
                value=item["value"],
            ) for item in items]

            added = self.store.add(memory_items, session_id)
            if added > 0:
                logger.info(
                    f"MemoryService: 提取 {added} 条记忆 "
                    f"(session={session_id[:8]}...)"
                )

        except Exception as e:
            logger.warning(f"MemoryService 提取失败: {e}")

    def list_memories(self, limit: int = 20, offset: int = 0,
                      memory_type: str | None = None) -> tuple[list[dict], int]:
        """分页列出记忆"""
        return self.store.list_all(limit, offset, memory_type)

    def update_memory(self, memory_id: str, value: str, key: str = "") -> bool:
        """更新记忆"""
        return self.store.update(memory_id, value, key)

    def get_static_block(self) -> str:
        """获取静态记忆区块（preference），注入 system prompt"""
        if not self.enabled:
            return ""
        try:
            prefs = self.store.get_preferences()
            return _format_preference_block(prefs)
        except Exception as e:
            logger.warning(f"获取静态记忆失败: {e}")
            return ""

    def get_dynamic_block(self, query: str, n_results: int = 5) -> str:
        """获取动态记忆区块（semantic），按 query 检索，注入 user message"""
        if not self.enabled or not query or not query.strip():
            return ""
        try:
            facts = self.store.query(query, n_results=n_results)
            return _format_semantic_block(facts)
        except Exception as e:
            logger.warning(f"获取动态记忆失败: {e}")
            return ""


def _format_preference_block(prefs: list[dict]) -> str:
    """格式化偏好为 system prompt 区块"""
    if not prefs:
        return ""
    parts = ["## 用户偏好（始终遵循）"]
    for p in prefs:
        key = p.get("key", "")
        value = p.get("value", "")
        if key:
            parts.append(f"- **{key}**: {value}")
        else:
            parts.append(f"- {value}")
    return "\n".join(parts) + "\n"


def _format_semantic_block(facts: list[dict]) -> str:
    """格式化语义记忆为 user message 补充区块"""
    if not facts:
        return ""
    parts = ["以下是你可能需要的用户相关信息："]
    for f in facts:
        value = f.get("value", "")
        if value:
            parts.append(f"- {value}")
    return "\n".join(parts)


# ============ 模块级单例（懒加载） ============

_memory_service: Optional[MemoryService] = None
_memory_service_lock = threading.Lock()


def get_memory_service() -> MemoryService:
    """获取 MemoryService 单例，线程安全，懒加载

    首次调用时自动读取配置初始化，后续复用同一实例。
    """
    global _memory_service
    if _memory_service is not None:
        return _memory_service
    with _memory_service_lock:
        if _memory_service is None:
            from src.config import MEMORY_PERSIST_DIR
            store = MemoryStore(persist_dir=MEMORY_PERSIST_DIR)
            _memory_service = MemoryService(store)
        return _memory_service
