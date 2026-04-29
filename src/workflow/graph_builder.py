from typing import Any, Callable, Dict, Optional, Tuple

from langgraph.graph import StateGraph

from src.models.task import TaskType, Task
from src.workflow.research_write_workflow import create_research_write_graph
from src.workflow.file_organize_workflow import create_file_organize_graph


class GraphBuilder:
    @staticmethod
    def create_graph(task: Task) -> Tuple[StateGraph, Dict[str, Any], Optional[Callable], Optional[Callable]]:
        mapping = {
            TaskType.RESEARCH_WRITE: create_research_write_graph,
            TaskType.FILE_ORGANIZE: create_file_organize_graph,
            TaskType.AUTO_PLAN: create_auto_plan_graph,
        }
        if task.task_type in mapping:
            return mapping[task.task_type](task)
        else:
            return create_default_graph(task)
            # raise ValueError(f"不支持的任务类型: {task_type}")


# TODO 其他workflow待实现
def create_auto_plan_graph(task: Task) -> Tuple[StateGraph, Dict[str, Any], Optional[Callable]]:
    pass


def create_default_graph(task: Task) -> Tuple[StateGraph, Dict[str, Any], Optional[Callable]]:
    pass
