import sqlite3
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

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        return Task(
            task_id=row["task_id"],
            priority=Priority(row["priority"]),
            query=row["query"],
            task_type=TaskType(row["task_type"]),
            status=TaskStatus(row["status"]),
            is_resume=bool(row["is_resume"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def save_task(self, task: Task):
        with db_pool.get_conn() as conn:
            row = self._task_to_row(task)
            conn.execute("""
                INSERT INTO tasks (task_id, priority, query, task_type, status, is_resume, created_at)
                VALUES (:task_id, :priority, :query, :task_type, :status, :is_resume, :created_at)
                ON CONFLICT(task_id) DO UPDATE SET
                    priority = excluded.priority,
                    status = excluded.status,
                    is_resume = excluded.is_resume,
                    updated_at = datetime('now')
            """, row)
            conn.commit()
        logger.debug(f"[TaskRepository] 任务 {task.task_id} 已保存到数据库")

    def update_status(self, task_id: str, status: TaskStatus):
        with db_pool.get_conn() as conn:
            conn.execute("""
                UPDATE tasks SET status = ?, updated_at = datetime('now')
                WHERE task_id = ?
            """, (status.value, task_id))
            conn.commit()
        logger.debug(f"[TaskRepository] 任务 {task_id} 状态已更新为 {status.name}")

    def update_priority(self, task_id: str, priority: Priority):
        with db_pool.get_conn() as conn:
            conn.execute("""
                UPDATE tasks SET priority = ?, updated_at = datetime('now')
                WHERE task_id = ?
            """, (priority.value, task_id))
            conn.commit()
        logger.debug(f"[TaskRepository] 任务 {task_id} 优先级已更新为 {priority.name}")

    def update_is_resume(self, task_id: str, is_resume: bool):
        with db_pool.get_conn() as conn:
            conn.execute("""
                UPDATE tasks SET is_resume = ?, updated_at = datetime('now')
                WHERE task_id = ?
            """, (is_resume, task_id))
            conn.commit()
        logger.debug(f"[TaskRepository] 任务 {task_id} 的is_resume 已设置为 {is_resume}")

    def get_task_status(self, task_id: str):
        with db_pool.get_conn() as conn:
            cursor = conn.execute("SELECT status FROM tasks WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
        if row is None:
            return None
        return TaskStatus(row["status"])

    def get_tasks_by_status(self, status: TaskStatus) -> List[Task]:
        with db_pool.get_conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY priority ASC, created_at ASC",
                (status.value,)
            )
            return [self._row_to_task(row) for row in cursor.fetchall()]

    def set_result(self, task_id: str, result: str, status: TaskStatus):
        if not (status == TaskStatus.COMPLETED or status == TaskStatus.ERROR):
            logger.error("status参数错误")
            return
        with db_pool.get_conn() as conn:
            conn.execute("""
                UPDATE tasks SET status = ?, updated_at = datetime('now')
                WHERE task_id = ?
            """, (status.value, task_id))
            if status == TaskStatus.ERROR:
                conn.execute("""
                    UPDATE task_results SET error = ?,updated_at = datetime('now')
                    WHERE task_id = ?
                """, (result, task_id))
            else:
                conn.execute("""
                    UPDATE task_results SET result = ?,updated_at = datetime('now')
                    WHERE task_id = ?
                """, (result, task_id))
            conn.commit()
        logger.debug(f"[TaskRepository] 任务 {task_id} 的结果已保存，状态: {status.name}")

    def get_result(self, task_id: str) -> Optional[str]:
        with db_pool.get_conn() as conn:
            cursor = conn.execute("SELECT result, error FROM task_results WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
        if row is None:
            return None
        elif row["result"] is None or row["error"] is None:
            return None
        return row["result"] if row["result"] is not None else row["error"]

    def delete_task(self, task_id: str):
        with db_pool.get_conn() as conn:
            conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM task_results WHERE task_id = ?", (task_id,))
            conn.commit()
        logger.debug(f"[TaskRepository] 任务 {task_id} 已从数据库删除")

    def restore_pending_tasks(self) -> List[Task]:
        return self.get_tasks_by_status(TaskStatus.PENDING)

    def restore_paused_tasks(self) -> List[Task]:
        return self.get_tasks_by_status(TaskStatus.PAUSED)

