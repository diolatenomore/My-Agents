from src.db.sqlite_pool import db_pool
from src.utils.common import logger


async def init_db():
    async with db_pool.get_conn() as conn:
        await conn.execute("""
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

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS task_results (
                task_id TEXT PRIMARY KEY,
                result TEXT NULL,
                error TEXT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        await conn.execute("""
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
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_copy_records_task_id ON copy_records(task_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_copy_records_source_path ON copy_records(source_path)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_copy_records_target_path ON copy_records(target_path)")

        await conn.execute("""
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
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_staging_records_task_id ON staging_records(task_id)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS diff_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                source_path TEXT,
                target_path TEXT,
                step INTEGER NOT NULL DEFAULT 0,
                is_reviewed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_diff_records_task_id ON diff_records(task_id)")
        # 兼容旧表：如果 is_reviewed 列不存在则添加
        try:
            await conn.execute("ALTER TABLE diff_records ADD COLUMN is_reviewed INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass  # 列已存在则跳过

        # VFS 审批表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS review_items (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                parent_id TEXT,
                op_type TEXT NOT NULL,
                source TEXT,
                target TEXT,
                copy_source TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_review_items_task_id ON review_items(task_id)")

        # Session 管理表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT DEFAULT '',
                context_tokens INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        # 迁移：为已有 sessions 表增加 context_tokens 列
        try:
            await conn.execute("ALTER TABLE sessions ADD COLUMN context_tokens INTEGER DEFAULT 0")
        except Exception:
            pass  # 列已存在则跳过
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS session_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_session_messages_sid ON session_messages(session_id)")

        # 模型配置表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS model_configs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                model TEXT NOT NULL,
                env_var_name TEXT NOT NULL UNIQUE,
                is_active INTEGER NOT NULL DEFAULT 1,
                max_context_tokens INTEGER NOT NULL DEFAULT 200000,
                max_output_tokens INTEGER NOT NULL DEFAULT 64000,
                max_tool_calls INTEGER NOT NULL DEFAULT 50,
                temperature REAL NOT NULL DEFAULT 0.7,
                max_iterations INTEGER NOT NULL DEFAULT 30,
                think INTEGER NOT NULL DEFAULT 1,
                reasoning_effort TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # 迁移：Agent 运行时配置字段（v2）
        for col_sql in [
            "ALTER TABLE model_configs ADD COLUMN temperature REAL NOT NULL DEFAULT 0.7",
            "ALTER TABLE model_configs ADD COLUMN max_iterations INTEGER NOT NULL DEFAULT 30",
            "ALTER TABLE model_configs ADD COLUMN think INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE model_configs ADD COLUMN reasoning_effort TEXT",
        ]:
            try:
                await conn.execute(col_sql)
            except Exception:
                pass  # 列已存在

    logger.info("数据库所有表初始化完成")
