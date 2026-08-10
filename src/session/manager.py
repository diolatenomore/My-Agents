"""SessionManager — Session 的高级操作封装"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from src.session.models import (
    Session,
    filter_history_messages,
)
from src.session.store import SessionStore


class SessionManager:
    """会话管理器"""

    def __init__(self):
        self.store = SessionStore()
        self._locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def lock(self, session_id: str):
        """获取 session 级别的异步锁，确保同一 session 的读写串行化"""
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        async with self._locks[session_id]:
            yield

    async def get_session(self, session_id: str) -> Optional[Session]:
        return await self.store.get_session(session_id)

    async def delete(self, session_id: str):
        await self.store.delete_session(session_id)

    async def list_sessions(self, limit: int = 50, offset: int = 0) -> list[Session]:
        return await self.store.list_sessions(limit, offset)

    async def update_title(self, session_id: str, title: str):
        await self.store.update_title(session_id, title)

    # ========== 历史消息管理 ==========

    async def load_display_history(self, session_id: str) -> list[dict]:
        """加载原始会话历史，返回 dict 列表"""
        msg_dicts = await self.store.get_display_messages(session_id)
        return filter_history_messages(msg_dicts)

    async def get_context_tokens(self, session_id: str) -> int:
        """获取会话上次持久化的上下文 token 数"""
        session = await self.store.get_session(session_id)
        return session.context_tokens if session else 0

    async def update_context_tokens(self, session_id: str, tokens: int):
        """更新会话的上下文 token 数"""
        await self.store.update_context_tokens(session_id, tokens)

    # ========== 上下文消息（context_messages）管理 ==========

    async def load_context_messages(self, session_id: str) -> list[dict]:
        """加载 API 上下文消息列表（可能已压缩）"""
        return await self.store.load_context_messages(session_id)

    async def get_context_message_count(self, session_id: str) -> int:
        """获取上下文消息总数"""
        return await self.store.get_context_message_count(session_id)

    async def append_context_messages(self, session_id: str, msg_dicts: list[dict]):
        """追加消息到上下文表（自动跳过 system 消息）"""
        await self.store.append_context_messages(session_id, msg_dicts)

    async def overwrite_context_messages(self, session_id: str, msg_dicts: list[dict]):
        """全量覆盖上下文消息（压缩后使用）"""
        await self.store.overwrite_context_messages(session_id, msg_dicts)

    async def save_display_messages(self, session_id: str, messages: list[dict]):
        """保存 Agent 执行完后新增的 display 消息到数据库

        跳过 role=system 的消息（每次重建，不存储）。
        去重：只保存超出已存储数量的新消息。
        """
        # 获取当前已存消息数（轻量 COUNT，不加载全部消息内容）
        existing = await self.store.count_display_messages(session_id)
        new_msgs = messages[existing:]

        if new_msgs:
            await self.store.append_display_messages(session_id, new_msgs)
