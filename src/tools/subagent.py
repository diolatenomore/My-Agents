"""委派工具 — 主 Agent 将子任务委派给子 Agent

子 Agent 复用父 Agent 的模型，使用独立上下文（不继承父对话历史），
仅返回最终 summary 给父 Agent。子 Agent 工具集 = 全量工具 - 屏蔽集。
"""

import asyncio
import json
from typing import Optional

from pydantic import BaseModel, Field

from src.agent.model_manager import model_manager
from src.agent.react_loop import _to_openai_messages, _build_request_kwargs
from src.tools.registry import registry
from src.utils.common import logger

_SUBAGENT_BLOCKED_TOOLS = frozenset({"delegate_task", "query_memory", "save_memory"})

_CHILD_PROMPT = """你是一个专注于执行委派任务的子智能体。

YOUR TASK（你的任务）:
{goal}

CONTEXT（上下文背景）:
{context}

请使用你拥有的工具完成任务。完成后，给出简洁清晰的总结，包括：
- 你做了什么
- 你发现或完成了什么
- 你创建或修改的文件
- 遇到的问题

总结要紧凑：以结论开头，多用要点，不要复述整个过程。你的回复会作为摘要返回给主智能体，过长的摘要会挤占主智能体的上下文。
"""


class DelegateTaskInput(BaseModel):
    goal: str = Field(description="要委派给子智能体的单个任务目标，描述清晰、自包含")
    context: str = Field(
        default="",
        description="子智能体完成任务所需的背景信息。子智能体看不到本次对话历史，所有必要信息都要写在这里",
    )


def _build_child_prompt(goal: str, context: Optional[str] = None) -> str:
    return _CHILD_PROMPT.format(goal=goal, context=context or "（无额外上下文）")

# TODO cancel事件和超时处理
async def run_subagent(
    model_id: str,
    prompt: str,
    tools: list,
    cancel_event: Optional[asyncio.Event] = None,
) -> str:
    """运行一个隔离上下文的子 Agent，返回最终 summary 文本"""
    client, model_config = await model_manager.resolve_model(model_id)
    max_iterations = model_config.get("max_iterations", 30)

    messages = [
        {"role": "user", "content": prompt},
    ]

    last_content = ""
    try:
        for _ in range(max_iterations):
            # 迭代间隙检查：主 Agent 是否已取消
            if cancel_event and cancel_event.is_set():
                return "用户中断了对话"

            response = await client.chat.completions.create(
                messages=_to_openai_messages(messages),
                tools=tools,
                **_build_request_kwargs(model_config),
            )
            message = response.choices[0].message
            content = message.content or ""
            last_content = content

            if not message.tool_calls:
                return content

            tool_calls = []
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append({"id": tc.id, "name": tc.function.name, "args": args})

            assistant_msg = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            # 顺序执行工具（内部默认通过，无需审批）
            for tc in tool_calls:
                # 每个工具执行前检查取消信号
                if cancel_event and cancel_event.is_set():
                    return "用户中断了对话"

                try:
                    result_str = str(await registry.dispatch(tc["name"], tc["args"]))
                except Exception as e:
                    result_str = f"工具执行失败: {e}"
                    logger.error(f"[SubAgent] 工具 '{tc['name']}' 执行失败: {e}")
                messages.append({
                    "role": "tool",
                    "content": result_str,
                    "tool_call_id": tc["id"],
                })

        # 达到迭代上限：追加总结 prompt，不带工具让 LLM 基于历史对话总结
        logger.warning("[SubAgent] 达到迭代上限，请求 LLM 总结")
        messages.append({
            "role": "user",
            "content": "你已达到工具调用上限，请基于以上对话历史，直接给出最后的总结",
        })
        try:
            response = await client.chat.completions.create(
                messages=_to_openai_messages(messages),
                **_build_request_kwargs(model_config),
            )
            summary = response.choices[0].message.content or ""
            return summary or "子智能体达到迭代上限，最后的输出为：\n" + last_content
        except Exception as e:
            logger.error(f"[SubAgent] 总结请求失败: {e}")
            return summary or "子智能体达到迭代上限，最后的输出为：\n" + last_content

    except asyncio.CancelledError:
        logger.info("[SubAgent] Task 被外部取消")
        return "用户中断了对话"


async def _delegate_subagent(
    goal: str,
    context: str = "",
    _model_id: str = "",
    _cancel_event: Optional[asyncio.Event] = None,
) -> str:
    if not _model_id:
        return "错误：无法获取当前模型配置，无法启动子智能体"

    # 子 Agent 屏蔽工具：delegate_task（避免递归）、query_memory/save_memory（不读写长期记忆）
    allowed = [n for n in registry.list_tools() if n not in _SUBAGENT_BLOCKED_TOOLS]
    tools = registry.get_schemas(allowed)

    try:
        result = await run_subagent(
            model_id=_model_id,
            prompt=_build_child_prompt(goal, context),
            tools=tools,
            cancel_event=_cancel_event,
        )
    except Exception as e:
        return f"子智能体执行出错: {e}"

    return result or "(子智能体未返回结果)"


registry.register(
    name="delegate_task",
    description=(
        "把复杂子任务委派给一个子智能体在独立上下文中执行，子智能体只把最终总结返回给你。"
        "适用于：推理密集的子任务、会淹没主上下文的大量中间数据、可独立完成的工作。"
        "不适用于：单次工具调用（直接调工具即可）、需要与用户交互的任务（子智能体无法提问）。"
        "子智能体看不到当前对话历史，如过需要背景信息，就通过 context 传入所有必要信息。"
    ),
    handler=_delegate_subagent,
    args_schema=DelegateTaskInput,
    requires_approval=True,
)
