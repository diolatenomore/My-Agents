import operator
import threading
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Optional, Any, TypedDict, Annotated, override
import sqlite3

from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import interrupt

from task import Task, TaskStatus, ExecutionType
from utils import extract_content

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

    def set_running_task(self, task):
        """设置运行中的 asyncio.Task"""
        self.running_task = task


    @abstractmethod
    async def run(self) -> Any:
        """异步执行任务的抽象方法"""
        raise NotImplementedError

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

class LangGraphWorker(ThreadBaseWorker):
    """
    基于 LangGraph 的 Worker
    支持 pause/resume/checkpoint
    """

    def __init__(self, task: Task, middleware, graphType: str = None, db_path: str = "checkpoints.db"):
        super().__init__(task, middleware)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.checkpointer = SqliteSaver(self.conn)
        self.config = {"configurable": {"thread_id": task.task_id}}
        
        # 如果没有提供graph，则使用默认graph
        from graph_builder import GraphBuilder
        if graphType == "chat":
            state_graph = GraphBuilder.create_qwen_chat_graph(worker=self)
            self.graph = state_graph.compile(checkpointer=self.checkpointer)
        else:
            # 创建默认graph，传递self作为worker参数
            state_graph = GraphBuilder.create_default_graph(worker=self)
            self.graph = state_graph.compile(checkpointer=self.checkpointer)


    def __del__(self):
        self.conn.close()

    def run(self):
        self.task.status = TaskStatus.RUNNING
        try:
            # 确保输入是符合State结构的字典
            initial_state = {
                "messages": [HumanMessage(content=self.task.config.get("task", "写一首古诗"))],
                "step": 0,
                "current_node": "start"
            }
            # TODO 聊天任务流式输出的情况，需要处理
            if self.task.is_resume:
                response = self.graph.invoke(None, self.config)
            else:
                response = self.graph.invoke(initial_state, self.config)

            # 检查任务状态，只有未被暂停或取消的任务才会设置结果
            if self.task.status != TaskStatus.PAUSED and self.task.status != TaskStatus.CANCELLED:
                print(f"[{self.worker_id}] 任务执行完成")
                self.task.status = TaskStatus.COMPLETED
                self.middleware.set_result(self.task.task_id, extract_content(response))
        except Exception as e:
            # 检查任务状态，只有未被暂停或取消的任务才会设置错误结果
            if self.task.status != TaskStatus.PAUSED and self.task.status != TaskStatus.CANCELLED:
                print(f"[{self.worker_id}] 任务执行出错: {str(e)}")
                self.task.status = TaskStatus.ERROR
                self.middleware.set_result(self.task.task_id, f"Error: {str(e)}")


class AsyncLangGraphWorker(AsyncBaseWorker):
    """
    基于 LangGraph 的异步 Worker
    支持 pause/resume/checkpoint
    """

    def __init__(self, task: Task, middleware,  db_path: str = "checkpoints.db"):
        super().__init__(task, middleware)
        self.db_path = db_path
        self.config = {"configurable": {"thread_id": task.task_id}}
        
        # 如果没有提供graph，则使用默认graph
        from graph_builder import GraphBuilder
        if task.config.get("task_type") == "chat":
            self.state_graph = GraphBuilder.create_qwen_chat_graph(worker=self)
        else:
            # 创建默认graph，传递self作为worker参数
            self.state_graph = GraphBuilder.create_default_graph(worker=self)

    async def run(self):
        self.task.status = TaskStatus.RUNNING
        try:
            # 确保输入是符合State结构的字典
            initial_state = {
                "messages": [HumanMessage(content=self.task.config.get("task", "写一首古诗"))],
                "step": 0,
                "current_node": "start"
            }
            # 使用 AsyncSqliteSaver
            async with AsyncSqliteSaver.from_conn_string(self.db_path) as checkpointer:
                self.graph = self.state_graph.compile(checkpointer=checkpointer)
                # 执行工作流
                if self.task.is_resume:
                    response = await self.graph.ainvoke(None, self.config)
                else:
                    response = await self.graph.ainvoke(initial_state, self.config)

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
            # 检查任务状态，只有未被暂停或取消的任务才会设置错误结果
            if self.task.status != TaskStatus.PAUSED and self.task.status != TaskStatus.CANCELLED:
                print(f"[{self.worker_id}] 任务执行出错: {str(e)}")
                self.task.status = TaskStatus.ERROR
                self.middleware.set_result(self.task.task_id, f"Error: {str(e)}")


class AsyncResearchWritingWorker(AsyncBaseWorker):
    """
    基于 LangGraph 的异步研究-写作 Worker
    支持 pause/resume/checkpoint
    """

    def __init__(self, task: Task, middleware, db_path: str = "checkpoints.db"):
        super().__init__(task, middleware)
        self.db_path = db_path
        self.config = {"configurable": {"thread_id": task.task_id}}
        
        # 创建研究-写作工作流
        from graph_builder import GraphBuilder
        self.state_graph = GraphBuilder.create_research_writing_graph(worker=self)

    async def run(self):
        self.task.status = TaskStatus.RUNNING
        try:
            # 使用 AsyncSqliteSaver
            async with AsyncSqliteSaver.from_conn_string(self.db_path) as checkpointer:
                self.graph = self.state_graph.compile(checkpointer=checkpointer)
                # 执行工作流
                if self.task.is_resume:
                    response = await self.graph.ainvoke(None, self.config)
                else:
                    # 确保输入是符合State结构的字典
                    initial_state = {
                        "task": self.task.config.get("task"),
                        "research_file": None,
                        "writing_file": None,
                        "messages": [],
                        "next": None,
                        "result": None
                    }
                    response = await self.graph.ainvoke(initial_state, self.config)

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
            # 检查任务状态，只有未被暂停或取消的任务才会设置错误结果
            if self.task.status != TaskStatus.PAUSED and self.task.status != TaskStatus.CANCELLED:
                print(f"[{self.worker_id}] 任务执行出错: {str(e)}")
                self.task.status = TaskStatus.ERROR
                self.middleware.set_result(self.task.task_id, f"Error: {str(e)}")
  