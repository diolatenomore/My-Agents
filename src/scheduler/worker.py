import threading
import asyncio
from abc import ABC, abstractmethod
from typing import Any, override
import sqlite3

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from done.VirtualFileSystem.init_db import DB_PATH
from models.task import Task, TaskStatus
from utils import extract_content


DB_PATH = "checkpoints.db"

# TODO 统一worker，把任务类型的分类放到graph_builder

class BaseWorker(ABC):
    """Worker 基类"""
    def __init__(self, task: Task, middleware):
        self.task = task
        self.worker_id = f"worker-{task.task_id}"
        self.middleware = middleware

    @property
    @abstractmethod
    def pause_flag(self):
        pass

    def pause(self):
        self.pause_flag.set()
        self.task.status = TaskStatus.PAUSED

    def is_paused(self) -> bool:
        """检查任务是否已暂停"""
        return self.pause_flag.is_set()

    def cancel(self):
        self.pause_flag.set()
        self.task.status = TaskStatus.CANCELLED
        print(f"[{self.worker_id}] 任务已取消")

    def clear_pause(self):
        """清除暂停标志"""
        self.pause_flag.clear()

class ThreadBaseWorker(BaseWorker):
    """线程 Worker 基类"""
    def __init__(self, task: Task, middleware):
        super().__init__(task, middleware)
        self._pause_flag = threading.Event()

    @abstractmethod
    def run(self) -> Any:
        """执行任务的抽象方法"""
        raise NotImplementedError

    @property
    def pause_flag(self):
        return self._pause_flag

class AsyncBaseWorker(BaseWorker):
    """异步 Worker 基类"""
    def __init__(self, task: Task, middleware):
        super().__init__(task, middleware)
        self._pause_flag = asyncio.Event()
        self.running_task = None  # 保存 asyncio.Task 引用

        self.config = {"configurable": {"thread_id": task.task_id}}

        # 创建研究-写作工作流
        from graph_builder import GraphBuilder
        self.state_graph, self.initial_state = GraphBuilder.create_graph(task.task_type, task.query)

    def set_running_task(self, task):
        """设置运行中的 asyncio.Task"""
        self.running_task = task

    async def run(self) -> Any:
        """异步执行任务"""
        self.task.status = TaskStatus.RUNNING
        try:
            # 使用 AsyncSqliteSaver
            async with AsyncSqliteSaver.from_conn_string(self.db_path) as checkpointer:
                self.graph = self.state_graph.compile(checkpointer=checkpointer)
                # 执行工作流
                if self.task.is_resume:
                    response = await self.graph.ainvoke(None, self.config)
                else:
                    response = await self.graph.ainvoke(self.initial_state, self.config)

                # 检查任务状态，只有未被暂停或取消的任务才会设置结果
                if self.task.status != TaskStatus.PAUSED and self.task.status != TaskStatus.CANCELLED:
                    print(f"[{self.worker_id}] 任务执行完成")
                    self.task.status = TaskStatus.COMPLETED
                    self.middleware.set_result(self.task.task_id, extract_content(response))
        except asyncio.CancelledError:
            # 捕获取消异常
            print(f"[{self.worker_id}] 任务被取消，保存断点", "使用task.cancel")
            self.task.status = TaskStatus.PAUSED
            # 任务被取消时，langgraph 会自动处理中断和状态保存
        except Exception as e:
            # 检查任务状态，只有未暂停或取消的任务才会设置错误结果
            if self.task.status != TaskStatus.PAUSED and self.task.status != TaskStatus.CANCELLED:
                print(f"[{self.worker_id}] 任务执行出错: {str(e)}")
                self.task.status = TaskStatus.ERROR
                self.middleware.set_result(self.task.task_id, f"Error: {str(e)}")

    @property
    def pause_flag(self):
        return self._pause_flag

    @override
    def pause(self):
        # 继续维护pause_flag
        self.pause_flag.set()
        if self.running_task:
            print("call cancel....")
            self.running_task.cancel()
        self.task.status = TaskStatus.PAUSED

    @override
    def cancel(self):
        self.pause_flag.set()
        if self.running_task:
            print("call cancel....")
            self.running_task.cancel()
        self.task.status = TaskStatus.CANCELLED
        print(f"[{self.worker_id}] 任务已取消")