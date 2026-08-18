"""LLM 记忆提取 — 审阅完整对话历史，提取可沉淀的记忆"""

import json
import re

from openai import AsyncOpenAI

from src.agent.model_manager import model_manager
from src.utils.common import logger

REVIEW_PROMPT = """请回顾以上对话，判断是否有值得保存到长期记忆中的信息。

返回一个 JSON 数组，每个元素包含：
- type: "preference" | "semantic"
- key: (仅 type="preference" 时需要) 简短的英文 snake_case 键名
- value: 一句完整、独立可理解的描述

关注点：
1. 用户是否透露了关于自身的信息——个人身份、偏好、习惯或其他值得记住的个人细节？
2. 用户是否表达了对助手行为方式的期望、工作风格或运作方式的偏好？

如果发现有价值的信息，请以下列 JSON 格式提取记忆：
[
  {"type": "preference", "key": "language", "value": "用户偏好中文回复"},
  {"type": "semantic", "value": "用户是软件工程师"}
]

类型说明：
- preference: 用户的喜好、偏好、习惯。如语言偏好、回复风格、工具选择。必须有 key。
  - 常用 key 示例: language, response_style, code_style, editor, os, framework
- semantic: 关于用户及其世界的客观事实，包括身份信息、项目信息、工作内容等。不需要 key。

规则：
- 只提取明确陈述的信息，不推测
- 如果助手回复中的信息明显是对用户已有记忆的复述/确认（如用户问"我是谁"，助手回答"你是xxx"），**不要提取**，因为这条记忆已存在。
- 没有可提取的内容则返回空数组 []
- value 不超过 100 字，必须独立可理解（不依赖上下文）
- preference 必须有明确的 key 字段
- 忽略临时性、一次性的信息（如 "帮我查一下天气"）

只返回 JSON 数组，不要其他内容。"""

_MAX_CHARS = 8000  # 完整对话的最大字符数
_JSON_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```|(\[[\s\S]*\]\s*$)")


async def extract_memories(messages: list[dict], model_id: str) -> list[dict]:
    """审阅完整对话历史，提取记忆。

    Args:
        messages: 完整对话消息列表（含 system、user、assistant、tool 等）
        model_id: 模型配置 ID（必传）

    Returns:
        提取到的记忆列表 [{"type": ..., "key": ..., "value": ...}, ...]
        解析失败或无可提取内容时返回空列表
    """
    # 剔除头个 system prompt（Agent 的系统提示词，与记忆提取无关），其余作为上下文
    context = messages[1:] if messages and messages[0].get("role") == "system" else messages

    try:
        client, model_name = await model_manager.resolve_model(model_id)
        result = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "你是一个记忆提取系统，善于从对话中提取长期记忆。"},
                *context,
                {"role": "user", "content": REVIEW_PROMPT},
            ],
            temperature=0.0,
        )
        return _parse_json(result.choices[0].message.content)
    except Exception as e:
        logger.warning(f"记忆提取 LLM 调用失败: {e}")
        return []


def _parse_json(text: str) -> list[dict]:
    """从 LLM 回复中解析 JSON 数组，兼容 markdown code block 包裹"""
    if not text:
        return []

    text = text.strip()

    # 尝试直接解析
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return _validate_items(data)
    except json.JSONDecodeError:
        pass

    # 尝试从 markdown code block 中提取
    match = _JSON_PATTERN.search(text)
    if match:
        json_str = match.group(1) or match.group(2)
        if json_str:
            try:
                data = json.loads(json_str.strip())
                if isinstance(data, list):
                    return _validate_items(data)
            except json.JSONDecodeError:
                pass

    logger.debug(f"记忆提取 JSON 解析失败，原始文本前 200 字符: {text[:200]}")
    return []


def _validate_items(items: list) -> list[dict]:
    """校验并清洗提取结果"""
    valid = []
    for item in items:
        if not isinstance(item, dict):
            continue
        memory_type = item.get("type", "")
        if memory_type not in ("preference", "semantic"):
            continue
        value = item.get("value", "").strip()
        if not value:
            continue

        cleaned = {"type": memory_type, "value": value}

        if memory_type == "preference":
            key = item.get("key", "").strip()
            if not key:
                continue  # preference 必须有 key
            cleaned["key"] = key.lower().replace(" ", "_")
        else:
            cleaned["key"] = ""

        valid.append(cleaned)

    return valid
