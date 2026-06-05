"""ReAct 循环核心 — 单 Agent 自主思考+工具调用循环"""

from dataclasses import dataclass
from typing import AsyncGenerator, Optional

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_openai import ChatOpenAI

from src.agent.agent_config import AgentConfig
from src.agent.prompts import DEFAULT_SYSTEM_PROMPT
from src.config import DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY
from src.tools.registry import registry
from src.utils.common import logger


@dataclass
class AgentResult:
    """Agent 运行结果"""
    content: str  # 最终回复内容
    messages: list  # 完整的消息列表（含中间步骤）
    iterations: int = 0  # 实际迭代次数
    tool_calls_count: int = 0  # 工具调用次数


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
        system_prompt: 自定义 system prompt
        tools: 工具列表，不传则使用所有注册工具

    Returns:
        AgentResult
    """
    cfg = config or AgentConfig()
    tools = tools or registry.get_all_schemas()
    prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    messages = _build_messages(prompt, history, query)

    model = ChatOpenAI(
        model=cfg.model,
        base_url=DEEPSEEK_BASE_URL,
        api_key=DEEPSEEK_API_KEY,
        temperature=cfg.temperature,
    )
    model_with_tools = model.bind_tools(tools)

    iterations, total_tool_calls = await _execute_loop(model_with_tools, messages, cfg)

    # 取最后一条 AI 消息作为最终回复
    final_content = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            final_content = msg.content
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
) -> AsyncGenerator[dict, None]:
    """运行 ReAct Agent 循环（流式版本），逐个 yield 事件

    事件类型:
        - token:     LLM 生成的文本片段（如 {"type":"token","content":"你好"}）
        - tool_call: 模型决定调用工具（如 {"type":"tool_call","name":"list_dir","args":{...}}）
        - tool_result: 工具执行结果（如 {"type":"tool_result","name":"list_dir","result":"..."}）
        - iteration: 开始新一轮迭代（如 {"type":"iteration","num":1}）
        - done:      全部完成（如 {"type":"done","content":"最终回复"}，含 "_messages" 供调用者持久化）
        - error:     发生错误（如 {"type":"error","message":"..."}）

    Args:
        query: 用户输入
        history: 历史消息列表（由调用者从持久化存储加载）
        config: Agent 配置
        system_prompt: 自定义 system prompt
        tools: 工具列表，不传则使用所有注册工具

    Yields:
        dict: SSE 兼容的事件字典
    """
    cfg = config or AgentConfig()
    tools = tools or registry.get_all_schemas()
    prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    messages = _build_messages(prompt, history, query)

    try:
        model = ChatOpenAI(
            model=cfg.model,
            base_url=DEEPSEEK_BASE_URL,
            api_key=DEEPSEEK_API_KEY,
            temperature=cfg.temperature,
            streaming=True,
        )
        model_with_tools = model.bind_tools(tools)

        for iteration in range(1, cfg.max_iterations + 1):
            yield {"type": "iteration", "num": iteration}

            if cfg.verbose:
                logger.info(f"[Agent] 迭代 {iteration}/{cfg.max_iterations}")

            # 收集本次 LLM 回复
            full_content = ""
            aggregated = None

            async for chunk in model_with_tools.astream(messages):
                # AIMessageChunk 支持 += 聚合
                if aggregated is None:
                    aggregated = chunk
                else:
                    aggregated += chunk

                # 吐出文本 token
                if chunk.content:
                    full_content += chunk.content
                    yield {"type": "token", "content": chunk.content}

            # astream 结束后，aggregated 包含完整响应
            # 注意：aggregated 是 AIMessageChunk，需转为 AIMessage 确保 tool_calls 正确序列化
            msg = AIMessage(
                content=full_content,
                tool_calls=list(aggregated.tool_calls) if aggregated.tool_calls else [],
            )
            messages.append(msg)

            # 没有工具调用 → 模型完成
            if not msg.tool_calls:
                yield {"type": "done", "content": full_content, "_messages": messages}
                return

            # 执行工具调用
            for tool_call in msg.tool_calls:
                tool_name = tool_call.get("name") if isinstance(tool_call, dict) else tool_call.name
                tool_args = tool_call.get("args") if isinstance(tool_call, dict) else tool_call.args
                tool_call_id = tool_call.get("id") if isinstance(tool_call, dict) else tool_call.id
                # 安全兜底：如果流式返回缺少 id，生成一个
                if not tool_call_id:
                    tool_call_id = f"call_{tool_name}"

                yield {"type": "tool_call", "name": tool_name, "args": tool_args}

                if cfg.verbose:
                    logger.info(f"[Agent] 调用工具: {tool_name}({tool_args})")

                try:
                    observation = registry.dispatch(tool_name, tool_args)
                except Exception as e:
                    observation = f"工具执行失败: {e}"
                    logger.error(f"[Agent] 工具 '{tool_name}' 执行失败: {e}")

                if cfg.verbose:
                    logger.info(
                        f"[Agent] 工具返回: {str(observation)[:200]}{'...' if len(str(observation)) > 200 else ''}"
                    )

                yield {"type": "tool_result", "name": tool_name, "result": str(observation)}

                messages.append(ToolMessage(
                    content=str(observation),
                    tool_call_id=tool_call_id,
                ))

        # 达到最大迭代次数
        summary = f"已达到最大迭代次数 {cfg.max_iterations}，请基于已有信息给出总结。"
        messages.append(HumanMessage(content=summary))
        final_response = await model_with_tools.ainvoke(messages)
        messages.append(final_response)
        yield {"type": "done", "content": final_response.content or "", "_messages": messages}

    except Exception as e:
        logger.error(f"[Agent] 流式执行出错: {e}", exc_info=True)
        yield {"type": "error", "message": str(e)}


def _build_messages(
    system_prompt: str, history: Optional[list], query: str
) -> list:
    """构建消息列表"""
    messages = [SystemMessage(content=system_prompt)]
    if history:
        messages.extend(history)
    messages.append(HumanMessage(content=query))
    return messages


async def _execute_loop(model_with_tools, messages, cfg):
    """非流式版本的 ReAct 循环执行体"""
    iterations = 0
    total_tool_calls = 0

    while iterations < cfg.max_iterations:
        iterations += 1

        if cfg.verbose:
            logger.info(f"[Agent] 迭代 {iterations}/{cfg.max_iterations}")

        response = await model_with_tools.ainvoke(messages)
        messages.append(response)

        if not response.tool_calls:
            if cfg.verbose:
                logger.info(f"[Agent] 模型完成输出，共 {iterations} 次迭代，{total_tool_calls} 次工具调用")
            return iterations, total_tool_calls

        for tool_call in response.tool_calls:
            total_tool_calls += 1
            tool_name = tool_call.get("name") if isinstance(tool_call, dict) else tool_call.name
            tool_args = tool_call.get("args") if isinstance(tool_call, dict) else tool_call.args
            tool_call_id = tool_call.get("id") if isinstance(tool_call, dict) else tool_call.id

            if cfg.verbose:
                logger.info(f"[Agent] 调用工具: {tool_name}({tool_args})")

            observation = registry.dispatch(tool_name, tool_args)

            if cfg.verbose:
                logger.info(f"[Agent] 工具返回: {str(observation)[:200]}{'...' if len(str(observation)) > 200 else ''}")

            messages.append(ToolMessage(
                content=str(observation),
                tool_call_id=tool_call_id,
            ))

    # 达到最大迭代次数
    summary = f"已达到最大迭代次数 {cfg.max_iterations}，请基于已有信息给出总结。"
    messages.append(HumanMessage(content=summary))
    final_response = await model_with_tools.ainvoke(messages)
    messages.append(final_response)

    return iterations, total_tool_calls
