import logging
from typing import Any

from langchain_core.messages import AIMessage


def extract_content(response: Any) -> str:
    """提取响应内容"""
    if isinstance(response, str):
        return response
    if isinstance(response, AIMessage):
        return str(response.content) if response.content else ""
    if isinstance(response, dict):
        # 尝试提取常见字段
        if "content" in response:
            return str(response["content"])
        if "messages" in response and isinstance(response["messages"], list):
            # 取最后一条 AI 消息
            for msg in reversed(response["messages"]):
                if isinstance(msg, AIMessage):
                    return str(msg.content)
                if isinstance(msg, dict) and msg.get("type") == "ai":
                    return str(msg.get("content", ""))
    # 其他类型转字符串
    return str(response)

def setup_logger(name: str) -> logging.Logger:
    """设置日志记录器"""
    _logger = logging.getLogger("AI-Agents")
    # 设置日志级别
    _logger.setLevel(logging.INFO)

    # 清除现有的处理器
    _logger.handlers.clear()
    _logger.propagate = False
    # 创建格式化器
    formatter = logging.Formatter(
        '%(asctime)s - [%(filename)s:%(lineno)d] - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    _logger.addHandler(console_handler)
    return _logger

logger = setup_logger(__name__)