"""Session 数据模型与消息序列化"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
    SystemMessage,
)


@dataclass
class Session:
    """会话"""
    session_id: str
    title: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    message_count: int = 0


def message_to_dict(msg: BaseMessage) -> dict:
    """将 LangChain 消息对象转为可序列化的 dict"""
    if isinstance(msg, HumanMessage):
        return {"role": "user", "content": msg.content}
    elif isinstance(msg, AIMessage):
        d: dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.get("id") if isinstance(tc, dict) else tc.id,
                    "name": tc.get("name") if isinstance(tc, dict) else tc.name,
                    "args": tc.get("args") if isinstance(tc, dict) else tc.args,
                }
                for tc in msg.tool_calls
            ]
        return d
    elif isinstance(msg, ToolMessage):
        return {"role": "tool", "content": msg.content, "tool_call_id": msg.tool_call_id}
    elif isinstance(msg, SystemMessage):
        return {"role": "system", "content": msg.content}
    else:
        return {"role": "unknown", "content": str(msg)}


def dict_to_message(d: dict) -> Optional[BaseMessage]:
    """将 dict 转回 LangChain 消息对象"""
    role = d.get("role")
    content = d.get("content", "")
    if role == "user":
        return HumanMessage(content=content)
    elif role == "assistant":
        tool_calls = d.get("tool_calls")
        msg = AIMessage(content=content, tool_calls=tool_calls)
        return msg
    elif role == "tool":
        return ToolMessage(content=content, tool_call_id=d.get("tool_call_id", ""))
    elif role == "system":
        return SystemMessage(content=content)
    return None


def filter_history_messages(messages: list[dict]) -> list[BaseMessage]:
    """从存储的消息 dict 列表中过滤出需要在下一轮注入的历史消息

    规则：只保留 user / assistant(有content) / tool 三类消息
    """
    result = []
    for d in messages:
        if d["role"] in ("user", "assistant", "tool"):
            msg = dict_to_message(d)
            if msg:
                # 跳过空内容的 assistant 消息（仅含 tool_calls 的中间帧）
                if isinstance(msg, AIMessage) and not msg.content:
                    continue
                result.append(msg)
    return result
