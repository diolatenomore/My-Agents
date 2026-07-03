# Memory 模块

基于 ChromaDB 向量数据库的长期记忆系统，用于从对话中提取、存储和检索用户信息。

## 架构

```
对话轮次 (query + response)
        │
        ▼
extraction.py          ── LLM 提取记忆项
        │
        ▼
models.py              ── MemoryItem 数据模型
        │
        ▼
store.py               ── ChromaDB 向量存储
        │
        ▼
service.py             ── 编排层（提取 + 检索 + 格式化）
        │
        ▼
主流程                  ── system prompt 注入 / fire-and-forget 写入
```

## 核心概念

### 记忆类型

| 类型 | 含义 | 去重策略 | 示例 |
|------|------|----------|------|
| `preference` | 用户偏好/习惯 | 按 key upsert | `language: "中文"`, `response_style: "简洁"` |
| `fact` | 客观事实 | 始终追加 | "用户的 Django 项目用的是 MySQL" |
| `identity` | 身份信息 | 始终追加 | "用户是一名后端工程师" |

### 数据流

1. **写入**：每轮对话结束后，fire-and-forget 调用 `extract_from_messages()`，LLM 从 query+response 中提取记忆，写入 ChromaDB
2. **检索**：每轮对话开始前，用用户 query 做语义搜索，将匹配的 preference + fact/identity 格式化为 markdown 注入 system prompt

## 文件说明

### `models.py`
`MemoryItem` 数据类，字段：
- `memory_type`: `"preference"` | `"fact"` | `"identity"`
- `value`: 记忆内容文本
- `key`: 仅 preference 使用，snake_case 键名（如 `"language"`, `"code_style"`）

### `store.py`
`MemoryStore` — ChromaDB 封装：
- `add(items, session_id)` — 批量写入，preference 按 key upsert
- `query(text, n_results)` — 语义搜索 facts + identity
- `get_preferences()` — 获取全部用户偏好
- `delete(memory_id)` — 删除单条
- 使用 ChromaDB 默认 embedding 函数，余弦相似度检索

### `extraction.py`
从对话中提取结构化记忆：
- 函数入口：`extract_memories(query, response)` → `list[dict]`
- 支持 markdown code block 包裹的 JSON 解析
- 带输入截断（单次 4000 字符）和结果校验

### `service.py`
`MemoryService` — 编排层：
- `extract_from_messages(session_id, query, response)` — 提取 + 写入（异步，fire-and-forget）
- `retrieve(query)` — 检索 + 格式化为 system prompt 区块
- `_format_memory_block()` — 将偏好和事实格式化为 markdown

**单例获取**：通过 `get_memory_service()` 获取实例（懒加载，线程安全），首次调用自动初始化 ChromaDB。

## 使用方式

```python
from src.memory.service import get_memory_service

# 获取单例（无需手动初始化）
memory_svc = get_memory_service()

# 检索相关记忆，注入 system prompt
memory_block = memory_svc.retrieve(user_query)

# Fire-and-forget 提取记忆（不阻塞主流程）
asyncio.create_task(
    memory_svc.extract_from_messages(session_id, query, response)
)
```

## 配置

相关配置在 `src/config.py`：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MEMORY_PERSIST_DIR` | `workspace/chroma_memory` | ChromaDB 持久化目录 |
| `MEMORY_EXTRACTION_ENABLED` | `True` | 是否启用记忆提取 |
| `MEMORY_RETRIEVAL_ENABLED` | `True` | 是否启用记忆检索 |
| `MEMORY_MAX_RESULTS` | `5` | 语义搜索返回的最大结果数 |
