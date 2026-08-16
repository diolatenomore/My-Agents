"""项目上下文管理

使用 contextvars 实现协程级别的项目隔离：
请求流入口写入当前项目，工具层（VFS operations / execute）读取工作目录，
并发会话互不干扰；subagent 经 asyncio.create_task 自动继承同一项目。
"""

import contextvars
from typing import Optional

from src.project.models import Project

_project_ctx: contextvars.ContextVar = contextvars.ContextVar('current_project', default=None)


def set_current_project(project: Optional[Project]):
    """设置当前协程的项目（None 表示普通聊天，无工作目录）"""
    _project_ctx.set(project)


def get_current_project() -> Optional[Project]:
    """获取当前协程的项目，未设置（普通聊天）返回 None"""
    return _project_ctx.get()


def get_current_work_dir() -> Optional[str]:
    """获取当前项目的工作目录，无项目时返回 None"""
    project = _project_ctx.get()
    return project.work_dir if project else None


def clear_current_project() -> None:
    """清理当前协程的项目"""
    _project_ctx.set(None)
