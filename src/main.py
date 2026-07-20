import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Path, Request, UploadFile
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

import asyncio

from src.session.manager import SessionManager
from src.db.sqlite_pool import db_pool
from src.db.init_db import init_db
from src.utils.common import logger
from src.models.http_dtos import (
    ChatRequest, ChatResponse, SessionDTO,
    GetTaskStatusResponse, TaskChangeResponse,
    UpdateTaskPriorityRequest, GetStatsResponse, TaskManagerStatus,
    UpdateMemoryRequest,
)
from src.tools.loader import discover_tools
from src.agent.react_loop import run_agent, run_agent_stream
from src.session.cancel import CancelRegistry
from src.memory.service import get_memory_service
from src.session.prompt_cache import SystemPromptCache

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
        return await _new_chat(chat_request, request.app.state.session_manager)
    except Exception as e:
        logger.error(e)
        return ChatResponse(code=500, message="服务端出错", type="error")


async def _new_chat(chat_request: ChatRequest, session_manager: SessionManager) -> ChatResponse:
    """新 Agent 循环（非流式），带 session 管理"""
    from src.agent.react_loop import _build_system_prompt, _get_memory_block
    from src.config import MODEL

    query = chat_request.query
    session_id = chat_request.session_id or str(uuid.uuid4())

    # 系统 prompt 冻结逻辑（与流式路径一致）
    prompt_cache = app.state.system_prompt_cache
    model_name = MODEL
    frozen_prompt = prompt_cache.get(model_name, session_id)
    if frozen_prompt:
        system_prompt = frozen_prompt
    else:
        memory_block = _get_memory_block(query)
        system_prompt = _build_system_prompt(memory_block=memory_block)
        prompt_cache.set(model_name, session_id, system_prompt)

    # 动态记忆注入 user message（随 query 变化，不碰 system prompt）
    dynamic_block = get_memory_service().get_dynamic_block(query)
    augmented_query = f"以下为用户的原始输入：\n{query}\n\n{dynamic_block}" if dynamic_block else query

    review_tree = None

    async with session_manager.lock(session_id):
        from src.vfs.task_context import set_current_task_id, clean_current_task_id, init_vfs, clean_vfs
        from src.vfs.review_manager import ReviewManager
        set_current_task_id(session_id)
        await init_vfs(session_id)
        try:
            history = await session_manager.load_history(session_id)
            result = await run_agent(augmented_query, history=history, system_prompt=system_prompt)

            # 如果有文件修改，处理 merge 结果，写入数据库
            from src.vfs.diff_table import DiffTable
            if await DiffTable.has_unreviewed(session_id):
                review_tree = await ReviewManager.build_review_tree(session_id)

        finally:
            await clean_vfs()
            clean_current_task_id()

        await session_manager.save_messages(session_id, result.messages)

        # Fire-and-forget 提取长期记忆（按轮次间隔控制）
        if get_memory_service().should_extract(session_id):
            asyncio.create_task(
                get_memory_service().extract_from_messages(session_id, result.messages)
            )

    return ChatResponse(
        code=200,
        message=result.content,
        type="chat",
        session_id=session_id,
        review_tree=review_tree,
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
    from src.agent.react_loop import _build_system_prompt, _get_memory_block
    from src.config import MODEL
    set_current_task_id(session_id)
    await init_vfs(session_id)
    history = await session_manager.load_history(session_id)

    # 注册取消事件
    cancel_registry = app.state.cancel_registry
    cancel_event = cancel_registry.create(session_id)

    # 系统 prompt 冻结逻辑：同一 (model, session) 在 TTL 内复用首个 prompt
    prompt_cache = app.state.system_prompt_cache
    model_name = MODEL  # TODO 后续前端加上模型配置
    frozen_prompt = prompt_cache.get(model_name, session_id)
    if frozen_prompt:
        system_prompt = frozen_prompt
    else:
        memory_block = _get_memory_block(query)
        system_prompt = _build_system_prompt(memory_block=memory_block)
        prompt_cache.set(model_name, session_id, system_prompt)

    # 动态记忆注入 user message（随 query 变化，不碰 system prompt）
    dynamic_block = get_memory_service().get_dynamic_block(query)
    augmented_query = f"以下为用户原始输入：\n{query}\n\n{dynamic_block}" if dynamic_block else query

    # 提前通知前端 session_id
    yield f"event: session_ready\ndata: {json.dumps({'type': 'session_ready', 'session_id': session_id}, ensure_ascii=False)}\n\n"

    messages: list = []
    final_content = ""
    try:
        async with session_manager.lock(session_id):
            async for event in run_agent_stream(
                augmented_query,
                history=history,
                system_prompt=system_prompt,
                cancel_event=cancel_event,
            ):
                # TODO 考虑中断之后vfs的处理
                if event["type"] == "cancelled":
                    messages = event.pop("_messages", [])
                    final_content = event.get("content", "")
                elif event["type"] == "done":
                    messages = event.pop("_messages", [])
                    final_content = event.get("content", "")
                    # 在 done 事件中嵌入审批树
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
        await clean_vfs()
        clean_current_task_id()
        if messages:
            try:
                await session_manager.save_messages(session_id, messages)
            except Exception as e:
                logger.error(f"保存会话消息失败: {e}")

        # Fire-and-forget 提取长期记忆（按轮次间隔控制）
        if messages and final_content and get_memory_service().should_extract(session_id):
            asyncio.create_task(
                get_memory_service().extract_from_messages(session_id, messages)
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
        ).model_dump()
        for s in sessions
    ])


@app.delete('/api/sessions/{session_id}')
async def delete_session(session_id: str = Path(...)):
    """删除会话"""
    await app.state.session_manager.delete(session_id)
    # 同步清除冻结的 system prompt 缓存
    app.state.system_prompt_cache.clear(session_id)
    return JSONResponse(content={"code": 200, "message": f"会话 {session_id} 已删除"})


@app.get('/api/sessions/{session_id}/messages')
async def get_session_messages(session_id: str = Path(...)):
    """获取会话的消息记录"""
    messages = await app.state.session_manager.store.get_messages(session_id)
    return JSONResponse(content={
        "session_id": session_id,
        "messages": messages,
    })


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


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='localhost', port=8000)
