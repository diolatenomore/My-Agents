"""MemoryService — 长期记忆的提取、检索、格式化编排"""

import threading
from typing import Optional

from src.memory.models import MemoryItem
from src.memory.store import MemoryStore
from src.memory.extraction import extract_memories
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

    async def extract_from_messages(
        self, session_id: str, query: str, response: str
    ) -> None:
        """从单轮对话中提取记忆并写入 ChromaDB（fire-and-forget）。

        只分析当前轮次的 query + response，增量积累。
        调用者应用 asyncio.create_task 包装，不阻塞主流程。
        """
        if not self.enabled:
            return

        try:
            items = await extract_memories(query, response)
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

    def retrieve(self, query: str, n_results: int = 5) -> str:
        """检索相关记忆，格式化为 system prompt 注入文本。

        Args:
            query: 用户当前消息
            n_results: 语义搜索返回的最大 fact 数

        Returns:
            markdown 格式的记忆区块，无可检索内容时返回 ""
        """
        if not self.enabled or not query or not query.strip():
            return ""

        try:
            prefs = self.store.get_preferences()
            facts = self.store.query(query, n_results=n_results)
            return _format_memory_block(prefs, facts)
        except Exception as e:
            logger.warning(f"MemoryService 检索失败: {e}")
            return ""


def _format_memory_block(prefs: list[dict], facts: list[dict]) -> str:
    """将偏好和事实格式化为 system prompt 区块"""
    parts = ["## 长期记忆"]

    if prefs:
        parts.append("### 用户偏好（始终遵循）")
        for p in prefs:
            key = p.get("key", "")
            value = p.get("value", "")
            if key:
                parts.append(f"- **{key}**: {value}")
            else:
                parts.append(f"- {value}")

    if facts:
        parts.append("### 相关历史信息")
        for f in facts:
            value = f.get("value", "")
            if value:
                parts.append(f"- {value}")

    if len(parts) == 1:  # 只有标题
        return ""

    return "\n".join(parts) + "\n"


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
