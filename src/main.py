from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Path, Request
from langchain_community.chat_models import ChatTongyi
import uuid

from src.db.sqlite_pool import db_pool
from src.config import MODEL
from src.db.init_db import init_db
from src.utils.common import extract_content, logger
from src.models.http_dtos import ChatRequest, ChatResponse, GetTaskStatusResponse, TaskChangeResponse, \
    UpdateTaskPriorityRequest, GetStatsResponse, TaskManagerStatus
from src.scheduler.classifier import Classifier
from src.scheduler.task_manager import TaskManager
from src.models.task import Task, ExecutionType, TaskType, Priority, TaskStatus

# TODO chat后续带上session_id

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化数据库表
    init_db()

    # 创建全局 task_manager 实例
    task_manager = TaskManager()
    task_manager.run()
    app.state.task_manager = task_manager

    try:
        yield
    finally:
        task_manager.close()
        db_pool.close_all()


app = FastAPI(lifespan=lifespan)

@app.post('/api/chat', response_model=ChatResponse)
async def chat(chat_request: ChatRequest, request: Request):
    query = chat_request.query
    if not query or query.strip() == "":
        return ChatResponse(
            code=401,
            message="参数不能为空",
            type="error"
        )

    # 1、把query交给分类器
    decision = await Classifier.classify(query)

    # 2、按路由分发
    try:
        if decision == TaskType.CHAT:
            # 简单聊天
            model = ChatTongyi(model=MODEL)
            messages = [{"role": "user", "content": query}]
            response = model.invoke(messages)
            return ChatResponse(
                code=200,
                message=extract_content(response),
                type="chat"
            )
        else:
            task_id = str(uuid.uuid4())
            task = Task(
                task_id=task_id,
                query=query,
                task_type=decision,
                status=TaskStatus.PENDING,
                priority=Priority.P2
            )
            request.app.state.task_manager.enqueue(task)
            return ChatResponse(
                code=200,
                message=f"任务已创建, task_id:{task_id}",
                type="mission-" + decision.value
            )
    except Exception as e:
        logger.error(e)
        return ChatResponse(
            code=500,
            message="服务端出错",
            type="error"
        )

# 暂时不用
# @app.post('/api/tasks', status_code=201)
# async def create_task(task_data):
#     """创建新任务"""
#     try:
#         priority = task_data.priority
#         task_type = task_data.type
#         config = task_data.config
#
#         # 转换任务类型
#         execution_type = ExecutionType.THREAD if task_type == 'thread' else ExecutionType.COROUTINE
#
#         # 后端生成task_id
#         task_id = str(uuid.uuid4())
#
#         # 创建任务
#         task = Task(
#             task_id=task_id,
#             priority=priority,
#             config=config,
#             type=execution_type
#         )
#
#         # 提交任务
#         task_manager.enqueue(task)
#
#         return {
#             'task_id': task_id,
#             'message': f'任务 {task_id} 已提交'
#         }
#     except Exception as e:
#         raise HTTPException(status_code=400, detail=f'创建任务失败: {str(e)}')


@app.get('/api/tasks/{task_id}', response_model=GetTaskStatusResponse)
async def get_task_status(request: Request, task_id: str = Path(...)):
    """获取任务状态"""
    try:
        task_manager = request.app.state.task_manager
        status = task_manager.get_task_status(task_id)
        result = task_manager.get_result(task_id)

        return GetTaskStatusResponse(
            code=200,
            status=status,
            result=result
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'获取任务状态失败: {str(e)}')


@app.post('/api/tasks/{task_id}/pause', response_model=TaskChangeResponse)
async def pause_task(request: Request, task_id: str = Path(...)):
    """暂停任务"""
    try:
        result = request.app.state.task_manager.pause_task(task_id)
        return TaskChangeResponse(
            code=200,
            message=result
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'暂停任务失败: {str(e)}')


@app.post('/api/tasks/{task_id}/resume', response_model=TaskChangeResponse)
async def resume_task(request: Request, task_id: str = Path(...)):
    """恢复任务"""
    try:
        result = request.app.state.task_manager.resume_task(task_id)
        return TaskChangeResponse(
            code=200,
            message=result
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'恢复任务失败: {str(e)}')


@app.delete('/api/tasks/{task_id}', response_model=TaskChangeResponse)
async def delete_task(request: Request, task_id: str = Path(...)):
    """删除任务"""
    try:
        result = request.app.state.task_manager.delete_task(task_id)
        return TaskChangeResponse(
            code=200,
            message=result
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'删除任务失败: {str(e)}')


@app.put('/api/tasks/{task_id}/priority', response_model=TaskChangeResponse)
async def update_task_priority(request: Request, priority_data: UpdateTaskPriorityRequest, task_id: str = Path(...)):
    """更新任务优先级"""
    try:
        priority = priority_data.priority
        result = request.app.state.task_manager.change_priority(task_id, priority)
        return TaskChangeResponse(
            code=200,
            message=result
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'更新任务优先级失败: {str(e)}')


@app.get('/api/stats', response_model=GetStatsResponse)
async def get_stats(request: Request):
    """获取系统状态"""
    try:
        task_manager = request.app.state.task_manager
        data = {
            'running': task_manager.running,
            'max_workers': task_manager.max_workers,
            'pending_tasks': len(task_manager.pending_queue),
            'paused_tasks': len(task_manager.paused_queue),
            'active_workers': len(task_manager.workers)
        }
        return GetStatsResponse(
            code=200,
            data=TaskManagerStatus(**data)
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'获取系统状态失败: {str(e)}')


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='localhost', port=8000)
