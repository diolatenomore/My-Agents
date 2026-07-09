"""Agent 配置"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentConfig:
    """Agent 运行配置"""
    model: str = "deepseek-v4-flash"
    temperature: float = 0.7
    max_iterations: int = 30  # ReAct 循环最大迭代次数
    max_tool_retries: int = 3  # 单个工具最大重试次数 TODO 最大重试是同一工具还是同一工具统一参数？
    verbose: bool = True  # 是否打印中间步骤日志
    think: bool = True  # 是否启用 DeepSeek 思考模式（extra_body thinking enabled/disabled）
    reasoning_effort: Optional[str] = None  # OpenAI 推理强度: "low" | "medium" | "high"，None 表示不传
