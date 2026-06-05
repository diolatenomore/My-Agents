"""VFS 任务上下文管理

使用 contextvars 实现协程级别的 task_id 隔离，
并通过注册表管理每个 task 独立的 StagingArea / CopyMapping 实例。
"""

import contextvars
from dataclasses import dataclass
from typing import Optional

from src.vfs.staging_area import StagingArea
from src.vfs.copy_mapping import CopyMapping
from src.utils.common import logger

# ---- contextvars：协程级隔离 ----
_task_id_ctx: contextvars.ContextVar = contextvars.ContextVar('vfs_task_id', default=None)

# ---- VFS 实例注册表 ----
@dataclass
class VFSContext:
    staging_area: 'StagingArea'    # forward ref, 实际类型在 init_vfs 时注入
    copy_mapping: 'CopyMapping'

_vfs_registry: dict[str, VFSContext] = {}


def set_current_task_id(task_id: str):
    """设置当前协程的 task_id"""
    current = _task_id_ctx.get()
    if current is not None and current != task_id:
        raise RuntimeError(f"当前协程已绑定 task_id={current}，无法再设置为 {task_id}")
    _task_id_ctx.set(task_id)


def get_current_task_id() -> str:
    """工具函数内部获取当前 task_id，未设置时抛异常"""
    task_id = _task_id_ctx.get()
    if task_id is None:
        raise RuntimeError("task_id未设置，请先调用 set_current_task_id")
    return task_id


def get_task_id_with_no_error() -> Optional[str]:
    """直接获取 task_id，未设置返回 None"""
    return _task_id_ctx.get()


def clean_current_task_id() -> None:
    """清理当前协程的 task_id"""
    _task_id_ctx.set(None)


# ---- VFS 实例生命周期 ----
async def init_vfs(task_id: str):
    """为指定 task_id 创建并加载 VFS 实例（StagingArea + CopyMapping）"""

    if task_id in _vfs_registry:
        logger.warning(f"task_id={task_id} 的 VFS 实例已存在，跳过重复创建")
        return

    staging = StagingArea(task_id)
    await staging.load()

    copy_map = CopyMapping(task_id, staging)
    await copy_map.load()

    _vfs_registry[task_id] = VFSContext(staging_area=staging, copy_mapping=copy_map)
    logger.debug(f"VFS 实例已创建并加载: task_id={task_id}")


def get_staging_area() -> StagingArea:
    """获取当前协程对应 task 的 StagingArea 实例"""
    task_id = get_current_task_id()
    ctx = _vfs_registry.get(task_id)
    if ctx is None:
        raise RuntimeError(f"task_id={task_id} 的 VFS 实例未初始化，请先调用 init_vfs")
    return ctx.staging_area


def get_copy_mapping() -> CopyMapping:
    """获取当前协程对应 task 的 CopyMapping 实例"""
    task_id = get_current_task_id()
    ctx = _vfs_registry.get(task_id)
    if ctx is None:
        raise RuntimeError(f"task_id={task_id} 的 VFS 实例未初始化，请先调用 init_vfs")
    return ctx.copy_mapping


async def clean_vfs():
    """清理当前协程对应 task 的 VFS 实例"""
    task_id = get_current_task_id()
    ctx = _vfs_registry.pop(task_id, None)
    if ctx:
        ctx.staging_area.clear()
        ctx.copy_mapping.clear()
        logger.debug(f"VFS 实例已清理: task_id={task_id}")
    else:
        logger.warning(f"task_id={task_id} 的 VFS 实例不存在，无需清理")
