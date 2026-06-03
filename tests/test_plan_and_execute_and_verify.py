import asyncio

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.vfs.operations import list_dir
from src.vfs.staging_area import StagingArea
from src.config import CHECKPOINT_DB_PATH
from src.models.task import Task, Priority, TaskType
from src.workflow.file_organize_workflow import create_file_organize_graph


async def test():
    task_id = "task0003"
    config = {"configurable": {"thread_id": task_id}}
    task = Task(
        task_id=task_id,
        priority=Priority.P2,
        query="整理 /Users/tinklingowl/PycharmProjects/AI-Agents/workspace 目录的文件，按类型分类",
        task_type=TaskType.FILE_ORGANIZE
    )
    # 使用 AsyncSqliteSaver
    async with AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as checkpointer:
        graph, initial_state = create_file_organize_graph(task)
        graph = graph.compile(checkpointer=checkpointer)

        response = await graph.ainvoke(initial_state, config)
        print(response["execute_result"])
        print(response["verify_result"])


if __name__ == "__main__":
    asyncio.run(test())
