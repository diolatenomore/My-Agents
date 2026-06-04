"""Agent 配置"""

from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    """Agent 运行配置"""
    model: str = "deepseek-v4-flash"
    temperature: float = 0.7
    max_iterations: int = 30  # ReAct 循环最大迭代次数
    max_tool_retries: int = 3  # 单个工具最大重试次数 TODO 最大重试是同一工具还是同一工具统一参数？
    verbose: bool = True  # 是否打印中间步骤日志
