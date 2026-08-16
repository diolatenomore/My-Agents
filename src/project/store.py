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
    async def update_project(cls, project_id: str, name: str):
        """更新项目名称（工作目录创建后不可修改）"""
        async with db_pool.get_conn() as conn:
            await conn.execute("UPDATE projects SET name = ?, updated_at = datetime('now') WHERE project_id = ?",
                               (name, project_id))

    @classmethod
    async def delete_project_with_sessions(cls, project_id: str) -> list[str]:
        """单个事务内删除项目及其全部归属会话（含会话消息、上下文消息、VFS 数据库记录）。

        返回被删除的会话 ID 列表，供调用方清理非数据库资源（system prompt 缓存、暂存区磁盘文件）。
        """
        async with db_pool.get_conn() as conn:  # get_conn 整体处于一个 BEGIN/COMMIT 事务中
            rows = await (await conn.execute(
                "SELECT session_id FROM sessions WHERE project_id = ?", (project_id,),
            )).fetchall()
            # 以子查询圈定归属会话，逐表删除其关联数据（VFS 各表以 task_id 关联会话）
            for table, key in [
                ("staging_records", "task_id"),
                ("copy_records", "task_id"),
                ("diff_records", "task_id"),
                ("review_items", "task_id"),
                ("session_messages", "session_id"),
                ("context_messages", "session_id"),
            ]:
                await conn.execute(
                    f"DELETE FROM {table} WHERE {key} IN (SELECT session_id FROM sessions WHERE project_id = ?)",
                    (project_id,),
                )
            await conn.execute("DELETE FROM sessions WHERE project_id = ?", (project_id,))
            await conn.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))
            return [row["session_id"] for row in rows]

    @classmethod
    async def list_projects(cls) -> list[Project]:
        """列出所有项目，按创建时间倒序（带会话数统计）"""
        async with db_pool.get_conn() as conn:
            rows = await (await conn.execute(
                """SELECT p.*, (SELECT COUNT(*) FROM sessions s WHERE s.project_id = p.project_id) as session_count
                    FROM projects p ORDER BY p.created_at DESC""",
            )).fetchall()
            return [_row_to_project(row) for row in rows]
