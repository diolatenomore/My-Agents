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
                created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
                updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.now(),
            )

    @classmethod
    async def create_session(cls, session_id: str, title: str = "") -> Session:
        now = datetime.now().isoformat()
        async with db_pool.get_conn() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO sessions (session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, title, now, now),
            )
        return Session(session_id=session_id, title=title)

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
                    created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
                    updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.now(),
                    message_count=row["msg_count"],
                )
                for row in rows
            ]

    # ========== Messages CRUD ==========

    @classmethod
    async def append_messages(cls, session_id: str, msg_dicts: list[dict]):
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
    async def count_messages(cls, session_id: str) -> int:
        """获取会话的消息总数"""
        async with db_pool.get_conn() as conn:
            row = await (await conn.execute(
                "SELECT COUNT(*) as cnt FROM session_messages WHERE session_id = ?",
                (session_id,),
            )).fetchone()
            return row["cnt"] if row else 0

    @classmethod
    async def get_messages(cls, session_id: str, limit: int = 200) -> list[dict]:
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

    @classmethod
    async def get_last_n_messages(cls, session_id: str, n: int = 50) -> list[dict]:
        """获取最近 n 条消息（按时间正序）"""
        async with db_pool.get_conn() as conn:
            rows = await (await conn.execute(
                """SELECT content FROM (
                        SELECT id, content FROM session_messages
                        WHERE session_id = ? ORDER BY id DESC LIMIT ?
                    ) sub ORDER BY id ASC""",
                (session_id, n),
            )).fetchall()
            return [json.loads(row["content"]) for row in rows]
