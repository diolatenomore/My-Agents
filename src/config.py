import os

_project_root = os.path.dirname(os.path.abspath(__file__))  # 获取 src 目录
_project_root = os.path.dirname(_project_root)  # 获取项目根目录

# 模型配置
MODEL = "deepseek-v4-flash"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# checkpoint数据库配置
CHECKPOINT_DB_PATH = os.path.join(_project_root, "workspace/checkpoints.db")

# 数据库连接池配置
DB_PATH = os.path.join(_project_root, "workspace/ai_agents.db")
MAX_CONNECTIONS = 3
CONNECT_TIMEOUT = 20

# TaskManager最大worker数配置
MAX_WORKERS = 4

# 代理工作区配置
AGENT_WORKSPACE_PATH = os.path.join(_project_root, "workspace/agent_workspace")

# 暂存区路径配置
STAGING_AREA_PATH = os.path.join(_project_root, "workspace/staging_area")
