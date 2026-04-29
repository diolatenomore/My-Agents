"""用于在工作流传递task_id"""

class TaskContent:
    task_id: str = None

    @classmethod
    def get(cls) -> str:
        return cls.task_id

    @classmethod
    def set(cls, task_id: str):
        cls.task_id = task_id

    @classmethod
    def clean(cls) -> None:
        cls.task_id = None


def get_current_task_id() -> str:
    """工具函数内部获取当前 task_id"""
    task_id = TaskContent.get()
    if task_id is None:
        raise RuntimeError("task_id未设置")
    return task_id

def get_task_id_with_no_error():
    """直接获取 task_id，不考虑是否为空"""
    return TaskContent.get()

def set_current_task_id(task_id: str):
    current_id = TaskContent.get()
    if current_id:
        raise RuntimeError("当前有其他正在运行的任务")
    TaskContent.set(task_id)

def clean_current_task_id() -> None:
    TaskContent.clean()
