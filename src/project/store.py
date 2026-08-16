"""Project 的 SQLite 持久化存储"""

from datetime import datetime
from typing import Optional

from src.db.sqlite_pool import db_pool
from src.project.models import Project


def _row_to_project(row) -> Project:
    return Project(
        project_id=row["project_id"],
        name=row["name"] or "",
        work_dir=row["work_dir"] or "",
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.now(),
        session_count=row["session_count"] if "session_count" in row.keys() else 0,
    )


class ProjectStore:
    """Project 数据库操作"""

    @classmethod
    async def get_project(cls, project_id: str) -> Optional[Project]:
        async with db_pool.get_conn() as conn:
            row = await (await conn.execute(
                """SELECT p.*, (SELECT COUNT(*) FROM sessions s WHERE s.project_id = p.project_id) as session_count
                    FROM projects p WHERE p.project_id = ?""",
                (project_id,),
            )).fetchone()
            return _row_to_project(row) if row else None

    @classmethod
    async def create_project(cls, project_id: str, name: str, work_dir: str) -> Project:
        now = datetime.now().isoformat()
        async with db_pool.get_conn() as conn:
            await conn.execute(
                "INSERT INTO projects (project_id, name, work_dir, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (project_id, name, work_dir, now, now),
            )
        return Project(project_id=project_id, name=name, work_dir=work_dir)

    @classmethod
    async def update_project(cls, project_id: str, name: Optional[str] = None, work_dir: Optional[str] = None):
        async with db_pool.get_conn() as conn:
            if name is not None:
                await conn.execute("UPDATE projects SET name = ?, updated_at = datetime('now') WHERE project_id = ?",
                                   (name, project_id))
            if work_dir is not None:
                await conn.execute("UPDATE projects SET work_dir = ?, updated_at = datetime('now') WHERE project_id = ?",
                                   (work_dir, project_id))

    @classmethod
    async def delete_project(cls, project_id: str):
        """删除项目，归属它的会话 project_id 置空（会话保留为普通聊天）"""
        async with db_pool.get_conn() as conn:
            await conn.execute("UPDATE sessions SET project_id = NULL WHERE project_id = ?", (project_id,))
            await conn.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))

    @classmethod
    async def list_projects(cls) -> list[Project]:
        """列出所有项目，按创建时间倒序（带会话数统计）"""
        async with db_pool.get_conn() as conn:
            rows = await (await conn.execute(
                """SELECT p.*, (SELECT COUNT(*) FROM sessions s WHERE s.project_id = p.project_id) as session_count
                    FROM projects p ORDER BY p.created_at DESC""",
            )).fetchall()
            return [_row_to_project(row) for row in rows]
