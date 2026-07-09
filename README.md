# AI-Agents

基于 ReAct 循环的 AI 智能体系统，提供 FastAPI 接口，支持工具调用、技能扩展、虚拟文件系统和长期记忆。

## 核心特性

- **ReAct 自主循环**：单 Agent 通过 Think → Act → Observe 循环自主决策和调用工具，无需硬编码工作流
- **流式输出 (SSE)**：实时推送思考过程、工具调用和结果，支持 `/api/chat/stream` 端点
- **会话管理**：SQLite 持久化多轮对话历史，支持会话列表、删除和消息查询
- **工具系统**：自注册式工具注册中心，支持 VFS 文件操作、HTTP 请求、搜索、Shell 命令执行
- **技能扩展 (Skills)**：基于 agentskills.io 标准的三级渐进式披露，模型可自主加载技能指令
- **虚拟文件系统 (VFS)**：写时复制 (Copy-on-Write) 暂存区，所有文件修改需审批后落盘
- **长期记忆**：ChromaDB 向量存储，自动从对话中提取偏好和事实，跨会话注入 system prompt

## 项目结构

```
ai-agents/
├── config/                    # 配置文件
│   ├── config.py              # YAML 配置加载器
│   └── default.yaml           # 默认配置
├── src/                       # 源代码
│   ├── main.py                # FastAPI 入口（路由、中间件、VFS 审批 API）
│   ├── config.py              # 项目配置（模型、数据库、路径等）
│   ├── agent/                 # Agent 核心
│   │   ├── react_loop.py      # ReAct 循环（流式 + 非流式）
│   │   ├── agent_config.py    # Agent 运行时配置
│   │   └── prompts.py         # 默认 System Prompt
│   ├── agents/                # 旧版提示词（workflow 遗留）
│   ├── db/                    # 数据库
│   │   ├── sqlite_pool.py     # SQLite 异步连接池
│   │   └── init_db.py         # 表结构初始化
│   ├── mcp/                   # MCP 客户端
│   │   └── client.py
│   ├── memory/                # 长期记忆
│   │   ├── service.py         # MemoryService（提取 + 检索编排）
│   │   ├── extraction.py      # LLM 记忆提取
│   │   ├── store.py           # ChromaDB 向量存储
│   │   └── models.py          # 记忆数据模型
│   ├── models/                # 数据模型
│   │   ├── http_dtos.py       # HTTP 请求/响应 DTO
│   │   ├── state.py           # LangGraph 状态
│   │   └── task.py            # 任务模型
│   ├── scheduler/             # 旧版任务调度（向后兼容保留）
│   ├── session/               # 会话管理
│   │   ├── manager.py         # SessionManager（锁 + 历史管理）
│   │   ├── models.py          # Session 数据模型
│   │   └── store.py           # SQLite 存储层
│   ├── skills/                # 技能系统
│   │   ├── loader.py          # SkillLoader（扫描、缓存、渐进式披露）
│   │   └── skills_config.json # 技能启用/禁用配置
│   ├── tools/                 # 工具系统
│   │   ├── registry.py        # ToolRegistry 自注册单例
│   │   ├── loader.py          # 工具发现与加载
│   │   ├── vfs_tools.py       # 文件操作工具（list_dir, create_file 等 13 个）
│   │   ├── web_tools.py       # 网络工具（web_request, web_search）
│   │   ├── execute_tools.py   # Shell 命令执行
│   │   └── skill_tools.py     # 技能工具（load_skill, list_skills）
│   ├── utils/                 # 工具函数
│   │   ├── common.py          # 日志、内容提取等
│   │   └── vfs.py             # VFS 辅助函数
│   ├── vfs/                   # 虚拟文件系统
│   │   ├── operations.py      # 文件操作（CRUD、复制、移动等）
│   │   ├── staging_area.py    # 暂存区管理
│   │   ├── copy_mapping.py    # 写时复制映射
│   │   ├── diff_table.py      # 差异记录表
│   │   ├── review_manager.py  # 审批管理器
│   │   └── task_context.py    # 任务上下文传递
│   └── workflow/              # 旧版 LangGraph 工作流（向后兼容保留）
├── skills/                    # 技能目录
├── tests/                     # 测试
├── workspace/                 # 运行时数据
│   ├── agent_workspace/       # Agent 工作目录
│   ├── chroma_memory/         # ChromaDB 持久化目录
│   └── ai_agents.db*          # SQLite 数据库
└── src/test_chat.html         # 测试聊天页面
```

## 快速开始

### 环境要求

- Python 3.12+
- DeepSeek API Key

### 安装

```bash
# 安装依赖
pip install fastapi uvicorn openai httpx aiosqlite langchain-core langgraph chromadb tavily-python pydantic pyyaml

# 设置 API Key
export DEEPSEEK_API_KEY="your-deepseek-api-key"

# 可选：启用网络搜索
export TAVILY_API_KEY="your-tavily-api-key"
```

### 启动服务

```bash
python -m src.main
```

服务启动后访问 `http://localhost:8000` 可看到测试聊天页面。

### API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 测试聊天页面 |
| `POST` | `/api/chat` | 非流式聊天 |
| `POST` | `/api/chat/stream` | SSE 流式聊天 |
| `GET` | `/api/sessions` | 会话列表 |
| `DELETE` | `/api/sessions/{id}` | 删除会话 |
| `GET` | `/api/sessions/{id}/messages` | 会话消息记录 |
| `GET` | `/api/vfs/review/{task_id}` | 获取审批树 |
| `POST` | `/api/vfs/review/{task_id}` | 审批全部变更 |
| `POST` | `/api/vfs/review/{task_id}/item/{item_id}` | 审批单条变更 |

### 使用示例

```python
import requests

# 非流式聊天
resp = requests.post("http://localhost:8000/api/chat", json={
    "query": "你好，帮我看看当前目录下有什么文件",
    "session_id": "my-session"
})
print(resp.json())

# 流式聊天（SSE）
import json

resp = requests.post(
    "http://localhost:8000/api/chat/stream",
    json={"query": "搜索最新AI新闻", "session_id": "my-session"},
    stream=True
)
for line in resp.iter_lines():
    if line.startswith(b"data:"):
        data = json.loads(line[5:])
        print(data["type"], data.get("content", ""))
```

### 通过 /skill 指令加载技能

在对话中使用 `/skill:skill-name` 指令可以加载指定技能的完整指令：

```
/skill:file-organize 帮我整理 ~/Documents 下的文件
/skill:bilibili-all-in-one 下载视频 BV1xx411c7mD
```

## 配置

主配置文件为 [config.py](file:///Users/tinklingowl/PycharmProjects/AI-Agents/src/config.py)：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `MODEL` | LLM 模型 | `deepseek-v4-flash` |
| `DEEPSEEK_BASE_URL` | API 地址 | `https://api.deepseek.com/v1` |
| `DEEPSEEK_API_KEY` | API Key（环境变量） | - |
| `DB_PATH` | SQLite 数据库路径 | `workspace/ai_agents.db` |
| `MAX_CONNECTIONS` | 数据库连接池大小 | `4` |
| `MAX_WORKERS` | 最大任务并发数 | `4` |
| `AGENT_WORKSPACE_PATH` | Agent 工作目录 | `workspace/agent_workspace` |
| `STAGING_AREA_PATH` | VFS 暂存区路径 | `workspace/staging_area` |
| `MEMORY_PERSIST_DIR` | ChromaDB 持久化目录 | `workspace/chroma_memory` |
| `MEMORY_RETRIEVAL_ENABLED` | 启用长期记忆检索 | `true` |

## 技能管理

技能通过 [skills/skills_config.json](file:///Users/tinklingowl/PycharmProjects/AI-Agents/skills/skills_config.json) 控制启用/禁用：

```json
{
  "disabled": ["university-applications"]
}
```

## 技术栈

- **Web 框架**：FastAPI + Uvicorn
- **LLM**：DeepSeek API (OpenAI 兼容)
- **数据库**：SQLite + aiosqlite 异步连接池
- **向量存储**：ChromaDB
- **搜索引擎**：Tavily
- **异步**：asyncio + async/await
