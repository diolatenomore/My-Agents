import os

_project_root = os.path.dirname(os.path.abspath(__file__))  # 获取 src 目录
_project_root = os.path.dirname(_project_root)  # 获取项目根目录

# 模型配置
MODEL = "deepseek-v3.2"

# checkpoint数据库配置
CHECKPOINT_DB_PATH = os.path.join(_project_root, "/workspace/checkpoints.db")

# TaskManager最大worker数配置
MAX_WORKERS = 4

# 代理工作区配置
AGENT_WORKSPACE = os.path.join(_project_root, "/workspace/agent_workspace")
