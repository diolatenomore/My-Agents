"""Session 的 SQLite 持久化存储"""

import json
from datetime import datetime
from typing import Optional

from src.db.sqlite_pool import db_pool
from src.session.models import Session


class SessionStore:
    """Session 数据库操作"""

    # ========== Session CRUD ==========

    @classmethod
    async def get_session(cls, session_id: str) -> Optional[Session]:
        async with db_pool.get_conn() as conn:
            row = await (await conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            )).fetchone()
            if not row:
                return None
            return Session(
                session_id=row["session_id"],
                title=row["title"] or "",
                context_tokens=row["context_tokens"] if "context_tokens" in row.keys() else 0,
                project_id=row["project_id"] if "project_id" in row.keys() else None,
                created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
                updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.now(),
            )

    @classmethod
    async def create_session(cls, session_id: str, title: str = "", project_id: Optional[str] = None) -> Session:
        now = datetime.now().isoformat()
        async with db_pool.get_conn() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO sessions (session_id, title, project_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, title, project_id, now, now),
            )
        return Session(session_id=session_id, title=title, project_id=project_id)

    @classmethod
    async def update_title(cls, session_id: str, title: str):
        async with db_pool.get_conn() as conn:
            await conn.execute(
                "UPDATE sessions SET title = ?, updated_at = datetime('now') WHERE session_id = ?",
                (title, session_id),
            )

    @classmethod
    async def delete_session(cls, session_id: str):
        async with db_pool.get_conn() as conn:
            await conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
            await conn.execute("DELETE FROM context_messages WHERE session_id = ?", (session_id,))
            await conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    @classmethod
    async def list_sessions(cls, limit: int = 50, offset: int = 0) -> list[Session]:
        """列出最近会话，按 updated_at 倒序"""
        async with db_pool.get_conn() as conn:
            rows = await (await conn.execute(
                """SELECT s.*, (SELECT COUNT(*) FROM session_messages m WHERE m.session_id = s.session_id) as msg_count
                    FROM sessions s
                    ORDER BY s.updated_at DESC
                    LIMIT ? OFFSET ?""",
                (limit, offset),
            )).fetchall()
            return [
                Session(
                    session_id=row["session_id"],
                    title=row["title"] or "",
                    context_tokens=row["context_tokens"] if "context_tokens" in row.keys() else 0,
                    project_id=row["project_id"] if "project_id" in row.keys() else None,
                    created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
                    updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.now(),
                    message_count=row["msg_count"],
                )
                for row in rows
            ]

    # ========== Display Messages CRUD ==========

    @classmethod
    async def append_display_messages(cls, session_id: str, msg_dicts: list[dict]):
        """批量追加消息（自动创建 session 行）"""
        async with db_pool.get_conn() as conn:
            await conn.execute(
                """INSERT INTO sessions (session_id, updated_at) VALUES (?, datetime('now'))
                    ON CONFLICT(session_id) DO UPDATE SET updated_at = datetime('now')""",
                (session_id,),
            )
            for d in msg_dicts:
                await conn.execute(
                    "INSERT INTO session_messages (session_id, role, content) VALUES (?, ?, ?)",
                    (session_id, d["role"], json.dumps(d, ensure_ascii=False)),
                )

    @classmethod
    async def count_display_messages(cls, session_id: str) -> int:
        """获取会话的消息总数"""
        async with db_pool.get_conn() as conn:
            row = await (await conn.execute(
                "SELECT COUNT(*) as cnt FROM session_messages WHERE session_id = ?",
                (session_id,),
            )).fetchone()
            return row["cnt"] if row else 0

    @classmethod
    async def get_display_messages(cls, session_id: str, limit: int = 200) -> list[dict]:
        """获取会话的消息列表（按时间正序）"""
        async with db_pool.get_conn() as conn:
            rows = await (await conn.execute(
                "SELECT content FROM session_messages WHERE session_id = ? ORDER BY id ASC LIMIT ?",
                (session_id, limit),
            )).fetchall()
            return [json.loads(row["content"]) for row in rows]

    @classmethod
    async def update_context_tokens(cls, session_id: str, tokens: int):
        """更新会话的上次上下文 token 数"""
        async with db_pool.get_conn() as conn:
            await conn.execute(
                "UPDATE sessions SET context_tokens = ?, updated_at = datetime('now') WHERE session_id = ?",
                (tokens, session_id),
            )

    # ========== 上下文消息（context_messages）CRUD ==========

    @classmethod
    async def append_context_messages(cls, session_id: str, msg_dicts: list[dict]):
        """追加消息到 context_messages 表

        自动跳过 system 消息（system prompt 不持久化）。
        """
        # system 消息总是在第一位，跳过
        if msg_dicts and msg_dicts[0].get("role") == "system":
            msg_dicts = msg_dicts[1:]
        if not msg_dicts:
            return
        async with db_pool.get_conn() as conn:
            await conn.execute(
                """INSERT INTO sessions (session_id, updated_at) VALUES (?, datetime('now'))
                    ON CONFLICT(session_id) DO UPDATE SET updated_at = datetime('now')""",
                (session_id,),
            )
            for d in msg_dicts:
                await conn.execute(
                    "INSERT INTO context_messages (session_id, role, content) VALUES (?, ?, ?)",
                    (session_id, d["role"], json.dumps(d, ensure_ascii=False)),
                )

    @classmethod
    async def load_context_messages(cls, session_id: str) -> list[dict]:
        """加载全部上下文消息（按 id 排序）"""
        async with db_pool.get_conn() as conn:
            rows = await (await conn.execute(
                "SELECT content FROM context_messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            )).fetchall()
            return [json.loads(row["content"]) for row in rows]

    @classmethod
    async def get_context_message_count(cls, session_id: str) -> int:
        """获取上下文消息总数"""
        async with db_pool.get_conn() as conn:
            row = await (await conn.execute(
                "SELECT COUNT(*) as cnt FROM context_messages WHERE session_id = ?",
                (session_id,),
            )).fetchone()
            return row["cnt"] if row else 0

    @classmethod
    async def delete_all_context_messages(cls, session_id: str):
        """删除某会话的全部上下文消息"""
        async with db_pool.get_conn() as conn:
            await conn.execute(
                "DELETE FROM context_messages WHERE session_id = ?",
                (session_id,),
            )

    @classmethod
    async def overwrite_context_messages(cls, session_id: str, msg_dicts: list[dict]):
        """全量覆盖上下文消息（压缩后使用）"""
        await cls.delete_all_context_messages(session_id)
        await cls.append_context_messages(session_id, msg_dicts)
