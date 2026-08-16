"""Project 数据模型"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Project:
    """项目（命名的工作目录，会话可选归属）"""
    project_id: str
    name: str = ""
    work_dir: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    session_count: int = 0  # 查询时 JOIN sessions 统计，非库字段
