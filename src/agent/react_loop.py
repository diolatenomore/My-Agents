"""ReAct 循环核心 — 单 Agent 自主思考+工具调用循环"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional

from openai import AsyncOpenAI
from openai import (
    APIError,
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

from src.agent.prompts import DEFAULT_SYSTEM_PROMPT
from src.skills.loader import build_skills_catalog
from src.tools.registry import registry
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


@dataclass
class AgentResult:
    """Agent 运行结果"""
    content: str  # 最终回复内容
    messages: list  # 完整的消息列表（含中间步骤）
    iterations: int = 0  # 实际迭代次数
    tool_calls_count: int = 0  # 工具调用次数
    token_usage: dict = field(default_factory=dict)  # 各维度 token 用量，字段: prompt_tokens(累计), completion_tokens(累计), context_tokens(最后一轮上下文)


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


def _from_openai_tool_calls(openai_tool_calls: list) -> list[dict]:
    """将 OpenAI 非流式响应的 tool_calls 转为内部格式"""
    result = []
    for tc in openai_tool_calls or []:
        func = tc.get("function", {})
        try:
            args = json.loads(func.get("arguments", "{}"))
        except json.JSONDecodeError:
            args = {}
        result.append({
            "id": tc.get("id", ""),
            "name": func.get("name", ""),
            "args": args,
        })
    return result


def _create_client(base_url: str, api_key: str) -> AsyncOpenAI:
    """创建 AsyncOpenAI 客户端"""
    return AsyncOpenAI(base_url=base_url, api_key=api_key)


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
    return kwargs


# ========== 消息构建 ==========

def _build_messages(
    system_prompt: str, history: Optional[list], query: str
) -> list[dict]:
    """构建消息列表"""
    query = _expand_skill_refs(query)  # skill注入到UserMessage，避免破坏前缀缓存
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": query})
    return messages


# ========== Agent 入口 ==========

async def run_agent(
    query: str,
    history: Optional[list] = None,
    system_prompt: Optional[str] = None,
    tools: Optional[list] = None,
    model_id: str = "",
) -> AgentResult:
    """运行 ReAct Agent 循环（非流式）

    Args:
        query: 用户输入
        history: 历史消息列表（由调用者从持久化存储加载）
        system_prompt: 自定义 system prompt，不传则使用默认 + 技能目录
        tools: 工具列表，不传则使用所有注册工具
        model_id: 模型配置 ID（必传）

    Returns:
        AgentResult

    Raises:
        ValueError: model_id 为空或模型不存在
    """
    if not model_id:
        raise ValueError("未指定模型，请先在模型管理中添加并选择模型")

    from src.agent.model_manager import model_manager

    tools = tools or registry.get_all_schemas()
    memory_block = _get_memory_block(query)
    prompt = _build_system_prompt(system_prompt, memory_block=memory_block)

    messages = _build_messages(prompt, history, query)
    client, model_config = await model_manager.resolve_model(model_id)

    try:
        iterations, total_tool_calls, token_usage = await _execute_loop(client, model_config, messages, tools)
    except Exception as e:
        raise ValueError(translate_openai_error(e)) from e

    # 取最后一条 assistant 消息作为最终回复
    final_content = ""
    for msg in reversed(messages):
        if msg["role"] == "assistant" and msg.get("content"):
            final_content = msg["content"]
            break

    return AgentResult(
        content=final_content,
        messages=messages,
        iterations=iterations,
        tool_calls_count=total_tool_calls,
        token_usage=token_usage,
    )


async def run_agent_stream(
    query: str,
    cancel_event: asyncio.Event,
    history: Optional[list] = None,
    system_prompt: Optional[str] = None,
    tools: Optional[list] = None,
    session_id: str = "",
    model_id: str = "",
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
        query: 用户输入
        history: 历史消息列表（由调用者从持久化存储加载）
        system_prompt: 自定义 system prompt，不传则使用默认 + 技能目录
        tools: 工具列表，不传则使用所有注册工具
        session_id: 会话 ID，用于审批等待的中断
        model_id: 模型配置 ID（必传）

    Yields:
        dict: SSE 兼容的事件字典

    Raises:
        ValueError: model_id 为空或模型不存在
    """
    if not model_id:
        raise ValueError("未指定模型，请先在模型管理中添加并选择模型")

    from src.agent.model_manager import model_manager

    tools = tools or registry.get_all_schemas()
    memory_block = _get_memory_block(query)
    prompt = _build_system_prompt(system_prompt, memory_block=memory_block)

    messages = _build_messages(prompt, history, query)
    client, model_config = await model_manager.resolve_model(model_id)

    # 从模型配置统一提取运行时参数
    max_iterations = model_config.get("max_iterations", 30)

    try:
        token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "context_tokens": 0}
        tool_calls_this_turn = 0

        for iteration in range(1, max_iterations + 1):

            # 检查点1：每轮迭代开始前检查取消信号
            if cancel_event.is_set():
                yield {
                    "type": "cancelled",
                    "content": "",
                    "_messages": messages,
                    "token_usage": token_usage,
                }
                return

            logger.info(f"[Agent] 迭代 {iteration}/{max_iterations}")

            openai_msgs = _to_openai_messages(messages)
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

            async for chunk in stream:
                chunk_count += 1

                # 检查点2：每 10 个 chunk 检查一次取消信号
                if chunk_count % 10 == 0 and cancel_event.is_set():
                    # 停止流消费，用已累积内容构造部分 assistant 消息
                    msg = {"role": "assistant", "content": full_content, "cancelled": True}
                    if full_reasoning:
                        msg["reasoning_content"] = full_reasoning
                    messages.append(msg)
                    yield {
                        "type": "cancelled",
                        "content": full_content,
                        "_messages": messages,
                        "token_usage": token_usage,
                    }
                    return

                delta = chunk.choices[0].delta if chunk.choices else None
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

            # 累计流式调用的 token 用量
            if stream_usage:
                token_usage["prompt_tokens"] += stream_usage.prompt_tokens
                token_usage["completion_tokens"] += stream_usage.completion_tokens
                token_usage["context_tokens"] = stream_usage.total_tokens

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
            messages.append(msg)

            # 没有工具调用 → 模型完成
            if not tool_calls:
                yield {
                    "type": "done",
                    "content": full_content,
                    "_messages": messages,
                    "token_usage": token_usage,
                }
                return

            # 执行工具调用（并行，边完成边 yield）
            # 每轮计算有效阈值 = 基础值 + 用户临时提升量
            from src.tools.approval import approval_registry
            base_max = model_config.get("max_tool_calls")
            effective_max = (base_max + approval_registry.get_threshold_raise(session_id)) if (base_max and base_max > 0) else None

            async for event in _execute_tool_calls_parallel(
                tool_calls, session_id, cancel_event,
                tool_calls_so_far=tool_calls_this_turn,
                max_tool_calls_threshold=effective_max,
            ):
                if event["type"] == "_tool_results_done":
                    # 全部执行完成，按原始顺序追加 tool 消息到 messages
                    for tc, result in zip(event["_tool_calls"], event["_ordered_results"]):
                        messages.append({
                            "role": "tool",
                            "content": result,
                            "tool_call_id": tc["id"],
                        })
                    tool_calls_this_turn += len(tool_calls)
                    continue
                yield event

        # 达到最大迭代次数
        # TODO 还需考虑上下文满了的情况
        summary = f"已达到最大迭代次数 {max_iterations}，请基于已有信息给出总结。"
        messages.append({"role": "user", "content": summary})  # TODO 角色为user合适吗？
        openai_msgs = _to_openai_messages(messages)
        response = await client.chat.completions.create(
            messages=openai_msgs,
            tools=tools,  # TODO 是否不应该传工具
            **_build_request_kwargs(model_config),
        )
        choice = response.choices[0].message
        final_content = choice.content or ""
        messages.append({"role": "assistant", "content": final_content})
        yield {
            "type": "done",
            "content": final_content,
            "_messages": messages,
            "token_usage": token_usage,
        }

    except Exception as e:
        logger.error(f"[Agent] 流式执行出错: {e}", exc_info=True)
        yield {"type": "error", "message": translate_openai_error(e)}


async def _execute_loop(
    client: AsyncOpenAI, model_config: dict, messages: list[dict], tools: list,
) -> tuple[int, int, dict]:
    """非流式版本的 ReAct 循环执行体

    Returns:
        (iterations, total_tool_calls, token_usage)
        token_usage 字段: prompt_tokens(累计), completion_tokens(累计), context_tokens(最后一轮上下文)
    """
    iterations = 0
    total_tool_calls = 0
    max_iterations = model_config.get("max_iterations", 30)
    token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "context_tokens": 0}

    while iterations < max_iterations:
        iterations += 1

        logger.info(f"[Agent] 迭代 {iterations}/{max_iterations}")

        openai_msgs = _to_openai_messages(messages)
        response = await client.chat.completions.create(
            messages=openai_msgs,
            tools=tools,
            **_build_request_kwargs(model_config),
        )
        choice = response.choices[0].message
        if response.usage:
            token_usage["prompt_tokens"] += response.usage.prompt_tokens
            token_usage["completion_tokens"] += response.usage.completion_tokens
            token_usage["context_tokens"] = response.usage.prompt_tokens

        msg = {
            "role": "assistant",
            "content": choice.content or "",
            "tool_calls": _from_openai_tool_calls(choice.tool_calls),
        }
        messages.append(msg)

        if not msg["tool_calls"]:
            logger.info(f"[Agent] 模型完成输出，共 {iterations} 次迭代，{total_tool_calls} 次工具调用")
            return iterations, total_tool_calls, token_usage

        for tc in msg["tool_calls"]:
            total_tool_calls += 1
            tool_name = tc["name"]
            tool_args = tc["args"]
            tool_call_id = tc["id"]

            logger.info(f"[Agent] 调用工具: {tool_name}({tool_args})")

            observation = await registry.dispatch(tool_name, tool_args)

            logger.info(f"[Agent] 工具返回: {str(observation)[:200]}{'...' if len(str(observation)) > 200 else ''}")

            messages.append({
                "role": "tool",
                "content": str(observation),
                "tool_call_id": tool_call_id,
            })

    # 达到最大迭代次数
    summary = f"已达到最大迭代次数 {max_iterations}，请基于已有信息给出总结。"
    messages.append({"role": "user", "content": summary})
    openai_msgs = _to_openai_messages(messages)
    response = await client.chat.completions.create(
        messages=openai_msgs,
        tools=tools,
        **_build_request_kwargs(model_config),
    )
    choice = response.choices[0].message
    if response.usage:
        token_usage["prompt_tokens"] += response.usage.prompt_tokens
        token_usage["completion_tokens"] += response.usage.completion_tokens
        token_usage["context_tokens"] = response.usage.prompt_tokens
    messages.append({"role": "assistant", "content": choice.content or ""})

    return iterations, total_tool_calls, token_usage


async def _execute_tool_calls_parallel(
    tool_calls: list[dict],
    session_id: str,
    cancel_event: asyncio.Event,
    tool_calls_so_far: int = 0,
    max_tool_calls_threshold: Optional[int] = None,
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
            and max_tool_calls_threshold > 0  # TODO 这两行何意味？
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
                wait_tasks, timeout=120, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()

            if cancel_event.is_set():
                approval_registry.clear(session_id, tool_call_id)
                return index, tc, "工具调用被用户中断"

            approved = approval_registry.get_decision(session_id, tool_call_id)
            approval_registry.clear(session_id, tool_call_id)


            if approved is None:
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
            results[i] = "工具调用被用户中断"
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
) -> str:
    """构建 system prompt：自定义 > 默认 + 技能目录 + 长期记忆"""
    if custom_prompt:
        return custom_prompt
    prompt = DEFAULT_SYSTEM_PROMPT
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


def _expand_skill_refs(query: str) -> str:
    """解析用户消息中的 /skill:name 指令，以 Hermes 风格注入
    Skill 正文不包裹任何标签，自然融入上下文。
    元信息用轻量方括号标注，边界靠自然语言过渡句。

    "/skill:file-organize 帮我整理 D:/work 的文件"
    →
    [SYSTEM: 用户调用了 "file-organize" skill，请遵循以下指令]

    <SKILL.md 全文>

    [Skill 目录: skills/file-organize]
    [附属文件: references/api.md, scripts/tool.py]

    用户指令：帮我整理 D:/work 的文件
    """
    import re
    from src.skills.loader import get_loader

    skill_pattern = re.compile(r'/skill:([a-zA-Z0-9][-a-zA-Z0-9]*)')

    matches = skill_pattern.findall(query)
    if not matches:
        return query

    # 去重 + 加载
    loader = get_loader()
    seen = set()
    names_in_order = []
    contents_by_name = {}
    files_by_name = {}
    for name in matches:
        if name in seen:
            continue
        seen.add(name)
        content = loader.load_skill(name)
        if content:
            names_in_order.append(name)
            contents_by_name[name] = content
            files_by_name[name] = loader.list_skill_dir(name)
            logger.info(f"/skill 显式加载: {name}")

    if not names_in_order:
        return query

    # 构建 Hermes 风格的消息
    parts = []
    total = len(names_in_order)
    for i, name in enumerate(names_in_order, 1):
        content = contents_by_name[name]
        files = files_by_name[name]

        if total == 1:
            parts.append(f'[SYSTEM: 用户调用了 "{name}" skill，请遵循以下指令]')
        else:
            parts.append(f'[SYSTEM: 用户调用了 "{name}" skill（第 {i}/{total} 个），请遵循以下指令]')

        parts.append("")
        parts.append(content)

        # Skill 目录元信息
        parts.append("")
        parts.append(f"[Skill 目录: skills/{name}]")

        # 附属文件清单
        if files:
            file_list = ", ".join(files)
            parts.append(f"[附属文件: {file_list}]")

        parts.append("")

    # 用户原始指令
    remaining = skill_pattern.sub('', query).strip()
    if remaining:
        parts.append(f"用户指令：{remaining}")

    return "\n".join(parts).rstrip()
