from datetime import datetime
from typing import Optional, List, Dict, Any

from src.db.sqlite_pool import db_pool
from src.models.task import Task, TaskStatus, Priority, TaskType
from src.utils.common import logger


class TaskRepository:
    def _task_to_row(self, task: Task) -> Dict[str, Any]:
        return {
            "task_id": task.task_id,
            "priority": task.priority.value,
            "query": task.query,
            "task_type": task.task_type.value,
            "status": task.status.value,
            "is_resume": 1 if task.is_resume else 0,
            "created_at": task.created_at.isoformat(),
        }

    @staticmethod
    def _row_to_task(row) -> Task:
        return Task(
            task_id=row["task_id"],
            priority=Priority(row["priority"]),
            query=row["query"],
            task_type=TaskType(row["task_type"]),
            status=TaskStatus(row["status"]),
            is_resume=bool(row["is_resume"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    async def save_task(self, task: Task):
        async with db_pool.get_conn() as conn:
            row = self._task_to_row(task)
            await conn.execute("""
                INSERT INTO tasks (task_id, priority, query, task_type, status, is_resume, created_at)
                VALUES (:task_id, :priority, :query, :task_type, :status, :is_resume, :created_at)
                ON CONFLICT(task_id) DO UPDATE SET
                    priority = excluded.priority,
                    status = excluded.status,
                    is_resume = excluded.is_resume,
                    updated_at = datetime('now')
            """, row)
        logger.debug(f"[TaskRepository] 任务 {task.task_id} 已保存到数据库")

    async def update_status(self, task_id: str, status: TaskStatus):
        async with db_pool.get_conn() as conn:
            await conn.execute("""
                UPDATE tasks SET status = ?, updated_at = datetime('now')
                WHERE task_id = ?
            """, (status.value, task_id))
        logger.debug(f"[TaskRepository] 任务 {task_id} 状态已更新为 {status.name}")

    async def update_priority(self, task_id: str, priority: Priority):
        async with db_pool.get_conn() as conn:
            await conn.execute("""
                UPDATE tasks SET priority = ?, updated_at = datetime('now')
                WHERE task_id = ?
            """, (priority.value, task_id))
        logger.debug(f"[TaskRepository] 任务 {task_id} 优先级已更新为 {priority.name}")

    async def update_is_resume(self, task_id: str, is_resume: bool):
        async with db_pool.get_conn() as conn:
            await conn.execute("""
                UPDATE tasks SET is_resume = ?, updated_at = datetime('now')
                WHERE task_id = ?
            """, (is_resume, task_id))
        logger.debug(f"[TaskRepository] 任务 {task_id} 的is_resume 已设置为 {is_resume}")

    async def get_task_status(self, task_id: str):
        async with db_pool.get_conn() as conn:
            cursor = await conn.execute("SELECT status FROM tasks WHERE task_id = ?", (task_id,))
            row = await cursor.fetchone()
        if row is None:
            return None
        return TaskStatus(row["status"])

    async def get_tasks_by_status(self, status: TaskStatus) -> List[Task]:
        async with db_pool.get_conn() as conn:
            cursor = await conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY priority ASC, created_at ASC",
                (status.value,)
            )
            rows = await cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    async def set_result(self, task_id: str, result: str, status: TaskStatus):
        if not (status == TaskStatus.COMPLETED or status == TaskStatus.ERROR):
            logger.error("status参数错误")
            return
        async with db_pool.get_conn() as conn:
            await conn.execute("""
                UPDATE tasks SET status = ?, updated_at = datetime('now')
                WHERE task_id = ?
            """, (status.value, task_id))
            if status == TaskStatus.ERROR:
                await conn.execute("""
                    UPDATE task_results SET error = ?,updated_at = datetime('now')
                    WHERE task_id = ?
                """, (result, task_id))
            else:
                await conn.execute("""
                    UPDATE task_results SET result = ?,updated_at = datetime('now')
                    WHERE task_id = ?
                """, (result, task_id))
        logger.debug(f"[TaskRepository] 任务 {task_id} 的结果已保存，状态: {status.name}")

    async def get_result(self, task_id: str) -> Optional[str]:
        async with db_pool.get_conn() as conn:
            cursor = await conn.execute("SELECT result, error FROM task_results WHERE task_id = ?", (task_id,))
            row = await cursor.fetchone()
        if row is None:
            return None
        elif row["result"] is None or row["error"] is None:
            return None
        return row["result"] if row["result"] is not None else row["error"]

    async def delete_task(self, task_id: str):
        async with db_pool.get_conn() as conn:
            await conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            await conn.execute("DELETE FROM task_results WHERE task_id = ?", (task_id,))
        logger.debug(f"[TaskRepository] 任务 {task_id} 已从数据库删除")

    async def restore_pending_tasks(self) -> List[Task]:
        return await self.get_tasks_by_status(TaskStatus.PENDING)

    async def restore_paused_tasks(self) -> List[Task]:
        return await self.get_tasks_by_status(TaskStatus.PAUSED)
