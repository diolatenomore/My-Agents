"""
任务上下文管理器
让task_id在文件操作中自动关联, 无需让agent调用工具时传入task_id

使用方法：
with task_scope(task_id):
    init_db()
    CopyMapping.load(task_id)
    StagingArea.load(task_id)
    workflow执行....
    # 只要调用get_current_task_id()，就会返回task_id
"""


import contextvars
from contextlib import contextmanager


# 定义上下文变量
_task_context = contextvars.ContextVar('task_id', default=None)

@contextmanager
def task_scope(task_id: str):
    """任务上下文管理器"""
    token = _task_context.set(task_id)
    try:
        yield
    finally:
        _task_context.reset(token)

def get_current_task_id() -> str:
    """工具函数内部获取当前 task_id"""
    task_id = _task_context.get()
    if task_id is None:
        raise RuntimeError("不在任务上下文中，请先使用 task_scope")
    return task_id
