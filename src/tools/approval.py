"""ApprovalRegistry — 管理工具执行前的审批等待

仿照 CancelRegistry 的 asyncio.Event 模式：
后端暂停执行，等待前端用户审批决策，通过 asyncio.Event 实现阻塞-唤醒。
"""

import asyncio


class ApprovalRegistry:
    """管理工具执行前的审批等待"""

    def __init__(self):
        self._events: dict[str, asyncio.Event] = {}   # key = "{session_id}:{tool_call_id}"
        self._decisions: dict[str, bool] = {}          # True=approved, False=rejected
        self._threshold_raises: dict[str, int] = {}    # session_id → 累计提升量（临时，不持久化）

    def create(self, session_id: str, tool_call_id: str) -> asyncio.Event:
        """创建审批等待事件"""
        key = f"{session_id}:{tool_call_id}"
        event = asyncio.Event()
        self._events[key] = event
        return event

    def decide(self, session_id: str, tool_call_id: str, approved: bool):
        """统一的审批决策入口"""
        key = f"{session_id}:{tool_call_id}"
        self._decisions[key] = approved
        if key in self._events:
            self._events[key].set()

    def get_decision(self, session_id: str, tool_call_id: str) -> bool | None:
        """获取审批结果，None 表示尚未决策"""
        return self._decisions.get(f"{session_id}:{tool_call_id}")

    def clear(self, session_id: str, tool_call_id: str):
        """清理审批记录"""
        key = f"{session_id}:{tool_call_id}"
        self._events.pop(key, None)
        self._decisions.pop(key, None)

    def raise_threshold(self, session_id: str, amount: int):
        """提升当前对话的工具调用上限（临时，不持久化）"""
        self._threshold_raises[session_id] = self._threshold_raises.get(session_id, 0) + amount

    def get_threshold_raise(self, session_id: str) -> int:
        """获取当前对话累计提升的上限量"""
        return self._threshold_raises.get(session_id, 0)

    def clear_threshold(self, session_id: str):
        """清理对话结束时的阈值提升记录"""
        self._threshold_raises.pop(session_id, None)


# 全局单例
approval_registry = ApprovalRegistry()
