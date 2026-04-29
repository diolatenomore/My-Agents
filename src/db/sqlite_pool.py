import sqlite3
import os
import queue
import threading
from contextlib import contextmanager

from src.config import DB_PATH, MAX_CONNECTIONS
from src.utils.common import logger


class SqlitePool:
    def __init__(self):
        self.db_path = DB_PATH
        self.max_connections = MAX_CONNECTIONS
        self._pool = queue.Queue(maxsize=MAX_CONNECTIONS)
        self._lock = threading.Lock()
        self._created = 0
        self._closed = False

        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def acquire(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("连接池已关闭，无法获取连接")

        try:
            conn = self._pool.get_nowait()
            return conn
        except queue.Empty:
            pass

        with self._lock:
            if self._created < self.max_connections:
                conn = self._create_connection()
                self._created += 1
                return conn

        conn = self._pool.get()
        return conn

    def release(self, conn: sqlite3.Connection):
        if self._closed:
            conn.close()
            return
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            conn.close()

    @contextmanager
    def get_conn(self):
        """强制事务上下文，自动 BEGIN/COMMIT/ROLLBACK"""
        conn = self.acquire()
        conn.execute("BEGIN")
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"操作数据库异常：{e}")
        finally:
            self.release(conn)

    def close_all(self):
        self._closed = True
        while True:
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except queue.Empty:
                break
        self._created = 0


db_pool = SqlitePool()
