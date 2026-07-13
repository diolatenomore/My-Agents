"""SystemPromptCache — 以 model 为 key 的 system prompt 冻结缓存

每个 model 只保留最新活跃 session 的 prompt，配合 TTL 实现惰性过期。
确保同一 (model, session) 在 TTL 内复用相同的 system prompt，从而维持
模型提供商侧的上下文前缀缓存（Context Prefix Caching）有效性。
"""

import time
from src.config import SYSTEM_PROMPT_FREEZE_TTL


class SystemPromptCache:
    """以 model 为 key 的 system prompt 缓存，每个 model 只缓存最新 session 的 prompt"""

    def __init__(self, ttl: int = SYSTEM_PROMPT_FREEZE_TTL):
        # _cache[model] = {"session_id": str, "prompt": str, "expires_at": float}
        self._cache: dict[str, dict] = {}
        self._ttl = ttl

    def get(self, model: str, session_id: str) -> str | None:
        """获取冻结 prompt。

        命中条件：model 已缓存、session_id 匹配、未过期。
        命中后会刷新过期时间（续期 TTL），避免活跃 session 中途过期。
        若 model 命中了但 session 不匹配 → 旧 session 的缓存不再适用，清除并返回 None。
        """
        entry = self._cache.get(model)
        if entry is None:
            return None

        if entry["session_id"] != session_id:
            # 同一模型不同 session → 旧 session 的缓存不再适用，清掉
            del self._cache[model]
            return None

        if time.time() >= entry["expires_at"]:
            del self._cache[model]
            return None

        # 命中：续期 TTL
        entry["expires_at"] = time.time() + self._ttl
        return entry["prompt"]

    def set(self, model: str, session_id: str, prompt: str):
        """冻结 prompt，覆盖该 model 的任何旧条目"""
        self._cache[model] = {
            "session_id": session_id,
            "prompt": prompt,
            "expires_at": time.time() + self._ttl,
        }

    def clear(self, session_id: str):
        """手动清除（例如 session 删除时），遍历清除匹配的条目"""
        to_delete = [m for m, e in self._cache.items() if e["session_id"] == session_id]
        for m in to_delete:
            del self._cache[m]
