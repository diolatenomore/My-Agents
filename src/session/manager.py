"""SessionManager — Session 的高级操作封装"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from langchain_core.messages import BaseMessage, SystemMessage

from src.session.models import (
    Session,
    message_to_dict,
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

    async def load_history(self, session_id: str) -> list[BaseMessage]:
        """加载会话历史，返回 LangChain 消息列表（供 Agent 注入）"""
        msg_dicts = await self.store.get_messages(session_id)
        return filter_history_messages(msg_dicts)

    async def save_messages(self, session_id: str, messages: list[BaseMessage]):
        """保存 Agent 执行完后新增的消息到数据库

        跳过 SystemMessage（每次重建），去重：只保存超出已存储数量的新消息。
        """
        # 获取当前已存消息数（轻量 COUNT，不加载全部消息内容）
        existing = await self.store.count_messages(session_id)

        # 剔除 SystemMessage（每次重建，不存储），再切出新增部分
        non_system_msgs = [m for m in messages if not isinstance(m, SystemMessage)]
        new_msgs = non_system_msgs[existing:]

        if new_msgs:
            new_msg_dicts = [message_to_dict(m) for m in new_msgs]
            await self.store.append_messages(session_id, new_msg_dicts)
