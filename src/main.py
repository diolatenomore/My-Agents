import json
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Path, Request
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from src.db.sqlite_pool import db_pool
from src.db.init_db import init_db
from src.utils.common import logger
from src.models.http_dtos import (
    ChatRequest, ChatResponse, SessionDTO,
    GetTaskStatusResponse, TaskChangeResponse,
    UpdateTaskPriorityRequest, GetStatsResponse, TaskManagerStatus,
)
from src.tools.loader import discover_tools
from src.agent.react_loop import run_agent, run_agent_stream
from src.session.manager import SessionManager

# 配置开关：USE_LEGACY_AGENT=true 则走旧的 Classifier+Workflow 模式
USE_LEGACY_AGENT = os.getenv("USE_LEGACY_AGENT", "false").lower() == "true"

# TODO chat后续带上session_id
# TODO skill里的tool名字不一致的修补
# TODO vfs改为通用工具，并接受不同task_id

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化数据库表
    await init_db()

    # 加载所有工具（self-register）
    discover_tools()

    # 初始化会话管理器
    from src.session.manager import SessionManager
    app.state.session_manager = SessionManager()

    if USE_LEGACY_AGENT:
        # 旧架构：懒导入避免 import 链触发
        from src.scheduler.task_manager import TaskManager
        task_manager = TaskManager()
        task_manager.run()
        app.state.task_manager = task_manager

    try:
        yield
    finally:
        if USE_LEGACY_AGENT:
            task_manager = app.state.task_manager
            task_manager.close()
        await db_pool.close_all()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get('/')
async def index():
    """提供测试页面"""
    html_path = './test_chat.html'
    with open(html_path, 'r', encoding='utf-8') as f:
        return HTMLResponse(f.read())


@app.post('/api/chat', response_model=ChatResponse)
async def chat(chat_request: ChatRequest, request: Request):
    query = chat_request.query
    if not query or query.strip() == "":
        return ChatResponse(code=401, message="参数不能为空", type="error")

    try:
        if USE_LEGACY_AGENT:
            return await _legacy_chat(query, request)
        else:
            return await _new_chat(chat_request, request.app.state.session_manager)
    except Exception as e:
        logger.error(e)
        return ChatResponse(code=500, message="服务端出错", type="error")


async def _new_chat(chat_request: ChatRequest, session_manager: SessionManager) -> ChatResponse:
    """新 Agent 循环（非流式），带 session 管理"""
    query = chat_request.query
    session_id = chat_request.session_id or str(uuid.uuid4())

    async with session_manager.lock(session_id):
        from src.vfs.task_context import set_current_task_id, clean_current_task_id, init_vfs, clean_vfs
        set_current_task_id(session_id)
        await init_vfs(session_id)
        try:
            history = await session_manager.load_history(session_id)
            result = await run_agent(query, history=history)
        finally:
            await clean_vfs()
            clean_current_task_id()

        await session_manager.save_messages(session_id, result.messages)

    return ChatResponse(
        code=200,
        message=result.content,
        type="chat",
        session_id=session_id,
    )


@app.post('/api/chat/stream')
async def chat_stream(chat_request: ChatRequest):
    """SSE 流式聊天接口"""
    query = chat_request.query
    if not query or query.strip() == "":
        return ChatResponse(code=401, message="参数不能为空", type="error")

    session_id = chat_request.session_id or str(uuid.uuid4())

    return StreamingResponse(
        _stream_events(query, session_id, app.state.session_manager),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_events(query: str, session_id: str, session_manager: SessionManager):
    """生成 SSE 事件流"""
    from src.vfs.task_context import set_current_task_id, clean_current_task_id, init_vfs, clean_vfs
    set_current_task_id(session_id)
    await init_vfs(session_id)
    history = await session_manager.load_history(session_id)

    # 提前通知前端 session_id
    yield f"event: session_ready\ndata: {json.dumps({'type': 'session_ready', 'session_id': session_id}, ensure_ascii=False)}\n\n"

    messages: list = []
    try:
        async with session_manager.lock(session_id):
            async for event in run_agent_stream(
                query,
                history=history,
            ):
                if event["type"] == "done":
                    messages = event.pop("_messages", [])
                yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
    except Exception as e:
        logger.error(f"流式输出出错: {e}")
        yield f"event: error\ndata: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
    finally:
        await clean_vfs()
        clean_current_task_id()
        if messages:
            try:
                await session_manager.save_messages(session_id, messages)
            except Exception as e:
                logger.error(f"保存会话消息失败: {e}")


async def _legacy_chat(query: str, request: Request) -> ChatResponse:
    """旧架构：Classifier 分发 + 工作流"""
    from src.scheduler.classifier import Classifier
    from src.models.task import Task, TaskType, Priority, TaskStatus
    from langchain_openai import ChatOpenAI
    from src.config import MODEL, DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY
    from src.utils.common import extract_content
    import uuid

    decision = await Classifier.classify(query)

    if decision == TaskType.CHAT:
        model = ChatOpenAI(model=MODEL, base_url=DEEPSEEK_BASE_URL, api_key=DEEPSEEK_API_KEY)
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


# ========== Session 管理 API ==========

@app.get('/api/sessions')
async def list_sessions():
    """列出所有会话"""
    sessions = await app.state.session_manager.list_sessions()
    return JSONResponse(content=[
        SessionDTO(
            session_id=s.session_id,
            title=s.title,
            message_count=s.message_count,
            created_at=s.created_at.isoformat() if hasattr(s.created_at, 'isoformat') else str(s.created_at),
            updated_at=s.updated_at.isoformat() if hasattr(s.updated_at, 'isoformat') else str(s.updated_at),
        ).model_dump()
        for s in sessions
    ])


@app.delete('/api/sessions/{session_id}')
async def delete_session(session_id: str = Path(...)):
    """删除会话"""
    await app.state.session_manager.delete(session_id)
    return JSONResponse(content={"code": 200, "message": f"会话 {session_id} 已删除"})


@app.get('/api/sessions/{session_id}/messages')
async def get_session_messages(session_id: str = Path(...)):
    """获取会话的消息记录"""
    messages = await app.state.session_manager.store.get_messages(session_id)
    return JSONResponse(content={
        "session_id": session_id,
        "messages": messages,
    })


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='localhost', port=8000)
