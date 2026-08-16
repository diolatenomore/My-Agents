import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path as FilePath

from fastapi import FastAPI, File, HTTPException, Path, Query, Request, UploadFile
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

import asyncio
from typing import Optional

from src.session.manager import SessionManager
from src.db.sqlite_pool import db_pool
from src.db.init_db import init_db
from src.utils.common import logger
from src.models.http_dtos import (
    ChatRequest, ChatResponse, SessionDTO,
    GetTaskStatusResponse, TaskChangeResponse,
    UpdateTaskPriorityRequest, GetStatsResponse, TaskManagerStatus,
    UpdateMemoryRequest,
    CreateModelRequest, UpdateModelRequest, ModelConfigDTO,
    ProjectDTO, ProjectCreateRequest, ProjectUpdateRequest,
)
from src.project.store import ProjectStore
from src.project.context import set_current_project, clear_current_project
from src.tools.loader import discover_tools
from src.tools.approval import approval_registry
from src.agent.react_loop import run_agent_stream
from src.config import STAGING_AREA_PATH
from src.agent.model_manager import model_manager
from src.session.cancel import CancelRegistry
from src.memory.service import get_memory_service
from src.session.prompt_cache import SystemPromptCache
from src.session.title_generator import generate_title

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化数据库表
    await init_db()

    # 加载所有工具（self-register）
    discover_tools()

    # 初始化会话管理器
    app.state.session_manager = SessionManager()

    # 初始化取消注册表
    app.state.cancel_registry = CancelRegistry()

    # 初始化 system prompt 冻结缓存
    app.state.system_prompt_cache = SystemPromptCache()

    # 初始化模型管理器（加载 .env + 自动迁移默认模型）
    await model_manager.init_models()

    try:
        yield
    finally:
        await db_pool.close_all()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _display_text(content) -> str:
    """把展示消息的 content 拼接为纯文本（user 消息可能为 segments 数组格式）"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(seg.get("text", "") for seg in content if isinstance(seg, dict) and seg.get("type") == "text")
    return ""


def _sanitize_segments(segments: Optional[list]) -> Optional[list]:
    """清洗前端传来的展示分段：只保留 text/skill 两类且字段类型正确，其余丢弃"""
    if not isinstance(segments, list):
        return None
    cleaned = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        if seg.get("type") == "text" and isinstance(seg.get("text"), str):
            cleaned.append({"type": "text", "text": seg["text"]})
        elif seg.get("type") == "skill" and isinstance(seg.get("name"), str):
            cleaned.append({"type": "skill", "name": seg["name"]})
    return cleaned or None


async def _maybe_generate_title(session_id: str, messages: list, session_manager: SessionManager, model_id: str):
    """在新会话首轮对话后，异步生成标题（fire-and-forget）"""
    try:
        current = await session_manager.get_session(session_id)
        if current and not current.title:
            user_msg = next((_display_text(m.get("content")) for m in messages if m.get("role") == "user"), "")
            assistant_msg = next((m["content"] for m in messages if m.get("role") == "assistant" and isinstance(m.get("content"), str)), "")
            if user_msg:
                title = await generate_title(user_msg, assistant_msg, model_id)
                await session_manager.update_title(session_id, title)
                logger.info(f"会话标题已生成: {session_id} -> {title}")
    except Exception as e:
        logger.error(f"生成标题失败: {e}")


FRONTEND_DIST = FilePath(__file__).resolve().parent.parent / 'frontend' / 'dist'
LEGACY_HTML = FilePath(__file__).resolve().parent / 'test_chat.html'


@app.get('/')
async def index():
    """入口页：优先返回 frontend 构建产物，未构建时回退旧测试页"""
    index_html = FRONTEND_DIST / 'index.html'
    if index_html.is_file():
        return FileResponse(index_html)
    return HTMLResponse(LEGACY_HTML.read_text(encoding='utf-8'))


@app.get('/legacy')
async def legacy():
    """旧版测试页面（保留备用）"""
    return HTMLResponse(LEGACY_HTML.read_text(encoding='utf-8'))


@app.post('/api/chat/stream')
async def chat_stream(chat_request: ChatRequest):
    """SSE 流式聊天接口"""
    query = chat_request.query
    if not query or query.strip() == "":
        return ChatResponse(code=401, message="参数不能为空", type="error")
    if not chat_request.model_id:
        return ChatResponse(code=402, message="未指定模型，请先在模型管理中添加并选择模型", type="error")

    session_id = chat_request.session_id or str(uuid.uuid4())

    return StreamingResponse(
        _stream_events(
            query, session_id, app.state.session_manager, chat_request.model_id, chat_request.project_id,
            skills=chat_request.skills, segments=chat_request.segments,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_events(
    query: str, session_id: str, session_manager: SessionManager, model_id: str, project_id: Optional[str] = None,
    skills: Optional[list] = None, segments: Optional[list] = None,
):
    """生成 SSE 事件流"""
    from src.vfs.task_context import set_current_task_id, clean_current_task_id, init_vfs, clean_vfs
    from src.agent.react_loop import _build_system_prompt, _get_memory_block
    from src.skills.loader import build_skill_injection

    display_messages: list = []
    context_messages: list = []
    final_content = ""
    last_context_tokens = 0
    compression_happened = False
    display_history = None
    is_new_session = False
    cancel_registry = app.state.cancel_registry

    try:
        set_current_task_id(session_id)
        await init_vfs(session_id)

        # 确定会话归属的项目：新会话按请求解析（无效则视为普通聊天）；
        # 已有会话以库中为准，不随请求变化（保证 VFS 暂存区/system prompt 缓存一致）
        session = await session_manager.get_session(session_id)
        if session is None:
            is_new_session = True
            project = await ProjectStore.get_project(project_id) if project_id else None
            await session_manager.create_session(session_id, project_id=project.project_id if project else None)
        else:
            project = await ProjectStore.get_project(session.project_id) if session.project_id else None
        set_current_project(project)

        display_history = await session_manager.load_display_history(session_id)
        ctx_tokens = await session_manager.get_context_tokens(session_id)

        # 加载 API 上下文消息（可能已压缩，不含 system prompt）
        context_msgs_loaded = await session_manager.load_context_messages(session_id) or []
        context_initial_count = len(context_msgs_loaded)

        # 系统 prompt 冻结逻辑：同一 (model, session) 在 TTL 内复用首个 prompt
        prompt_cache = app.state.system_prompt_cache
        frozen_prompt = prompt_cache.get(model_id, session_id)
        if frozen_prompt:
            system_prompt = frozen_prompt
        else:
            memory_block = _get_memory_block(query)
            system_prompt = _build_system_prompt(memory_block=memory_block, project=project)
            prompt_cache.set(model_id, session_id, system_prompt)

        # 动态记忆注入 user message（随 query 变化，不碰 system prompt）
        dynamic_block = get_memory_service().get_dynamic_block(query)
        augmented_query = f"以下为用户原始输入：\n{query}\n\n{dynamic_block}" if dynamic_block else query

        # 显式注入的 skill 前置到 user message（与动态记忆同轨道：模型可见、展示历史保持干净）
        skill_block = build_skill_injection(skills)
        if skill_block:
            augmented_query = f"{skill_block}\n\n{augmented_query}"

        # 构建完整的 API 上下文：system prompt + 已持久化上下文 + 新 query（动态记忆版）
        context_messages = [{"role": "system", "content": system_prompt}]
        context_messages.extend(context_msgs_loaded)
        context_messages.append({"role": "user", "content": augmented_query})

        # 构建展示消息列表（仅用于持久化和前端展示）
        # user 消息 content 统一为 segments 数组（skill 占位符的位置信息），纯文本按需拼接
        user_content = _sanitize_segments(segments) or [{"type": "text", "text": query}]
        display_history.append({"role": "user", "content": user_content})
        display_messages = display_history

        # 提前通知前端 session_id
        yield f"event: session_ready\ndata: {json.dumps({'type': 'session_ready', 'session_id': session_id}, ensure_ascii=False)}\n\n"

        async with session_manager.lock(session_id):
            # 注册取消事件
            cancel_event = cancel_registry.create(session_id)
            
            async for event in run_agent_stream(
                cancel_event=cancel_event,
                context_messages=context_messages,
                display_messages=display_messages,
                session_id=session_id,
                model_id=model_id,
                last_context_tokens=ctx_tokens,
            ):
                if event["type"] in ("cancelled", "done"):
                    display_messages = event.pop("display_messages", [])
                    context_messages = event.pop("context_messages", [])
                    final_content = event.get("content", "")
                    last_context_tokens = event.get("context_tokens", 0)
                    compression_happened = event.pop("compression_happened", False)
                    # 检查是否有未审批的 VFS 变更，嵌入审批树
                    from src.vfs.diff_table import DiffTable
                    from src.vfs.review_manager import ReviewManager
                    if await DiffTable.has_unreviewed(session_id):
                        review_tree = await ReviewManager.build_review_tree(session_id)
                        if review_tree:
                            event["review_tree"] = review_tree
                yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    except Exception as e:
        logger.error(f"流式输出出错: {e}")
        yield f"event: error\ndata: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
    finally:
        cancel_registry.clear(session_id)
        approval_registry.clear_threshold(session_id)
        await clean_vfs()
        clean_current_task_id()
        clear_current_project()
        try:
            await session_manager.save_display_messages(session_id, display_messages)
            if last_context_tokens:
                await session_manager.update_context_tokens(session_id, last_context_tokens)
            # 持久化 context_messages：压缩后全量覆盖，否则增量追加
            if compression_happened:
                await session_manager.overwrite_context_messages(session_id, context_messages)
            else:
                new_msgs = context_messages[context_initial_count:]
                if new_msgs:
                    await session_manager.append_context_messages(session_id, new_msgs)
        except Exception as e:
            logger.error(f"保存会话消息失败: {e}")

        # Fire-and-forget 生成会话标题（仅新会话首轮；display_history 已含本轮消息，不能用作判断）
        if is_new_session:
            asyncio.create_task(_maybe_generate_title(session_id, display_messages, session_manager, model_id))

        # Fire-and-forget 提取长期记忆（按轮次间隔控制）
        if context_messages and final_content and get_memory_service().should_extract(session_id):
            asyncio.create_task(
                get_memory_service().extract_from_messages(session_id, context_messages, model_id)
            )


# ---- 取消流式对话 ----

@app.post('/api/chat/cancel/{session_id}')
async def cancel_chat(session_id: str = Path(...)):
    """取消正在进行的流式对话"""
    app.state.cancel_registry.request_cancel(session_id)
    return JSONResponse(content={"code": 200, "message": "已发送取消信号"})


# ---- VFS 审批接口 ----

@app.get('/api/vfs/review/{task_id}')
async def get_review_tree(task_id: str = Path(...)):
    """获取 merge 后的审批树"""
    from src.vfs.review_manager import ReviewManager
    tree = await ReviewManager.get_review_tree(task_id)
    if tree is None:
        return JSONResponse({"code": 200, "message": "无待审批变更", "review_tree": None})
    return JSONResponse({"code": 200, "message": "ok", "review_tree": tree})


@app.post('/api/vfs/review/{task_id}')
async def process_review(task_id: str = Path(...), approved: bool = True):
    """处理审批结果（通过/拒绝）"""
    from src.vfs.task_context import set_current_task_id, clean_current_task_id, init_vfs, clean_vfs
    set_current_task_id(task_id)
    await init_vfs(task_id)
    try:
        from src.vfs.review_manager import ReviewManager
        await ReviewManager.process_review(task_id, approved)
    finally:
        await clean_vfs()
        clean_current_task_id()
    return JSONResponse({"code": 200, "message": "审批完成"})


@app.post('/api/vfs/review/{task_id}/item/{item_id}')
async def process_review_item(task_id: str = Path(...), item_id: str = Path(...), approved: bool = True):
    """审批单条操作（通过/拒绝）"""
    from src.vfs.task_context import set_current_task_id, clean_current_task_id, init_vfs, clean_vfs
    from src.vfs.review_manager import ReviewManager
    set_current_task_id(task_id)
    await init_vfs(task_id)
    try:
        await ReviewManager.process_single_item(task_id, item_id, approved)
    finally:
        await clean_vfs()
        clean_current_task_id()
    return JSONResponse({"code": 200, "message": "ok"})


# ---- 工具审批接口 ----

@app.post('/api/tools/decide/{session_id}/{tool_call_id}')
async def decide_tool(
    session_id: str,
    tool_call_id: str,
    approved: bool = True,
    raise_limit_by: Optional[int] = Query(None, ge=1, description="提升上限量，正整数，仅 approved=true 时有效"),
):
    """工具执行审批决策，可选提升当前对话的工具调用上限或迭代上限"""
    approval_registry.decide(session_id, tool_call_id, approved)
    if approved and raise_limit_by is not None and raise_limit_by >= 1:
        if tool_call_id.startswith("__iter__"):
            # 迭代阈值提升
            approval_registry.raise_iteration_threshold(session_id, raise_limit_by)
            return JSONResponse(content={
                "code": 200,
                "message": f"已通过，迭代上限已提升 {raise_limit_by}",
                "new_threshold_raise": approval_registry.get_iteration_raise(session_id),
            })
        else:
            # 工具调用阈值提升
            approval_registry.raise_threshold(session_id, raise_limit_by)
            return JSONResponse(content={
                "code": 200,
                "message": f"已通过，上限已提升 {raise_limit_by}",
                "new_threshold_raise": approval_registry.get_threshold_raise(session_id),
            })
    return JSONResponse(content={"code": 200, "message": "已通过" if approved else "已拒绝"})


# ---- 旧版任务 API（保留向后兼容） ----

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
            project_id=s.project_id,
        ).model_dump()
        for s in sessions
    ])


async def _cleanup_vfs_data(task_id: str):
    """删除会话时清理 VFS 残留：数据库记录 + 暂存区磁盘文件"""
    try:
        async with db_pool.get_conn() as conn:
            await conn.execute("DELETE FROM staging_records WHERE task_id = ?", (task_id,))
            await conn.execute("DELETE FROM copy_records WHERE task_id = ?", (task_id,))
            await conn.execute("DELETE FROM diff_records WHERE task_id = ?", (task_id,))
            await conn.execute("DELETE FROM review_items WHERE task_id = ?", (task_id,))
    except Exception as e:
        logger.error(f"清理 VFS 数据库记录失败 (task_id={task_id}): {e}")

    _remove_staging_dir(task_id)


def _remove_staging_dir(task_id: str):
    """清理暂存区磁盘目录（会话/项目删除后调用）"""
    staging_dir = os.path.join(STAGING_AREA_PATH, task_id)
    if os.path.exists(staging_dir):
        try:
            shutil.rmtree(staging_dir)
        except Exception as e:
            logger.error(f"清理暂存区目录失败 {staging_dir}: {e}")


@app.delete('/api/sessions/{session_id}')
async def delete_session(session_id: str = Path(...)):
    """删除会话"""
    await app.state.session_manager.delete(session_id)
    # 同步清除冻结的 system prompt 缓存
    app.state.system_prompt_cache.clear(session_id)
    # 清理 VFS 残留数据（暂存区文件 + 数据库记录）
    await _cleanup_vfs_data(session_id)
    return JSONResponse(content={"code": 200, "message": f"会话 {session_id} 已删除"})


@app.put('/api/sessions/{session_id}/title')
async def update_session_title(session_id: str = Path(...), title: str = ""):
    """修改会话标题"""
    title = title.strip()
    if not title:
        return JSONResponse(content={"code": 400, "message": "标题不能为空"}, status_code=400)
    if len(title) > 50:
        return JSONResponse(content={"code": 400, "message": "标题不能超过50字"}, status_code=400)
    await app.state.session_manager.update_title(session_id, title)
    return JSONResponse(content={"code": 200, "message": "标题已更新"})


@app.get('/api/sessions/{session_id}/messages')
async def get_session_messages(session_id: str = Path(...)):
    """获取会话的消息记录"""
    messages = await app.state.session_manager.store.get_display_messages(session_id)
    ctx_tokens = await app.state.session_manager.get_context_tokens(session_id)
    return JSONResponse(content={
        "session_id": session_id,
        "messages": messages,
        "context_tokens": ctx_tokens,
    })


# ========== Project 管理 API ==========

def _project_to_dto(p) -> dict:
    return ProjectDTO(
        project_id=p.project_id,
        name=p.name,
        work_dir=p.work_dir,
        session_count=p.session_count,
        created_at=p.created_at.isoformat() if hasattr(p.created_at, 'isoformat') else str(p.created_at),
        updated_at=p.updated_at.isoformat() if hasattr(p.updated_at, 'isoformat') else str(p.updated_at),
    ).model_dump()


@app.get('/api/projects')
async def list_projects():
    """列出所有项目"""
    projects = await ProjectStore.list_projects()
    return JSONResponse(content=[_project_to_dto(p) for p in projects])


async def find_project_conflict(name: Optional[str], work_dir: Optional[str], exclude_id: str = "") -> Optional[str]:
    """项目查重：名称精确匹配；工作目录按本机路径规则归一化后比较（Windows 忽略大小写）。返回冲突提示，无冲突返回 None"""
    for p in await ProjectStore.list_projects():
        if p.project_id == exclude_id:
            continue
        if name and p.name == name:
            return f"项目名称「{name}」已存在"
        if work_dir and os.path.normcase(p.work_dir) == os.path.normcase(work_dir):
            return f"工作目录 {work_dir} 已被项目「{p.name}」使用"
    return None


@app.post('/api/projects')
async def create_project(req: ProjectCreateRequest):
    """创建项目：name 非空，work_dir 必须是已存在的目录，名称与工作目录均不可与现有项目重复"""
    name = req.name.strip()
    if not name:
        return JSONResponse(content={"code": 400, "message": "项目名称不能为空"}, status_code=400)
    if len(name) > 50:
        return JSONResponse(content={"code": 400, "message": "项目名称不能超过50字"}, status_code=400)
    work_dir = os.path.normpath(os.path.abspath(req.work_dir.strip()))
    if not os.path.isdir(work_dir):
        return JSONResponse(content={"code": 400, "message": f"工作目录不存在: {work_dir}"}, status_code=400)
    conflict = await find_project_conflict(name, work_dir)
    if conflict:
        return JSONResponse(content={"code": 400, "message": conflict}, status_code=400)
    project = await ProjectStore.create_project(str(uuid.uuid4()), name, work_dir)
    return JSONResponse(content=_project_to_dto(project))


@app.put('/api/projects/{project_id}')
async def update_project(req: ProjectUpdateRequest, project_id: str = Path(...)):
    """更新项目（仅允许修改名称，工作目录不可改；名称不可与其它项目重复）"""
    project = await ProjectStore.get_project(project_id)
    if not project:
        return JSONResponse(content={"code": 404, "message": "项目不存在"}, status_code=404)
    name = req.name.strip()
    if not name:
        return JSONResponse(content={"code": 400, "message": "项目名称不能为空"}, status_code=400)
    if len(name) > 50:
        return JSONResponse(content={"code": 400, "message": "项目名称不能超过50字"}, status_code=400)
    conflict = await find_project_conflict(name, None, exclude_id=project_id)
    if conflict:
        return JSONResponse(content={"code": 400, "message": conflict}, status_code=400)
    await ProjectStore.update_project(project_id, name)
    return JSONResponse(content=_project_to_dto(await ProjectStore.get_project(project_id)))


@app.delete('/api/projects/{project_id}')
async def delete_project(project_id: str = Path(...)):
    """删除项目：ProjectStore 在单个事务内级联删除项目及其归属会话（含消息、上下文、VFS 数据库记录），接口层再清理各会话的缓存与暂存区磁盘文件"""
    project = await ProjectStore.get_project(project_id)
    if not project:
        return JSONResponse(content={"code": 404, "message": "项目不存在"}, status_code=404)
    session_ids = await ProjectStore.delete_project_with_sessions(project_id)
    for sid in session_ids:
        app.state.system_prompt_cache.clear(sid)
        _remove_staging_dir(sid)
    return JSONResponse(content={"code": 200, "message": f"项目 {project.name} 及其 {len(session_ids)} 个会话已删除"})


# ========== 记忆管理 API ==========

@app.get('/api/memories')
async def list_memories(limit: int = 20, offset: int = 0, memory_type: str | None = None):
    """分页列出记忆"""
    items, total = get_memory_service().list_memories(limit, offset, memory_type)
    return JSONResponse(content={
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


@app.delete('/api/memories/{memory_id}')
async def delete_memory(memory_id: str = Path(...)):
    """删除单条记忆"""
    ok = get_memory_service().store.delete(memory_id)
    if ok:
        return JSONResponse(content={"code": 200, "message": "已删除"})
    return JSONResponse(content={"code": 404, "message": "记忆不存在"}, status_code=404)


@app.put('/api/memories/{memory_id}')
async def update_memory(req: UpdateMemoryRequest, memory_id: str = Path(...)):
    """更新记忆"""
    ok = get_memory_service().update_memory(memory_id, req.value, req.key)
    if ok:
        return JSONResponse(content={"code": 200, "message": "已更新"})
    return JSONResponse(content={"code": 404, "message": "记忆不存在"}, status_code=404)


@app.get('/api/memories/stats')
async def count_memories():
    """获取记忆统计"""
    total = get_memory_service().store.count()
    prefs = len(get_memory_service().store.get_preferences())
    return JSONResponse(content={
        "total": total,
        "preferences": prefs,
        "facts_identity": total - prefs,
    })


# ========== 技能管理 API ==========

@app.get('/api/skills')
async def list_skills():
    """列出所有技能（含启用/禁用状态）"""
    from src.skills.loader import get_loader
    loader = get_loader()
    skills = loader.list_all_skills()
    return JSONResponse(content={"code": 200, "skills": skills})


@app.put('/api/skills/toggle')
async def set_skill_state(name: str, disabled: bool = True):
    """置技能启用/禁用状态（幂等）。name 通过 query 参数传递，避免技能名含 / 等特殊字符时路径解析异常"""
    from src.skills.loader import get_loader
    loader = get_loader()
    if disabled:
        loader.disable_skill(name)
        return JSONResponse(content={"code": 200, "disabled": True, "message": f"技能 {name} 已禁用"})
    else:
        loader.enable_skill(name)
        return JSONResponse(content={"code": 200, "disabled": False, "message": f"技能 {name} 已启用"})


@app.post('/api/skills/upload')
async def upload_skill(file: UploadFile = File(...)):
    """上传技能 zip 包，验证格式后安装到 skills/ 目录"""
    from src.skills.loader import get_loader, _find_skill_md, _parse_frontmatter

    if not file.filename or not file.filename.lower().endswith('.zip'):
        return JSONResponse(content={"code": 400, "message": "只支持 .zip 格式的文件"}, status_code=400)

    # 保存上传文件到临时目录
    tmp_dir = tempfile.mkdtemp(prefix="skill_upload_")
    zip_path = os.path.join(tmp_dir, "upload.zip")
    try:
        content = await file.read()
        with open(zip_path, "wb") as f:
            f.write(content)

        # 解压
        extract_dir = os.path.join(tmp_dir, "extracted")
        os.makedirs(extract_dir)
        with zipfile.ZipFile(zip_path, "r") as zf:
            # 安全检查：防止 zip 炸弹
            total_size = sum(info.file_size for info in zf.infolist())
            if total_size > 15 * 1024 * 1024:  # 15MB 限制
                return JSONResponse(content={"code": 400, "message": "zip 包过大，限制 15MB"}, status_code=400)
            zf.extractall(extract_dir)

        # 在解压目录中查找 SKILL.md / skill.md（最多往下找一层）
        skill_md_path = _find_skill_md(extract_dir)
        skill_root = extract_dir

        if not skill_md_path:
            # 尝试往下一层目录查找
            subdirs = [d for d in os.listdir(extract_dir)
                       if os.path.isdir(os.path.join(extract_dir, d)) and not d.startswith('.')]
            if len(subdirs) == 1:
                skill_root = os.path.join(extract_dir, subdirs[0])
                skill_md_path = _find_skill_md(skill_root)

        if not skill_md_path:
            return JSONResponse(content={"code": 400, "message": "zip 包中未找到 SKILL.md 或 skill.md 文件"}, status_code=400)

        # 解析 frontmatter 验证必填字段
        meta = _parse_frontmatter(skill_md_path)
        if meta is None:
            return JSONResponse(content={"code": 400, "message": "SKILL.md 格式不正确，缺少 name 或 description 字段"}, status_code=400)

        # 目标目录名：优先取父目录名（单目录 zip），否则用 name 清理后作为目录名
        if skill_root != extract_dir:
            target_dirname = os.path.basename(skill_root)
        else:
            target_dirname = _sanitize_dirname(meta.name)

        loader = get_loader()
        target_path = os.path.join(loader.skills_dir, target_dirname)
        if os.path.exists(target_path):
            return JSONResponse(
                content={"code": 409, "message": f"技能目录 {target_dirname} 已存在，请先删除后再上传"},
                status_code=409,
            )

        # 复制到 skills/ 目录
        shutil.copytree(skill_root, target_path)
        loader._invalidate_metas()

        return JSONResponse(content={
            "code": 200,
            "message": f"技能 {meta.name} 安装成功",
            "skill": {"name": meta.name, "description": meta.description, "version": meta.version},
        })

    except zipfile.BadZipFile:
        return JSONResponse(content={"code": 400, "message": "无效的 zip 文件"}, status_code=400)
    except Exception as e:
        return JSONResponse(content={"code": 500, "message": f"安装失败: {str(e)}"}, status_code=500)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _sanitize_dirname(name: str) -> str:
    """将技能名转为安全的目录名：替换非法字符，去首尾空白"""
    name = re.sub(r'[<>:"/\\|?*\s]+', '-', name)
    name = name.strip('-').lower()
    return name or "unnamed-skill"


# ========== 模型配置管理 API ==========

@app.get('/api/models')
async def list_models():
    """列出所有模型配置（不含 api_key）"""
    models = await model_manager.list_models()
    return JSONResponse(content=[
        ModelConfigDTO(**m).model_dump() for m in models
    ])


@app.post('/api/models')
async def create_model(req: CreateModelRequest):
    """创建新模型配置"""
    if not req.name.strip():
        return JSONResponse(content={"code": 400, "message": "模型名称不能为空"}, status_code=400)
    if not req.base_url.strip():
        return JSONResponse(content={"code": 400, "message": "Base URL 不能为空"}, status_code=400)
    if not req.model.strip():
        return JSONResponse(content={"code": 400, "message": "模型标识不能为空"}, status_code=400)
    if not req.api_key.strip():
        return JSONResponse(content={"code": 400, "message": "API Key 不能为空"}, status_code=400)

    try:
        result = await model_manager.create_model(
            name=req.name.strip(),
            base_url=req.base_url.strip(),
            model=req.model.strip(),
            api_key=req.api_key.strip(),
            max_context_tokens=req.max_context_tokens,
            max_output_tokens=req.max_output_tokens,
            max_tool_calls=req.max_tool_calls,
            temperature=req.temperature,
            max_iterations=req.max_iterations,
            think=req.think,
            reasoning_effort=req.reasoning_effort,
            approval_timeout=req.approval_timeout,
            approval_timeout_auto_approve=req.approval_timeout_auto_approve,
        )
        return JSONResponse(content={"code": 200, "message": "创建成功", "data": ModelConfigDTO(**result).model_dump()})
    except Exception as e:
        return JSONResponse(content={"code": 500, "message": f"创建失败: {str(e)}"}, status_code=500)


@app.put('/api/models/{model_id}')
async def update_model(model_id: str, req: UpdateModelRequest):
    """更新模型配置"""
    existing = await model_manager.get_model(model_id)
    if not existing:
        return JSONResponse(content={"code": 404, "message": "模型配置不存在"}, status_code=404)

    try:
        result = await model_manager.update_model(
            model_id=model_id,
            name=req.name.strip() if req.name else None,
            base_url=req.base_url.strip() if req.base_url else None,
            model=req.model.strip() if req.model else None,
            api_key=req.api_key.strip() if req.api_key else None,
            max_context_tokens=req.max_context_tokens,
            max_output_tokens=req.max_output_tokens,
            max_tool_calls=req.max_tool_calls,
            temperature=req.temperature,
            max_iterations=req.max_iterations,
            think=req.think,
            reasoning_effort=req.reasoning_effort,
            approval_timeout=req.approval_timeout,
            approval_timeout_auto_approve=req.approval_timeout_auto_approve,
        )
        if not result:
            return JSONResponse(content={"code": 404, "message": "模型配置不存在"}, status_code=404)
        return JSONResponse(content={"code": 200, "message": "更新成功", "data": ModelConfigDTO(**result).model_dump()})
    except Exception as e:
        return JSONResponse(content={"code": 500, "message": f"更新失败: {str(e)}"}, status_code=500)


@app.delete('/api/models/{model_id}')
async def delete_model(model_id: str):
    """删除模型配置"""
    try:
        ok = await model_manager.delete_model(model_id)
        if not ok:
            return JSONResponse(content={"code": 404, "message": "模型配置不存在"}, status_code=404)
        return JSONResponse(content={"code": 200, "message": "删除成功"})
    except Exception as e:
        return JSONResponse(content={"code": 500, "message": f"删除失败: {str(e)}"}, status_code=500)


# ===== 前端静态托管（必须位于所有 API 路由之后注册）=====

if (FRONTEND_DIST / 'index.html').is_file():
    app.mount('/assets', StaticFiles(directory=FRONTEND_DIST / 'assets'), name='frontend-assets')

    @app.get('/{full_path:path}')
    async def spa_fallback(full_path: str):
        """SPA 路由回退：非 /api 路径优先返回静态文件，否则返回 index.html"""
        if full_path.startswith('api'):
            raise HTTPException(status_code=404, detail='Not Found')
        if full_path:
            candidate = (FRONTEND_DIST / full_path).resolve()
            if str(candidate).startswith(str(FRONTEND_DIST.resolve())) and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / 'index.html')


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='localhost', port=8000)
