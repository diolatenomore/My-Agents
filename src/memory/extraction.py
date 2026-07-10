"""LLM 记忆提取 — 从对话轮次中提取偏好、事实、身份信息"""

import json
import re

from openai import AsyncOpenAI

from src.config import DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY
from src.utils.common import logger

# 第一层语义去重
EXTRACTION_PROMPT = """你是一个记忆提取系统。从以下对话中提取关于用户的长期有用信息。

返回一个 JSON 数组，每个元素包含：
- type: "preference" | "fact" | "identity"
- key: (仅 type="preference" 时需要) 简短的英文 snake_case 键名
- value: 一句完整、独立可理解的描述

类型说明：
- preference: 用户的喜好、偏好、习惯。如语言偏好、回复风格、工具选择。必须有 key。
  - 常用 key 示例: language, response_style, code_style, editor, os, framework
- fact: 关于用户项目、工作内容的客观事实。不需要 key。
- identity: 用户的身份信息（姓名、角色、公司、职位）。不需要 key。

规则：
- 只提取明确陈述的信息，不推测
- 如果助手回复中的信息明显是对用户已有记忆的复述/确认（如用户问"我是谁"，助手回答"你是xxx"），**不要提取**，因为这条记忆已存在。
- 没有可提取的内容则返回空数组 []
- 如果用户只是询问/确认已有信息，返回空数组 []
- value 不超过 100 字，必须独立可理解（不依赖上下文）
- preference 必须有明确的 key 字段
- 忽略临时性、一次性的信息（如 "帮我查一下天气"）

用户消息: {query}

助手回复: {response}

只返回 JSON 数组，不要其他内容："""

_MAX_CHARS = 4000  # 单次提取的最大输入字符数
_JSON_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```|(\[[\s\S]*\]\s*$)")


async def extract_memories(query: str, response: str) -> list[dict]:
    """调用 LLM 从单轮对话中提取记忆。

    Args:
        query: 用户消息
        response: 助手最终回复

    Returns:
        提取到的记忆列表 [{"type": ..., "key": ..., "value": ...}, ...]
        解析失败或无可提取内容时返回空列表
    """
    # 截断过长文本
    if len(query) > _MAX_CHARS:
        query = query[:_MAX_CHARS]
    if len(response) > _MAX_CHARS:
        response = response[:_MAX_CHARS]

    prompt = EXTRACTION_PROMPT.format(query=query, response=response)
    # TODO 添加retry重试机制，重新抛给llm（限制输出pydantic模型格式？）
    try:
        client = AsyncOpenAI(base_url=DEEPSEEK_BASE_URL, api_key=DEEPSEEK_API_KEY)
        result = await client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": "只返回 JSON 数组，不返回其他内容。"},
                {"role": "user", "content": prompt},
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
        if memory_type not in ("preference", "fact", "identity"):
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
