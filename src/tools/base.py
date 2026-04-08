from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

class Tool(ABC):
    """工具基类"""
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
    
    @abstractmethod
    def run(self, **kwargs) -> Any:
        """运行工具"""
        pass
    
    def get_info(self) -> Dict:
        """获取工具信息"""
        return {
            "name": self.name,
            "description": self.description
        }