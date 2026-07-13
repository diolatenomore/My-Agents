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
MAX_CONNECTIONS = 4
CONNECT_TIMEOUT = 5
CLOSE_TIMEOUT = 5

# TaskManager最大worker数配置
MAX_WORKERS = 4

# 代理工作区配置
AGENT_WORKSPACE_PATH = os.path.join(_project_root, "workspace/agent_workspace")

# 暂存区路径配置
STAGING_AREA_PATH = os.path.join(_project_root, "workspace/staging_area")

# System Prompt 冻结时间（秒），同一 session 在 TTL 内复用首个 prompt
SYSTEM_PROMPT_FREEZE_TTL = 10800  # 默认 3 小时

# 长期记忆配置
MEMORY_PERSIST_DIR = os.path.join(_project_root, "workspace/chroma_memory")
MEMORY_EXTRACTION_ENABLED = True
MEMORY_RETRIEVAL_ENABLED = True
MEMORY_MAX_RESULTS = 5
# 记忆写入前的语义去重阈值（余弦距离，越小越相似）
# 新记忆与已有同类型记忆的余弦距离 <= 此阈值时，跳过写入
MEMORY_DEDUP_THRESHOLD = 0.2
