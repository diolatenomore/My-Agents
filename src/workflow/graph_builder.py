from langgraph.graph import StateGraph
from typing import Dict, Any, Tuple

from models.task import TaskType
from workflow.research_write_workflow import create_research_write_graph


class GraphBuilder:
    """
    Graph构建器
    负责创建和配置LangGraph
    """

    @staticmethod
    def create_graph(task_type: TaskType, query: str) -> Tuple[StateGraph, Dict[str, Any]]:
        mapping = {
            TaskType.RESEARCH_WRITE: create_research_write_graph,
            TaskType.FILE_RW: create_file_rw_graph,
            TaskType.AUTO_PLAN: create_auto_plan_graph,
        }
        if task_type in mapping:
            return mapping[task_type](query)
        else:
            return create_default_graph(query)
            # raise ValueError(f"不支持的任务类型: {task_type}")


# TODO 其他workflow待实现
def create_file_rw_graph(query: str) -> Tuple[StateGraph, Dict[str, Any]]:
    pass


def create_auto_plan_graph(query: str) -> Tuple[StateGraph, Dict[str, Any]]:
    pass


def create_default_graph(query: str) -> Tuple[StateGraph, Dict[str, Any]]:
    pass

