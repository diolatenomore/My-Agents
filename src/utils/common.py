import uuid
import logging
from typing import Any, Dict
from config.config import config

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
        return str(response)

def generate_task_id() -> str:
    """生成任务ID"""
    return str(uuid.uuid4())

def setup_logger(name: str) -> logging.Logger:
    """设置日志记录器"""
    logger = logging.getLogger(name)
    
    # 设置日志级别
    level = config.get("logging.level", "INFO")
    logger.setLevel(getattr(logging, level))
    
    # 检查是否已经有处理器
    if not logger.handlers:
        # 创建控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, level))
        
        # 创建文件处理器
        file_handler = logging.FileHandler(config.get("logging.file", "agent.log"))
        file_handler.setLevel(getattr(logging, level))
        
        # 设置日志格式
        formatter = logging.Formatter(config.get("logging.format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)
        
        # 添加处理器
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
    
    return logger