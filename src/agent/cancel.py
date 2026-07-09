"""CancelRegistry — 管理每个 session 的取消信号"""

import asyncio


class CancelRegistry:
    """取消注册表，为每个 session 提供可外部触发的 asyncio.Event"""

    def __init__(self):
        self._events: dict[str, asyncio.Event] = {}

    def create(self, session_id: str) -> asyncio.Event:
        """为 session 创建取消事件"""
        event = asyncio.Event()
        self._events[session_id] = event
        return event

    def request_cancel(self, session_id: str):
        """请求取消指定 session 的流式对话"""
        event = self._events.get(session_id)
        if event:
            event.set()

    def clear(self, session_id: str):
        """清除 session 的取消事件"""
        self._events.pop(session_id, None)
