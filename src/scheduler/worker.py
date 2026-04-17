import threading
import asyncio
from abc import ABC, abstractmethod
from typing import Any, override

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.config import CHECKPOINT_DB_PATH
from src.models.task import Task, TaskStatus
from src.workflow.graph_builder import GraphBuilder
from src.utils.common import extract_content, logger


# TODO 统一worker，把任务类型的分类放到graph_builder

class BaseWorker(ABC):
    """Worker 基类"""
    def __init__(self, task: Task, task_manager):
        self.task = task
        self.worker_id = f"worker-{task.task_id}"
        self.task_manager = task_manager

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
    def __init__(self, task: Task, task_manager):
        super().__init__(task, task_manager)
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
    def __init__(self, task: Task, task_manager):
        super().__init__(task, task_manager)
        self._pause_flag = asyncio.Event()
        self.running_task = None  # 保存 asyncio.Task 引用

        self.config = {"configurable": {"thread_id": task.task_id}}

        self.state_graph, self.initial_state = GraphBuilder.create_graph(task)

    def set_running_task(self, task):
        """设置运行中的 asyncio.Task"""
        self.running_task = task

    async def run(self) -> Any:
        """异步执行任务"""
        self.task.status = TaskStatus.RUNNING
        try:
            # 使用 task_scope 设置任务上下文
            # 使用 AsyncSqliteSaver
            async with AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as checkpointer:
                self.graph = self.state_graph.compile(checkpointer=checkpointer)
                # 执行工作流
                if self.task.is_resume:
                    logger.info(f"[{self.worker_id}] 任务 {self.task.task_id} 为恢复任务，从断点继续执行")
                    response = await self.graph.ainvoke(None, self.config)
                else:
                    logger.info(f"[{self.worker_id}] 任务 {self.task.task_id} 为新任务，从初始状态开始执行")
                    response = await self.graph.ainvoke(self.initial_state, self.config)

                # 检查任务状态，只有未被暂停或取消的任务才会设置结果
                if self.task.status != TaskStatus.PAUSED and self.task.status != TaskStatus.CANCELLED:
                    logger.info(f"[{self.worker_id}] 任务执行完成")
                    self.task.status = TaskStatus.COMPLETED
                    self.task_manager.set_result(self.task.task_id, extract_content(response))
        except asyncio.CancelledError:
            # 捕获取消异常
            logger.info(f"[{self.worker_id}] 任务被取消，保存断点，使用task.cancel")
            self.task.status = TaskStatus.PAUSED
            # 任务被取消时，langgraph 会自动处理中断和状态保存
        except Exception as e:
            logger.error(f"[{self.worker_id}] 任务执行出错: {str(e)}")
            # 检查任务状态，只有未暂停或取消的任务才会设置错误结果
            if self.task.status != TaskStatus.PAUSED and self.task.status != TaskStatus.CANCELLED:
                self.task.status = TaskStatus.ERROR
                self.task_manager.set_result(self.task.task_id, f"Error: {str(e)}")

    @property
    def pause_flag(self):
        return self._pause_flag

    @override
    def pause(self):
        # 继续维护pause_flag
        self.pause_flag.set()
        if self.running_task:
            logger.info(f"[{self.worker_id}] 任务 {self.task.task_id} 被暂停")
            self.running_task.cancel()
        self.task.status = TaskStatus.PAUSED

    @override
    def cancel(self):
        self.pause_flag.set()
        if self.running_task:
            logger.info(f"[{self.worker_id}] 任务 {self.task.task_id} 被取消")
            self.running_task.cancel()
        self.task.status = TaskStatus.CANCELLED
