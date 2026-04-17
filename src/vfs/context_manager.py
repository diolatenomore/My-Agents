
# import contextvars
# from contextlib import contextmanager, asynccontextmanager

# 该方法在异步边界会丢失上下文变量
# 定义上下文变量
# _task_context = contextvars.ContextVar('task_id', default=None)
# @asynccontextmanager
# def task_scope(task_id: str):
#     """任务上下文管理器"""
#     token = _task_context.set(task_id)
#     try:
#         yield
#     finally:
#         _task_context.reset(token)

class TaskContent:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.task_id = None  #  任务id
            TaskContent._initialized = True


def get_current_task_id() -> str:
    """工具函数内部获取当前 task_id"""
    task_content = TaskContent()
    task_id = task_content.task_id
    if task_id is None:
        raise RuntimeError("task_id未设置")
    return task_id

def set_current_task_id(task_id: str):
    task_content = TaskContent()
    if task_content.task_id:
        raise RuntimeError("当前有其他正在运行的任务")
    task_content.task_id = task_id

def clean_current_task_id() -> None:
    task_content = TaskContent()
    task_content.task_id = None
