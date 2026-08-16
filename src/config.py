import os

_project_root = os.path.dirname(os.path.abspath(__file__))  # 获取 src 目录
_project_root = os.path.dirname(_project_root)  # 获取项目根目录

# 模型配置
MODEL = "deepseek-v4-flash"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# checkpoint数据库配置
CHECKPOINT_DB_PATH = os.path.join(_project_root, "workspace", "checkpoints.db")

# 数据库连接池配置
DB_PATH = os.path.join(_project_root, "workspace", "ai_agents.db")
MAX_CONNECTIONS = 4
CONNECT_TIMEOUT = 5
CLOSE_TIMEOUT = 5

# TaskManager最大worker数配置
MAX_WORKERS = 4

# 代理工作区配置
AGENT_WORKSPACE_PATH = os.path.join(_project_root, "workspace", "agent_workspace")

# 暂存区路径配置
STAGING_AREA_PATH = os.path.join(_project_root, "workspace", "staging_area")

# System Prompt 冻结时间（秒），同一 session 在 TTL 内复用首个 prompt
SYSTEM_PROMPT_FREEZE_TTL = 10800  # 默认 3 小时

# 记忆提取间隔（对话轮次数），每 N 轮对话提取一次记忆
MEMORY_EXTRACTION_INTERVAL = 10

# 长期记忆配置
MEMORY_PERSIST_DIR = os.path.join(_project_root, "workspace", "chroma_memory")
MEMORY_EXTRACTION_ENABLED = True
MEMORY_RETRIEVAL_ENABLED = True
MEMORY_MAX_RESULTS = 5
# 记忆写入前的语义去重阈值（余弦距离，越小越相似）
# 新记忆与已有同类型记忆的余弦距离 <= 此阈值时，跳过写入
MEMORY_DEDUP_THRESHOLD = 0.2
# 记忆检索时间衰减系数 λ（指数衰减 e^(-λ × days)）
# λ 越大衰减越快，0 表示不衰减。建议值 0.01 ~ 0.1
MEMORY_DECAY_LAMBDA = 0.05

# 上下文压缩配置
COMPACTION_TAIL_TOKEN_RATIO = 0.20   # 尾部 token 预算占可用窗口的比例
COMPACTION_MIN_TAIL_COUNT = 5        # 尾部最少保留消息数
COMPACTION_BUDGET_OVERFLOW = 1.5     # 单条消息可超出预算的倍数
COMPACTION_HEAD_COUNT = 3            # 头部保护的非 system 消息数
COMPACTION_TOOL_TRIM_THRESHOLD = 200 # Phase 1 工具输出裁剪字符阈值

# 显式注入的技能数量上限（每个 skill 为完整 SKILL.md，防止上下文爆炸）
MAX_INJECT_SKILLS = 3
