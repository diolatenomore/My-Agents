"""ReAct 循环核心 — 单 Agent 自主思考+工具调用循环"""

import asyncio
import json
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

from openai import AsyncOpenAI

from src.agent.agent_config import AgentConfig
from src.agent.prompts import DEFAULT_SYSTEM_PROMPT
from src.config import DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY
from src.skills.loader import build_skills_catalog
from src.tools.registry import registry
from src.utils.common import logger


@dataclass
class AgentResult:
    """Agent 运行结果"""
    content: str  # 最终回复内容
    messages: list  # 完整的消息列表（含中间步骤）
    iterations: int = 0  # 实际迭代次数
    tool_calls_count: int = 0  # 工具调用次数


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


def _create_client() -> AsyncOpenAI:
    """创建 AsyncOpenAI 客户端"""
    return AsyncOpenAI(base_url=DEEPSEEK_BASE_URL, api_key=DEEPSEEK_API_KEY)


def _build_request_kwargs(cfg: AgentConfig) -> dict:
    """根据配置构建 chat.completions.create 的所有参数"""
    extra = {"thinking": {"type": "enabled" if cfg.think else "disabled"}}
    kwargs: dict = {
        "model": cfg.model,
        "temperature": cfg.temperature,
        "extra_body": extra,
    }
    if cfg.reasoning_effort is not None:
        kwargs["reasoning_effort"] = cfg.reasoning_effort
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
    config: Optional[AgentConfig] = None,
    system_prompt: Optional[str] = None,
    tools: Optional[list] = None,
) -> AgentResult:
    """运行 ReAct Agent 循环（非流式）

    Args:
        query: 用户输入
        history: 历史消息列表（由调用者从持久化存储加载）
        config: Agent 配置
        system_prompt: 自定义 system prompt，不传则使用默认 + 技能目录
        tools: 工具列表，不传则使用所有注册工具

    Returns:
        AgentResult
    """
    cfg = config or AgentConfig()
    tools = tools or registry.get_all_schemas()
    memory_block = _get_memory_block(query)
    prompt = _build_system_prompt(system_prompt, memory_block=memory_block)

    messages = _build_messages(prompt, history, query)
    client = _create_client()

    iterations, total_tool_calls = await _execute_loop(client, cfg, messages, tools)

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
    )


async def run_agent_stream(
    query: str,
    history: Optional[list] = None,
    config: Optional[AgentConfig] = None,
    system_prompt: Optional[str] = None,
    tools: Optional[list] = None,
    cancel_event: Optional[asyncio.Event] = None,
) -> AsyncGenerator[dict, None]:
    """运行 ReAct Agent 循环（流式版本），逐个 yield 事件

    事件类型:
        - thinking:   模型的思考过程（如 {"type":"thinking","content":"..."}）
        - token:      LLM 生成的可见文本片段（如 {"type":"token","content":"你好"}）
        - tool_call:  模型决定调用工具（如 {"type":"tool_call","name":"list_dir","args":{...}}）
        - tool_result: 工具执行结果（如 {"type":"tool_result","name":"list_dir","result":"..."}）
        - cancelled:  取消信号（如 {"type":"cancelled","content":"", "_messages": 截断后的消息} ）
        - done:       全部完成（如 {"type":"done","content":"最终回复"}，含 "_messages" 供调用者持久化）
        - error:      发生错误（如 {"type":"error","message":"..."}）

    Args:
        query: 用户输入
        history: 历史消息列表（由调用者从持久化存储加载）
        config: Agent 配置
        system_prompt: 自定义 system prompt，不传则使用默认 + 技能目录
        tools: 工具列表，不传则使用所有注册工具

    Yields:
        dict: SSE 兼容的事件字典
    """
    cfg = config or AgentConfig()
    tools = tools or registry.get_all_schemas()
    memory_block = _get_memory_block(query)
    prompt = _build_system_prompt(system_prompt, memory_block=memory_block)

    messages = _build_messages(prompt, history, query)
    client = _create_client()

    try:
        for iteration in range(1, cfg.max_iterations + 1):

            # 检查点1：每轮迭代开始前检查取消信号
            if cancel_event and cancel_event.is_set():
                yield {
                    "type": "cancelled",
                    "content": "",
                    "_messages": messages,
                }
                return

            if cfg.verbose:
                logger.info(f"[Agent] 迭代 {iteration}/{cfg.max_iterations}")

            openai_msgs = _to_openai_messages(messages)
            stream = await client.chat.completions.create(
                messages=openai_msgs,
                tools=tools,
                stream=True,
                **_build_request_kwargs(cfg),
            )

            full_content = ""
            full_reasoning = ""
            # 工具调用增量聚合: index → {id, name, args_str}
            tool_call_bufs: dict[int, dict] = {}
            chunk_count = 0  # 用于取消检查的 chunk 计数

            async for chunk in stream:
                chunk_count += 1

                # 检查点2：每 10 个 chunk 检查一次取消信号
                if cancel_event and chunk_count % 10 == 0 and cancel_event.is_set():
                    # 停止流消费，用已累积内容构造部分 assistant 消息
                    msg = {"role": "assistant", "content": full_content, "cancelled": True}
                    if full_reasoning:
                        msg["reasoning_content"] = full_reasoning
                    messages.append(msg)
                    yield {
                        "type": "cancelled",
                        "content": full_content,
                        "_messages": messages,
                    }
                    return

                delta = chunk.choices[0].delta if chunk.choices else None
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
                yield {"type": "done", "content": full_content, "_messages": messages}
                return

            # 执行工具调用
            for tc in tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                tool_call_id = tc["id"]

                # 检查点3：工具执行前检查取消信号
                if cancel_event and cancel_event.is_set():
                    # 为剩余未执行的工具调用生成假错误返回
                    remaining = tool_calls[tool_calls.index(tc):]
                    for remaining_tc in remaining:
                        yield {"type": "tool_call", "name": remaining_tc["name"], "args": remaining_tc["args"]}
                        error_result = "工具调用被用户中断"
                        yield {"type": "tool_result", "name": remaining_tc["name"], "result": error_result}
                        messages.append({
                            "role": "tool",
                            "content": error_result,
                            "tool_call_id": remaining_tc["id"],
                        })
                    yield {
                        "type": "cancelled",
                        "content": full_content,
                        "_messages": messages,
                    }
                    return

                yield {"type": "tool_call", "name": tool_name, "args": tool_args}

                if cfg.verbose:
                    logger.info(f"[Agent] 调用工具: {tool_name}({tool_args})")

                try:
                    observation = await registry.dispatch(tool_name, tool_args)
                except Exception as e:
                    observation = f"工具执行失败: {e}"
                    logger.error(f"[Agent] 工具 '{tool_name}' 执行失败: {e}")

                if cfg.verbose:
                    logger.info(
                        f"[Agent] 工具返回: {str(observation)[:200]}{'...' if len(str(observation)) > 200 else ''}"
                    )

                yield {"type": "tool_result", "name": tool_name, "result": str(observation)}

                messages.append({
                    "role": "tool",
                    "content": str(observation),
                    "tool_call_id": tool_call_id,
                })

        # 达到最大迭代次数
        # TODO 还需考虑上下文满了的情况
        summary = f"已达到最大迭代次数 {cfg.max_iterations}，请基于已有信息给出总结。"
        messages.append({"role": "user", "content": summary})  # TODO 角色为user合适吗？
        openai_msgs = _to_openai_messages(messages)
        response = await client.chat.completions.create(
            messages=openai_msgs,
            tools=tools,  # TODO 是否不应该传工具
            **_build_request_kwargs(cfg),
        )
        choice = response.choices[0].message
        final_content = choice.content or ""
        messages.append({"role": "assistant", "content": final_content})
        yield {"type": "done", "content": final_content, "_messages": messages}

    except Exception as e:
        logger.error(f"[Agent] 流式执行出错: {e}", exc_info=True)
        yield {"type": "error", "message": str(e)}


async def _execute_loop(
    client: AsyncOpenAI, cfg: AgentConfig, messages: list[dict], tools: list,
) -> tuple[int, int]:
    """非流式版本的 ReAct 循环执行体"""
    iterations = 0
    total_tool_calls = 0

    while iterations < cfg.max_iterations:
        iterations += 1

        if cfg.verbose:
            logger.info(f"[Agent] 迭代 {iterations}/{cfg.max_iterations}")

        openai_msgs = _to_openai_messages(messages)
        response = await client.chat.completions.create(
            messages=openai_msgs,
            tools=tools,
            **_build_request_kwargs(cfg),
        )
        choice = response.choices[0].message

        msg = {
            "role": "assistant",
            "content": choice.content or "",
            "tool_calls": _from_openai_tool_calls(choice.tool_calls),
        }
        messages.append(msg)

        if not msg["tool_calls"]:
            if cfg.verbose:
                logger.info(f"[Agent] 模型完成输出，共 {iterations} 次迭代，{total_tool_calls} 次工具调用")
            return iterations, total_tool_calls

        for tc in msg["tool_calls"]:
            total_tool_calls += 1
            tool_name = tc["name"]
            tool_args = tc["args"]
            tool_call_id = tc["id"]

            if cfg.verbose:
                logger.info(f"[Agent] 调用工具: {tool_name}({tool_args})")

            observation = await registry.dispatch(tool_name, tool_args)

            if cfg.verbose:
                logger.info(f"[Agent] 工具返回: {str(observation)[:200]}{'...' if len(str(observation)) > 200 else ''}")

            messages.append({
                "role": "tool",
                "content": str(observation),
                "tool_call_id": tool_call_id,
            })

    # 达到最大迭代次数
    summary = f"已达到最大迭代次数 {cfg.max_iterations}，请基于已有信息给出总结。"
    messages.append({"role": "user", "content": summary})
    openai_msgs = _to_openai_messages(messages)
    response = await client.chat.completions.create(
        messages=openai_msgs,
        tools=tools,
        **_build_request_kwargs(cfg),
    )
    choice = response.choices[0].message
    messages.append({"role": "assistant", "content": choice.content or ""})

    return iterations, total_tool_calls


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
