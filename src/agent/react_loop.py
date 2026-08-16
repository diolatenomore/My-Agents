"""ReAct 循环核心 — 单 Agent 自主思考+工具调用循环"""

import asyncio
import json
import os
from datetime import datetime
from typing import AsyncGenerator, Optional

from openai import (
    APIError,
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

from src.agent.prompts import DEFAULT_SYSTEM_PROMPT
from src.project.models import Project
from src.config import (
    COMPACTION_BUDGET_OVERFLOW,
    COMPACTION_HEAD_COUNT,
    COMPACTION_MIN_TAIL_COUNT,
    COMPACTION_TAIL_TOKEN_RATIO,
    COMPACTION_TOOL_TRIM_THRESHOLD,
)
from src.skills.loader import build_skills_catalog
from src.tools.registry import registry
from src.tools.todo_tools import TodoStore
from src.utils.common import logger


def translate_openai_error(e: Exception) -> str:
    """将 OpenAI SDK 异常翻译为中文可读信息"""
    if isinstance(e, AuthenticationError):
        return "API Key 无效或余额不足，请检查模型配置中的 API Key"
    if isinstance(e, APITimeoutError):
        return "请求超时，请检查网络连接或 Base URL 是否正确"
    if isinstance(e, APIConnectionError):
        return f"无法连接到模型服务 ({e})，请检查 Base URL 是否正确"
    if isinstance(e, RateLimitError):
        return "请求频率过高，请稍后重试"
    if isinstance(e, APIError):
        msg = str(e)
        if e.body and isinstance(e.body, dict):
            msg = e.body.get("message", msg)
        elif hasattr(e, "message"):
            msg = e.message
        return f"模型服务返回错误: {msg}"
    return str(e)


# ========== 消息格式转换 ==========

def _to_openai_messages(messages: list[dict]) -> list[dict]:
    """将内部消息列表转为 OpenAI API 格式

    内部 dict 与 OpenAI API 格式几乎一致，仅 assistant 消息的 tool_calls 字段不同：
      内部:   {"id", "name", "args": {dict}}
      OpenAI: {"id", "type": "function", "function": {"name", "arguments": "{json_str}"}}
    """
    result = []
    for msg in messages:
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            result.append({
                "role": "assistant",
                "content": msg.get("content", ""),
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"], ensure_ascii=False),
                        },
                    }
                    for tc in msg["tool_calls"]
                ],
            })
        else:
            result.append(msg)
    return result


def _build_request_kwargs(model_config: dict) -> dict:
    """根据模型配置构建 chat.completions.create 的所有参数"""
    think_enabled = bool(model_config.get("think", 1))
    extra = {"thinking": {"type": "enabled" if think_enabled else "disabled"}}
    kwargs: dict = {
        "model": model_config["model"],
        "temperature": model_config.get("temperature", 0.7),
        "extra_body": extra,
    }
    re = model_config.get("reasoning_effort")
    if re:
        kwargs["reasoning_effort"] = re
    max_out = model_config.get("max_output_tokens")
    if max_out and max_out > 0:
        kwargs["max_tokens"] = max_out
    return kwargs


# ========== 压缩时机 ==========

def _calc_compression_threshold(model_config: dict) -> int:
    """计算压缩触发阈值（Claude Code 方案）

    effective_window = max_context_tokens - max(max_output_tokens, 20_000)
    threshold = effective_window - 13_000

    以默认值 200K 窗口 + 64K 输出上限为例：200000 - 64000 - 13000 = 123000
    """
    max_context = model_config.get("max_context_tokens", 200000)
    max_output = model_config.get("max_output_tokens", 64000)
    effective_window = max_context - max(max_output, 20000)
    return effective_window - 13000


# ========== 压缩核心实现 ==========

def _estimate_tokens(messages: list[dict]) -> int:
    """简易 token 估算：基于字符数近似

    中文 ≈ 1 token/字符，英文 ≈ 0.5 token/字符（≈ 2 字符/token）
    取折中：1 token ≈ 1.5 字符 → token = 字符数 / 1.5
    """
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if not content:
            continue
        total += max(1, len(content) // 1.5)
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                total += max(1, len(str(tc.get("name", ""))) // 1.5)
                total += max(1, len(str(tc.get("args", {}))) // 1.5)
    return int(total)


def _compute_tail_boundary(messages: list[dict], model_config: dict) -> int:
    """Token 预算 + 消息数下限双保险计算尾部起点索引

    从末尾往回累加 token，超过 tail_budget * overflow 时停下，
    但至少保留 min_tail_count 条。
    """
    max_context = model_config.get("max_context_tokens", 200000)
    max_output = model_config.get("max_output_tokens", 64000)
    available = max_context - max_output
    tail_budget = available * COMPACTION_TAIL_TOKEN_RATIO

    accumulated = 0
    tail_start = len(messages)
    for i in range(len(messages) - 1, -1, -1):
        msg_tokens = _estimate_tokens([messages[i]])
        if accumulated + msg_tokens > tail_budget * COMPACTION_BUDGET_OVERFLOW:
            break
        accumulated += msg_tokens
        tail_start = i

    # 消息数下限检查
    count = len(messages) - tail_start
    if count < COMPACTION_MIN_TAIL_COUNT:
        tail_start = max(0, len(messages) - COMPACTION_MIN_TAIL_COUNT)

    return tail_start


def _align_compression_boundary(messages: list[dict], tail_start: int) -> int:
    """边界对齐：确保不会截断 tool_call/tool_result 对

    从 tail_start 向前调整：如果 tail_start 处是一条 tool 消息，
    向前找到其对应的 assistant(tool_calls)，将其也纳入尾部。
    """
    if tail_start <= 0 or tail_start >= len(messages):
        return tail_start

    # 构建 tool_call_id → assistant_index 的映射
    tool_call_map: dict[str, int] = {}
    for i, msg in enumerate(messages):
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                if tc.get("id"):
                    tool_call_map[tc["id"]] = i

    # 扫描尾部 tool 消息，如果其 assistant 在中间区，将其拉入尾部
    adjusted = tail_start
    for i in range(tail_start, len(messages)):
        msg = messages[i]
        if msg["role"] == "tool" and msg.get("tool_call_id"):
            call_id = msg["tool_call_id"]
            if call_id in tool_call_map:
                assistant_idx = tool_call_map[call_id]
                if assistant_idx < tail_start:
                    adjusted = min(adjusted, assistant_idx)

    return adjusted


def _extract_previous_summary(
    middle_messages: list[dict],
) -> tuple[str | None, list[dict]]:
    """从中间区剥离旧摘要，返回 (旧摘要正文, 剥离后的中间消息)"""
    previous_summary = None
    stripped = []
    for msg in middle_messages:
        if msg.get("_compaction_summary"):
            previous_summary = msg["content"]
        else:
            stripped.append(msg)
    return previous_summary, stripped


def _serialize_middle_turns(messages: list[dict]) -> str:
    """将消息列表序列化为可读文本，用于摘要 prompt"""
    # 建立 tool_call_id → tool_name 映射
    tool_call_names: dict[str, str] = {}
    for msg in messages:
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                if tc.get("id") and tc.get("name"):
                    tool_call_names[tc["id"]] = tc["name"]

    lines = []
    for msg in messages:
        role = msg["role"]
        if role == "user":
            lines.append(f"[User]: {msg.get('content', '')}")
        elif role == "assistant":
            if msg.get("tool_calls"):
                names = [tc["name"] for tc in msg["tool_calls"]]
                lines.append(
                    f"[Assistant(tool_calls: {', '.join(names)})]: {msg.get('content', '')}"
                )
            else:
                lines.append(f"[Assistant]: {msg.get('content', '')}")
        elif role == "tool":
            c = msg.get("content", "")
            preview = c[:200] + "..." if len(c) > 200 else c
            tool_name = tool_call_names.get(msg.get("tool_call_id", ""), msg.get("tool_call_id", ""))
            lines.append(f"[Tool Result({tool_name})]: {preview}")
    return "\n".join(lines)

def _build_summary_prompt(
    middle: list[dict], previous_summary: str | None,
) -> str:
    """构建压缩摘要 prompt，参考 Hermes 的压缩提示词结构"""
    serialized = _serialize_middle_turns(middle)
    today = datetime.now().strftime("%Y-%m-%d")

    # 共享的结构化模板
    sections = """## Historical Task Snapshot
[最重要的字段。逐字记录用户最近一次尚未被满足的输入——用他们自己的原话。如果用户只是问了个问题也属于活动任务——这个任务就是"带着完整上下文回答那个问题"。不要因为用户没下命令式指令就写"None"；只在最后一轮已完全了结时才写"None。"]

## Goal
[用户总体想达成什么]

## Constraints & Preferences
[用户的偏好、编码风格、约束、重要决策]

## Completed Actions
[已完成动作的编号列表——包含工具、目标、结果。每条格式：N. 动作 目标 — 结果 [tool: 工具名]。文件路径、命令、行号、结果要具体]
示例：
1. 读取 config.py:45 — 发现 `==` 应为 `!=` [tool: read_file]
2. 修改 config.py:45 — 把 `==` 改成 `!=` [tool: patch]
3. 运行测试 `pytest tests/` — 3/50 失败：test_parse, test_validate, test_edge [tool: terminal]

## Active State
[当前工作状态——工作目录和分支（如有）、改动/新建的文件及各自简要说明、测试状态、运行中的进程、重要的环境细节]

## Blocked
[尚未解决的阻塞、错误或问题，包含精确的错误信息]

## Key Decisions
[重要的技术决策及其原因]

## Resolved Questions
[用户问过且已经回答的问题——要包含答案，这样以后不用重复回答]

## Relevant Files
[读取、修改或创建过的文件——各带一句简要说明]

## Critical Context
[如果不明确保留就会丢失的具体数值、错误消息、配置细节或数据。绝不包含 API 密钥、令牌、密码、凭据——一律写 [REDACTED]]"""

    if previous_summary:
        return f"""你正在更新一份上下文压缩摘要。之前的一次压缩生成了下面的摘要，此后又发生了新的对话轮次，需要把它们并入进来。

<之前的摘要>
{previous_summary}
</之前的摘要>

需要并入的新轮次：
{serialized}

用这套相同的结构来更新摘要。**保留**所有仍然相关的既有信息。把新完成的操作**追加**到编号列表（继续往下编号）。做完了的项从"Active State"移到"Completed Actions"，已回答的问题移到"Resolved Questions"，更新"Active State"为当前状态。只有明确过时的信息才删除。关键要求：必须更新"Historical Task Snapshot"，让它反映用户最近一次尚未被满足的输入。
用用户对话时使用的语言写摘要——不要翻译、不要切换成英语。
摘要中绝对不要包含 API 密钥、令牌、密码、机密、凭据或连接字符串——遇到任何这类内容一律替换成 [REDACTED]。
时间锚定规则：当前日期是 {today}。已经完成的操作，要写成"已完成、带日期、过去时"的事实，而不是悬而未决的指令。绝不要把已完成的操作写得像还需要做，也绝不要给还没发生的工作编造日期。
只写摘要正文，不要任何前言或前缀。"""
    else:
        return f"""你是一个负责生成上下文检查点的总结智能体。将以下对话轮次作为"前期工作的紧凑记录"的素材来源。只输出结构化的摘要，不要加问候语、前言或前缀。
用用户对话时使用的语言写摘要——不要翻译、不要切换成英语。
摘要中绝对不要包含 API 密钥、令牌、密码、机密、凭据或连接字符串——遇到任何这类内容一律替换成 [REDACTED]。可以记录"这里出现过凭据"这个事实，但不要保留它们的值。
时间锚定规则：当前日期是 {today}。已经完成的操作，要写成"已完成、带日期、过去时"的事实，而不是悬而未决的指令。绝不要把已完成的操作写得像还需要做，也绝不要给还没发生的工作编造日期。
只写摘要正文，不要任何前言或前缀。

需要总结的轮次：
{serialized}

请按以下结构输出摘要（如果某一项没有可写的，内容就填None，保证摘要的结构没有缺失）：

{sections}"""


def _compress_phase1_trim_tool_outputs(messages: list[dict]) -> int:
    """Phase 1：裁剪工具输出 — 将大于阈值的 tool 内容替换为占位符

    返回估算节省的 token 数。
    """
    saved = 0
    for i, msg in enumerate(messages):
        if msg["role"] == "tool":
            content = msg.get("content", "")
            if len(content) > COMPACTION_TOOL_TRIM_THRESHOLD:
                saved += _estimate_tokens([msg]) - 1  # 占位符约 1 token
                messages[i] = {
                    "role": "tool",
                    "content": "[旧工具输出已清除以节省上下文空间]",
                    "tool_call_id": msg.get("tool_call_id", ""),
                }
    return saved


async def _compress_phase2_llm_summary(
    middle: list[dict],
    previous_summary: str | None,
    model_config: dict,
    client,
    context_tokens: int,
) -> str:
    """Phase 2：LLM 结构化摘要

    将中间区消息序列化后调用 LLM 生成摘要。
    返回摘要文本。
    """
    prompt = _build_summary_prompt(middle, previous_summary)
    # 摘要 token 上限：max(context_tokens * 0.2, 2000)，上限为配置的最大输出
    max_summary_tokens = max(int(context_tokens * 0.20), 2000)
    max_summary_tokens = min(max_summary_tokens, model_config["max_output_tokens"])

    response = await client.chat.completions.create(
        model=model_config["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=max_summary_tokens,
    )
    return response.choices[0].message.content or ""


async def _compress(
    context_messages: list[dict],
    model_config: dict,
    client,
    context_tokens: int,
) -> bool:
    """尝试压缩 context_messages，修改原地，返回是否执行了压缩

    Phase 1 裁剪 + Phase 2 摘要。
    已有的 _compaction_summary 标记的消息会被剥离，其正文作为 previous_summary
    注入 prompt 进行迭代更新，最终只保留一条摘要。
    """
    # 确定头部保护边界（跳过 system 消息）
    head_end = 0
    head_count = 0
    for i, msg in enumerate(context_messages):
        if head_count >= COMPACTION_HEAD_COUNT:
            break
        if msg["role"] != "system":
            head_count += 1
        head_end = i + 1

    # 确定尾部边界
    tail_start = _compute_tail_boundary(context_messages, model_config)
    tail_start = _align_compression_boundary(context_messages, tail_start)

    if tail_start <= head_end:
        return False  # 没有中间区可压缩

    middle = context_messages[head_end:tail_start]
    tail = context_messages[tail_start:]

    # 剥离旧摘要
    previous_summary, stripped_middle = _extract_previous_summary(middle)

    # Phase 1：裁剪工具输出
    _compress_phase1_trim_tool_outputs(stripped_middle)

    # Phase 2：LLM 摘要
    try:
        summary_text = await _compress_phase2_llm_summary(
            stripped_middle, previous_summary, model_config, client, context_tokens,
        )
    except Exception as e:
        logger.warning(f"[Agent] LLM 摘要生成失败: {e}，仅执行 Phase 1 裁剪")
        summary_text = None

    # 重组 context_messages
    head = context_messages[:head_end]

    if summary_text:
        summary_msg = {
            "role": "assistant",
            "content": summary_text,
            "_compaction_summary": True,  # 标记为压缩摘要，供下一轮 _extract_previous_summary 剥离并迭代更新
        }
        context_messages[:] = head + [summary_msg] + tail
    else:
        # Phase 2 失败，保留 Phase 1 裁剪后的中间消息
        context_messages[:] = head + stripped_middle + tail

    logger.info(
        f"[Agent] 压缩完成: head={head_end}, middle={len(middle)}, tail={len(tail)}, "
        f"summary={'success' if summary_text else 'failed'}"
    )
    return True


# ========== TODO Hydration ==========

def _hydrate_todo_store(todo_store: TodoStore, context_messages: list[dict]):
    """从对话历史中恢复 TODO 状态

    从后往前扫描 context_messages，找到最近一次 todo 工具的 tool 返回消息，
    验证其对应一个 assistant 的 todo 调用后，解析 JSON 重建 TodoStore。
    """
    import json

    # 只往前找最近 10 条消息
    recent_messages = context_messages[-10:] if len(context_messages) > 10 else context_messages

    # 从后往前找到最近一条 tool 消息（内容包含 "todos" 和 "summary"）
    last_tool_msg = None
    for msg in reversed(recent_messages):
        if msg.get("role") == "tool" and msg.get("tool_call_id"):
            content = msg.get("content", "")
            if '"todos"' in content and '"summary"' in content:
                last_tool_msg = msg
                break

    if not last_tool_msg:
        return

    # 解析 JSON 并恢复
    if todo_store.restore_from_json(last_tool_msg["content"]):
        logger.info(f"[Todo] 从对话历史恢复: {todo_store.read()['summary']}")


# ========== Agent 入口 ==========

async def run_agent_stream(
    cancel_event: asyncio.Event,
    context_messages: list[dict],
    display_messages: list[dict],
    tools: Optional[list] = None,
    session_id: str = "",
    model_id: str = "",
    last_context_tokens: int = 0,
) -> AsyncGenerator[dict, None]:
    """运行 ReAct Agent 循环（流式版本），逐个 yield 事件

    事件类型:
        - thinking:   模型的思考过程（如 {"type":"thinking","content":"..."}）
        - token:      LLM 生成的可见文本片段（如 {"type":"token","content":"你好"}）
        - tool_call:  模型决定调用工具（如 {"type":"tool_call","name":"list_dir","args":{...}}）
                      需要审批时额外包含 requires_approval=True 和 tool_call_id
        - tool_result: 工具执行结果（如 {"type":"tool_result","name":"list_dir","result":"..."}）
        - cancelled:  取消信号（如 {"type":"cancelled","content":"", "_messages": 截断后的消息} ）
        - done:       全部完成（如 {"type":"done","content":"最终回复"}，含 "_messages" 供调用者持久化）
        - error:      发生错误（如 {"type":"error","message":"..."}）
        - threshold_tool_call: 达到工具调用上限后的工具请求（需审批）

    Args:
        cancel_event: 取消信号事件
        context_messages: API 上下文消息列表（必传，调用者已构建完整）
        display_messages: 展示消息列表（必传，调用者已构建完整，仅用于持久化和前端展示）
        tools: 工具列表，不传则使用所有注册工具
        session_id: 会话 ID，用于审批等待的中断
        model_id: 模型配置 ID（必传）
        last_context_tokens: 上次持久化的上下文 token 数（用于恢复压缩检查基线）

    Yields:
        dict: SSE 兼容的事件字典

    Raises:
        ValueError: model_id 为空或模型不存在
    """
    if not model_id:
        raise ValueError("未指定模型，请先在模型管理中添加并选择模型")

    from src.agent.model_manager import model_manager
    from src.tools.approval import approval_registry

    tools = tools or registry.get_all_schemas()
    client, model_config = await model_manager.resolve_model(model_id)

    # 创建本会话的 TodoStore（子 Agent 不会创建，实现天然隔离）
    todo_store = TodoStore()

    # 从对话历史恢复 TODO 状态（hydration）
    _hydrate_todo_store(todo_store, context_messages)

    # 从模型配置统一提取运行时参数
    max_iterations = model_config.get("max_iterations", 30)
    approval_timeout = model_config.get("approval_timeout")  # None 或 0 表示无限等待
    approval_timeout_auto_approve = model_config.get("approval_timeout_auto_approve", False)
    # 将 None 或 0 转为 None（无限等待），否则转为 float
    approval_wait_timeout = None if (approval_timeout is None or approval_timeout == 0) else float(approval_timeout)

    try:
        tool_calls_this_turn = 0
        context_tokens = last_context_tokens  # 从持久化恢复的基线
        compression_happened = False
        effective_max_iterations = max_iterations + approval_registry.get_iteration_raise(session_id)
        iteration = 1

        while iteration <= effective_max_iterations:

            # 检查点1：每轮迭代开始前检查取消信号
            if cancel_event.is_set():
                yield {
                    "type": "cancelled",
                    "content": "",
                    "display_messages": display_messages,
                    "context_messages": context_messages,
                    "context_tokens": context_tokens,
                    "compression_happened": compression_happened,
                }
                return

            logger.info(f"[Agent] 迭代 {iteration}/{effective_max_iterations}")

            # 压缩时机检查：在 API 调用前检查上下文是否超过阈值
            if context_tokens > 0:
                threshold = _calc_compression_threshold(model_config)
                if context_tokens >= threshold:
                    compressed = await _compress(
                        context_messages, model_config, client, context_tokens,
                    )
                    if compressed:
                        compression_happened = True

            openai_msgs = _to_openai_messages(context_messages)
            stream = await client.chat.completions.create(
                messages=openai_msgs,
                tools=tools,
                stream=True,
                stream_options={"include_usage": True},
                **_build_request_kwargs(model_config),
            )

            full_content = ""
            full_reasoning = ""
            # 工具调用增量聚合: index → {id, name, args_str}
            tool_call_bufs: dict[int, dict] = {}
            chunk_count = 0  # 用于取消检查的 chunk 计数
            stream_usage = None  # 流式最后一个 chunk 的 usage
            finish_reason = None  # 流式最后一个 chunk 的 finish_reason

            async for chunk in stream:
                chunk_count += 1

                # 检查点2：每 10 个 chunk 检查一次取消信号
                if chunk_count % 10 == 0 and cancel_event.is_set():
                    # 停止流消费，用已累积内容构造部分 assistant 消息
                    msg = {"role": "assistant", "content": full_content, "cancelled": True}
                    if full_reasoning:
                        msg["reasoning_content"] = full_reasoning
                    display_messages.append(msg)
                    context_messages.append(msg)
                    yield {
                        "type": "cancelled",
                        "content": full_content,
                        "display_messages": display_messages,
                        "context_messages": context_messages,
                        "context_tokens": context_tokens,
                        "compression_happened": compression_happened,
                    }
                    return

                delta = chunk.choices[0].delta if chunk.choices else None
                if chunk.choices:
                    finish_reason = chunk.choices[0].finish_reason or finish_reason
                if chunk.usage:
                    stream_usage = chunk.usage
                if not delta:
                    continue

                # ---- reasoning_content（思考过程） ----
                reasoning = getattr(delta, 'reasoning_content', None)
                if reasoning is None and hasattr(delta, 'model_extra') and delta.model_extra:
                    reasoning = delta.model_extra.get('reasoning_content', '')
                if reasoning:
                    full_reasoning += reasoning
                    yield {"type": "thinking", "content": reasoning}

                # ---- content（可见文本） ----
                if delta.content:
                    full_content += delta.content
                    yield {"type": "token", "content": delta.content}

                # ---- 聚合 tool_calls 增量 ----
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_call_bufs:
                            tool_call_bufs[idx] = {"id": "", "name": "", "args_str": ""}
                        buf = tool_call_bufs[idx]
                        if tc_delta.id:
                            buf["id"] = tc_delta.id
                        if tc_delta.function and tc_delta.function.name:
                            buf["name"] = tc_delta.function.name
                        if tc_delta.function and tc_delta.function.arguments:
                            buf["args_str"] += tc_delta.function.arguments

            # 更新当前上下文 token 基线
            if stream_usage:
                context_tokens = stream_usage.prompt_tokens

            # 检查是否达到输出上限 → 直接结束，不解析不完整的 tool_calls
            if finish_reason == "length":
                logger.warning("[Agent] 模型输出达到 max_output_tokens 上限，对话终止")
                msg = {"role": "assistant", "content": full_content}
                if full_reasoning:
                    msg["reasoning_content"] = full_reasoning
                display_messages.append(msg)
                context_messages.append(msg)
                yield {
                    "type": "done",
                    "content": full_content,
                    "display_messages": display_messages,
                    "context_messages": context_messages,
                    "context_tokens": context_tokens,
                    "finish_reason": "length",
                    "compression_happened": compression_happened,
                }
                return

            # 流结束后构造 tool_calls（内部格式） 
            tool_calls = []
            for idx in sorted(tool_call_bufs.keys()):
                buf = tool_call_bufs[idx]
                try:
                    args = json.loads(buf["args_str"]) if buf["args_str"] else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append({
                    "id": buf["id"] or f"call_{buf['name']}",
                    "name": buf["name"],
                    "args": args,
                })

            # 构造 assistant 消息
            msg: dict = {"role": "assistant", "content": full_content}
            if full_reasoning:
                msg["reasoning_content"] = full_reasoning
            if tool_calls:
                msg["tool_calls"] = tool_calls
            display_messages.append(msg)
            context_messages.append(msg)

            # 没有工具调用 → 模型完成
            if not tool_calls:
                yield {
                    "type": "done",
                    "content": full_content,
                    "display_messages": display_messages,
                    "context_messages": context_messages,
                    "context_tokens": context_tokens,
                    "compression_happened": compression_happened,
                }
                return

            # 执行工具调用（并行，边完成边 yield）
            # 每轮计算有效阈值 = 基础值 + 用户临时提升量
            base_max = model_config.get("max_tool_calls")
            effective_max = (base_max + approval_registry.get_threshold_raise(session_id)) if (base_max and base_max > 0) else None

            async for event in _execute_tool_calls_parallel(
                tool_calls, session_id, cancel_event,
                tool_calls_so_far=tool_calls_this_turn,
                max_tool_calls_threshold=effective_max,
                approval_timeout_auto_approve=approval_timeout_auto_approve,
                approval_wait_timeout=approval_wait_timeout,
                model_id=model_id,
                todo_store=todo_store,
            ):
                if event["type"] == "_tool_results_done":
                    # 全部执行完成，按原始顺序追加 tool 消息到两个列表
                    for tc, result in zip(event["_tool_calls"], event["_ordered_results"]):
                        tool_msg = {
                            "role": "tool",
                            "content": result,
                            "tool_call_id": tc["id"],
                        }
                        display_messages.append(tool_msg)
                        context_messages.append(tool_msg)
                    tool_calls_this_turn += len(tool_calls)
                    continue
                yield event

            iteration += 1

            # 迭代阈值检查：下一轮是否超过有效上限
            if iteration > effective_max_iterations:
                iter_event_id = f"__iter__{session_id}_{iteration}"
                approval_event = approval_registry.create(session_id, iter_event_id)
                yield {
                    "type": "threshold_iteration",
                    "current_iterations": iteration - 1,
                    "max_iterations": effective_max_iterations,
                    "tool_call_id": iter_event_id,
                }
                # 等待审批决策
                wait_tasks = [
                    asyncio.create_task(approval_event.wait()),
                    asyncio.create_task(cancel_event.wait()),
                ]
                _, pending = await asyncio.wait(
                    wait_tasks, timeout=approval_wait_timeout, return_when=asyncio.FIRST_COMPLETED
                )
                for t in pending:
                    t.cancel()

                if cancel_event.is_set():
                    approval_registry.clear(session_id, iter_event_id)
                    yield {
                        "type": "cancelled",
                        "content": "",
                        "display_messages": display_messages,
                        "context_messages": context_messages,
                        "context_tokens": context_tokens,
                        "compression_happened": compression_happened,
                    }
                    return

                approved = approval_registry.get_decision(session_id, iter_event_id)
                if approved is None:
                    # 超时 → 按配置决定
                    approval_registry.clear(session_id, iter_event_id)
                    if approval_timeout_auto_approve:
                        effective_max_iterations = iteration  # 允许再执行一轮
                        continue
                    else:
                        break  # 默认拒绝 → 结束
                elif approved is False:
                    # 用户拒绝 → 走总结逻辑
                    approval_registry.clear(session_id, iter_event_id)
                    break
                else:
                    # 用户通过 → 重新计算有效上限，继续循环
                    approval_registry.clear(session_id, iter_event_id)
                    effective_max_iterations = max(
                        iteration,
                        max_iterations + approval_registry.get_iteration_raise(session_id),
                    )
                    continue

        # 达到最大迭代次数，直接结束
        yield {
            "type": "done",
            "content": "",
            "display_messages": display_messages,
            "context_messages": context_messages,
            "context_tokens": context_tokens,
            "compression_happened": compression_happened,
            "stop_reason": "max_iterations",
        }

    except Exception as e:
        logger.error(f"[Agent] 流式执行出错: {e}", exc_info=True)
        yield {"type": "error", "message": translate_openai_error(e)}


async def _execute_tool_calls_parallel(
    tool_calls: list[dict],
    session_id: str,
    cancel_event: asyncio.Event,
    tool_calls_so_far: int = 0,
    max_tool_calls_threshold: Optional[int] = None,
    approval_timeout_auto_approve: bool = False,
    approval_wait_timeout: Optional[float] = None,
    model_id: str = "",
    todo_store: Optional[TodoStore] = None,
) -> AsyncGenerator[dict, None]:
    """并行执行工具调用，先 yield 全部 tool_call，再按完成顺序逐个 yield tool_result"""
    from src.tools.approval import approval_registry

    # ===== Phase 1: Yield 全部 tool_call 事件 =====
    needs_approval_list: list[bool] = []  # 按顺序维护每个工具调用是否需要审批

    for i, tc in enumerate(tool_calls):
        tool_name = tc["name"]
        static_approval = registry.requires_approval(tool_name)
        threshold_exceeded = (
            max_tool_calls_threshold is not None
            and (tool_calls_so_far + i + 1) > max_tool_calls_threshold
        )
        needs_approval = static_approval or threshold_exceeded
        needs_approval_list.append(needs_approval)

        if threshold_exceeded:
            # 纯阈值超标 → 新事件类型 threshold_tool_call
            yield {
                "type": "threshold_tool_call",
                "name": tool_name,
                "args": tc["args"],
                "tool_call_id": tc["id"],
                "current_tool_calls": tool_calls_so_far + i + 1,
                "max_tool_calls": max_tool_calls_threshold,
            }
        elif static_approval:
            # 静态审批工具（如 execute）→ 现有事件
            yield {
                "type": "tool_call",
                "name": tool_name,
                "args": tc["args"],
                "requires_approval": True,
                "tool_call_id": tc["id"],
            }
        else:
            yield {"type": "tool_call", "name": tool_name, "args": tc["args"]}

    # ===== Phase 2+3 合并：并发执行 + 边完成边 yield =====

    async def _run_one(index: int, tc: dict, needs_approval: bool) -> tuple[int, dict, str]:
        """执行单个工具（非审批直接执行，审批等待后执行）"""
        tool_name = tc["name"]
        tool_args = tc["args"]
        tool_call_id = tc["id"]
        if tool_name == "delegate_task" and model_id:
            tool_args = {**tool_args, "_model_id": model_id, "_cancel_event": cancel_event}
        elif tool_name == "execute":
            tool_args = {**tool_args, "_cancel_event": cancel_event}
        elif tool_name == "todo" and todo_store:
            tool_args = {**tool_args, "_todo_store": todo_store}

        if not needs_approval:
            # 非审批工具：直接执行
            logger.info(f"[Agent] 调用工具: {tool_name}({tool_args})")
            try:
                result = await registry.dispatch(tool_name, tool_args)
                result_str = str(result)
            except Exception as e:
                result_str = f"工具执行失败: {e}"
                logger.error(f"[Agent] 工具 '{tool_name}' 执行失败: {e}")
            logger.info(
                f"[Agent] 工具返回: {result_str[:200]}{'...' if len(result_str) > 200 else ''}"
            )
            return index, tc, result_str
        else:
            # 审批工具：等待审批后执行
            approval_event = approval_registry.create(session_id, tool_call_id)
            wait_tasks = [
                asyncio.create_task(approval_event.wait()),
                asyncio.create_task(cancel_event.wait()),
            ]
            _, pending = await asyncio.wait(
                wait_tasks, timeout=approval_wait_timeout, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()

            if cancel_event.is_set():
                approval_registry.clear(session_id, tool_call_id)
                return index, tc, "用户中断了对话"

            approved = approval_registry.get_decision(session_id, tool_call_id)
            approval_registry.clear(session_id, tool_call_id)

            if approved is None:
                if approval_timeout_auto_approve:
                    pass  # 超时默认通过 → 继续执行工具
                else:
                    return index, tc, "用户长时间未审批，工具调用已超时"
            elif approved is False:
                return index, tc, "用户拒绝了该工具的执行"

            logger.info(f"[Agent] 调用工具: {tool_name}({tool_args})")
            try:
                result = await registry.dispatch(tool_name, tool_args)
                result_str = str(result)
            except Exception as e:
                result_str = f"工具执行失败: {e}"
                logger.error(f"[Agent] 工具 '{tool_name}' 执行失败: {e}")
            logger.info(
                f"[Agent] 工具返回: {result_str[:200]}{'...' if len(result_str) > 200 else ''}"
            )
            return index, tc, result_str

    # 创建所有 task（立即开始并发执行）
    tasks = [asyncio.create_task(_run_one(i, tc, needs_approval_list[i])) for i, tc in enumerate(tool_calls)]

    # results 收集，供后续按原始顺序构造 messages
    results: dict[int, str] = {}

    # 边完成边 yield
    for coro in asyncio.as_completed(tasks):
        if cancel_event.is_set():
            break

        try:
            index, tc, result = await coro
        except asyncio.CancelledError:
            continue

        results[index] = result
        yield {"type": "tool_result", "name": tc["name"], "result": result}

    # 取消未完成的 task
    for task in tasks:
        if not task.done():
            task.cancel()

    # 为被取消而未能完成的工具补充结果
    for i, tc in enumerate(tool_calls):
        if i not in results:
            results[i] = "用户中断了对话"
            yield {"type": "tool_result", "name": tc["name"], "result": results[i]}

    # 按原始顺序返回 results（供调用者构造 messages）
    yield {
        "type": "_tool_results_done",
        "_tool_calls": tool_calls,
        "_ordered_results": [results[i] for i in range(len(tool_calls))],
    }


def _build_system_prompt(
    custom_prompt: Optional[str] = None,
    memory_block: str = "",
    project: Optional['Project'] = None,
) -> str:
    """构建 system prompt：自定义 > 默认 + 项目信息 + 技能目录 + 长期记忆"""
    if custom_prompt:
        return custom_prompt
    prompt = DEFAULT_SYSTEM_PROMPT
    if project is not None:
        prompt += "\n\n" + (
            "# 当前项目\n"
            f"- 项目名称: {project.name}\n"
            f"- 工作目录: {project.work_dir}\n"
            "当前会话关联到上述项目。文件操作工具（list_dir/read_file/create_file 等）的相对路径"
            "和 execute 命令的工作目录均以该工作目录为基准自动解析，"
            "你可以直接使用相对路径（如 src/main.py）操作项目文件，无需提供绝对路径。"
        )
    catalog = build_skills_catalog()
    if catalog:
        prompt += "\n\n" + catalog
    if memory_block:
        prompt += "\n\n" + memory_block
    return prompt


def _get_memory_block(query: str) -> str:
    """检索偏好的静态记忆，返回注入 system prompt 的 markdown 文本"""
    try:
        from src.memory.service import get_memory_service
        return get_memory_service().get_static_block()
    except Exception:
        return ""
