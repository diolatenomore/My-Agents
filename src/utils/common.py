import logging
from typing import Any

def extract_content(response: Any) -> str:
    """提取响应内容"""
    if isinstance(response, dict):
        if "messages" in response:
            messages = response["messages"]
            if messages:
                return str(messages[-1])
        elif "result" in response:
            return str(response["result"])
        else:
            return str(response)
    else:
        # 处理LangChain响应对象
        if hasattr(response, 'content'):
            return response.content
        # 处理其他对象
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