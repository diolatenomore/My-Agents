"""Session 数据模型"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Session:
    """会话"""
    session_id: str
    title: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    message_count: int = 0


def filter_history_messages(messages: list[dict]) -> list[dict]:
    """过滤出需要注入下一轮的历史消息

    只保留 user / assistant / tool 消息。
    跳过既无 content 也无 tool_calls 的 assistant 空消息。
    """
    result = []
    for m in messages:
        if m["role"] not in ("user", "assistant", "tool"):
            continue
        if m["role"] == "assistant" and not m.get("content") and not m.get("tool_calls"):
            continue
        result.append(m)
    return result
