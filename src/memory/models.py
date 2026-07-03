"""长期记忆数据模型"""

from dataclasses import dataclass, field
from typing import Literal

# TODO 后续再调研其他做法
@dataclass
class MemoryItem:
    """从对话中提取的一条记忆

    memory_type:
        - preference: 用户偏好（key-value 结构，按 key 去重）
        - fact: 客观事实（始终追加）
        - identity: 用户身份信息（始终追加）
    """
    memory_type: Literal["preference", "fact", "identity"]
    value: str
    key: str = ""  # 仅 preference 使用，如 "language", "response_style"
