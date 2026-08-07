"""模型配置管理器 — 管理多模型配置，API Key 通过环境变量 + .env 文件管理"""

import os
import re
import uuid
from typing import Optional

import httpx
from openai import AsyncOpenAI

from src.db.sqlite_pool import db_pool
from src.utils.common import logger

ENV_KEY_PREFIX = "AI_MODEL_KEY_"
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _sanitize_name(name: str) -> str:
    """将模型名称转为安全的环境变量名后缀（大写、下划线、去特殊字符）"""
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    sanitized = re.sub(r'_+', '_', sanitized)
    return sanitized.strip('_').upper()


def _env_file_path() -> str:
    return os.path.join(_PROJECT_ROOT, ".env")


class ModelManager:
    """模型配置管理器（单例）"""

    _instance: Optional["ModelManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    async def init_models(self):
        """启动时加载 .env 文件"""
        if self._initialized:
            return

        _load_dotenv()
        self._initialized = True
        logger.info("模型管理器初始化完成")

    async def list_models(self) -> list[dict]:
        """列出所有模型配置（不含 api_key）"""
        async with db_pool.get_conn() as conn:
            cursor = await conn.execute(
                "SELECT id, name, base_url, model, env_var_name, is_active, "
                "max_context_tokens, max_output_tokens, max_tool_calls, "
                "created_at, updated_at "
                "FROM model_configs ORDER BY created_at DESC"
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_model(self, model_id: str) -> Optional[dict]:
        """获取单个模型详情（不含 api_key）"""
        async with db_pool.get_conn() as conn:
            cursor = await conn.execute(
                "SELECT id, name, base_url, model, env_var_name, is_active, "
                "max_context_tokens, max_output_tokens, max_tool_calls, "
                "created_at, updated_at "
                "FROM model_configs WHERE id = ?", (model_id,)
            )
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def create_model(self, name: str, base_url: str, model: str, api_key: str,
                           max_context_tokens: int = 200000, max_output_tokens: int = 64000,
                           max_tool_calls: int = 50) -> dict:
        """创建新模型配置"""
        model_id = str(uuid.uuid4())
        env_var_name = f"{ENV_KEY_PREFIX}{_sanitize_name(name)}"

        # 写入 .env 文件 + os.environ
        self._write_env_var(env_var_name, api_key)

        async with db_pool.get_conn() as conn:
            await conn.execute(
                "INSERT INTO model_configs (id, name, base_url, model, env_var_name, "
                "max_context_tokens, max_output_tokens, max_tool_calls) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (model_id, name, base_url, model, env_var_name,
                 max_context_tokens, max_output_tokens, max_tool_calls),
            )

        logger.info(f"模型配置已创建: {name} (id={model_id})")
        return await self.get_model(model_id)

    async def update_model(self, model_id: str, name: Optional[str] = None,
                           base_url: Optional[str] = None, model: Optional[str] = None,
                           api_key: Optional[str] = None,
                           max_context_tokens: Optional[int] = None,
                           max_output_tokens: Optional[int] = None,
                           max_tool_calls: Optional[int] = None) -> Optional[dict]:
        """更新模型配置"""
        existing = await self.get_model(model_id)
        if not existing:
            return None

        new_name = name or existing["name"]
        new_base_url = base_url or existing["base_url"]
        new_model = model or existing["model"]

        # 如果 api_key 有更新，写入环境变量
        if api_key:
            self._write_env_var(existing["env_var_name"], api_key)

        # 如果名称变更，更新 env_var_name
        new_env_var_name = existing["env_var_name"]
        if name and name != existing["name"]:
            new_env_var_name = f"{ENV_KEY_PREFIX}{_sanitize_name(name)}"
            current_key = os.environ.get(existing["env_var_name"], "")
            if current_key:
                self._write_env_var(new_env_var_name, current_key)

        # 构建动态 UPDATE 语句
        set_clauses = ["name=?", "base_url=?", "model=?", "env_var_name=?", "updated_at=datetime('now')"]
        params = [new_name, new_base_url, new_model, new_env_var_name]

        if max_context_tokens is not None:
            set_clauses.append("max_context_tokens=?")
            params.append(max_context_tokens)
        if max_output_tokens is not None:
            set_clauses.append("max_output_tokens=?")
            params.append(max_output_tokens)
        if max_tool_calls is not None:
            set_clauses.append("max_tool_calls=?")
            params.append(max_tool_calls)

        params.append(model_id)

        async with db_pool.get_conn() as conn:
            await conn.execute(
                f"UPDATE model_configs SET {', '.join(set_clauses)} WHERE id=?",
                params,
            )

        logger.info(f"模型配置已更新: {new_name} (id={model_id})")
        return await self.get_model(model_id)

    async def delete_model(self, model_id: str) -> bool:
        """删除模型配置"""
        existing = await self.get_model(model_id)
        if not existing:
            return False

        async with db_pool.get_conn() as conn:
            await conn.execute("DELETE FROM model_configs WHERE id=?", (model_id,))

        # 清理对应的环境变量
        self._remove_env_var(existing["env_var_name"])

        logger.info(f"模型配置已删除: {existing['name']} (id={model_id})")
        return True

    async def resolve_model(self, model_id: str) -> tuple[AsyncOpenAI, str]:
        """解析模型配置并创建客户端，同时返回 model 标识符

        Args:
            model_id: 模型配置 ID（必传）

        Returns:
            (AsyncOpenAI 客户端, model 标识符)

        Raises:
            ValueError: 模型不存在或 API Key 未配置
        """
        if not model_id:
            raise ValueError("未指定模型，请先在模型管理中添加并选择模型")

        model_config = await self.get_model(model_id)
        if not model_config:
            raise ValueError(f"模型配置不存在 (id={model_id})")

        api_key = os.environ.get(model_config["env_var_name"], "")
        if not api_key:
            raise ValueError(f"环境变量 {model_config['env_var_name']} 未设置，请检查 .env 文件")

        # 连接超时 10s，read 超时 120s（兼容思考模式等长时间无输出的场景）
        timeout = httpx.Timeout(120.0, connect=10.0)
        return (AsyncOpenAI(base_url=model_config["base_url"], api_key=api_key, timeout=timeout),
                model_config["model"])

    def _write_env_var(self, key: str, value: str):
        """写入环境变量到 os.environ 和 .env 文件"""
        # 1. 写入当前进程环境变量
        os.environ[key] = value

        # 2. 追加/更新 .env 文件
        env_path = _env_file_path()
        lines = []
        found = False
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} "):
                        lines.append(f"{key}={value}\n")
                        found = True
                    else:
                        lines.append(line)
        if not found:
            lines.append(f"{key}={value}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    def _remove_env_var(self, key: str):
        """从 os.environ 和 .env 文件中移除环境变量"""
        # 1. 从当前进程移除
        os.environ.pop(key, None)

        # 2. 从 .env 文件中移除对应行
        env_path = _env_file_path()
        if not os.path.exists(env_path):
            return

        lines = []
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not (stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ")):
                    lines.append(line)

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)


def _load_dotenv():
    """加载 .env 文件到 os.environ（不覆盖已有系统环境变量）"""
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file_path(), override=False)
    except ImportError:
        logger.warning("python-dotenv 未安装，无法自动加载 .env 文件")


# 全局单例
model_manager = ModelManager()
