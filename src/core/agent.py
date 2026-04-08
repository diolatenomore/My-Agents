from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class Agent(ABC):
    """智能体基类"""
    
    def __init__(self, name: str, config: Optional[Dict] = None):
        self.name = name
        self.config = config or {}
        self.tools = []
    
    @abstractmethod
    def run(self, task: str, **kwargs) -> Any:
        """运行智能体"""
        pass
    
    def add_tool(self, tool):
        """添加工具"""
        self.tools.append(tool)
    
    def get_tool(self, tool_name: str):
        """获取工具"""
        for tool in self.tools:
            if tool.name == tool_name:
                return tool
        return None
    
    def execute_tool(self, tool_name: str, **kwargs) -> Any:
        """执行工具"""
        tool = self.get_tool(tool_name)
        if tool:
            return tool.run(**kwargs)
        else:
            raise ValueError(f"Tool {tool_name} not found")