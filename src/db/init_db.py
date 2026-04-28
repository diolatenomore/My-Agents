from src.db.sqlite_pool import db_pool
from src.utils.common import logger


def init_db():
    with db_pool.get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                priority INTEGER NOT NULL,
                query TEXT NOT NULL,
                task_type TEXT NOT NULL,
                status INTEGER NOT NULL,
                is_resume INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_results (
                task_id TEXT PRIMARY KEY,
                result TEXT NULL,
                error TEXT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS copy_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                source_path TEXT NOT NULL,
                target_path TEXT NOT NULL,
                is_copied INTEGER NOT NULL DEFAULT 0,
                is_dir INTEGER NOT NULL DEFAULT 0,
                staging_path TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_copy_records_task_id ON copy_records(task_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_copy_records_source_path ON copy_records(source_path)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_copy_records_target_path ON copy_records(target_path)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS staging_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                path TEXT NOT NULL,
                staging_path TEXT,
                is_dir INTEGER NOT NULL DEFAULT 0,
                deleted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_staging_records_task_id ON staging_records(task_id)")


        conn.execute("""
            CREATE TABLE IF NOT EXISTS diff_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                source_path TEXT,
                target_path TEXT,
                step INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_diff_records_task_id ON diff_records(task_id)")

        conn.commit()

    logger.info("数据库所有表初始化完成")
