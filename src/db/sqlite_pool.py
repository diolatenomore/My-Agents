"""异步 SQLite 连接池，基于 aiosqlite"""

import asyncio
import os
import sqlite3

import aiosqlite
from contextlib import asynccontextmanager

from src.config import DB_PATH, MAX_CONNECTIONS, CONNECT_TIMEOUT
from src.utils.common import logger


class AsyncSqlitePool:
    """异步 SQLite 连接池（WAL 模式，支持并发读）"""

    def __init__(self):
        self.db_path = DB_PATH
        self._pool: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue(maxsize=MAX_CONNECTIONS)
        self._created = 0
        self._closed = False
        self._lock = asyncio.Lock()

        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    async def _create_connection(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    async def _acquire(self) -> aiosqlite.Connection:
        if self._closed:
            raise RuntimeError("连接池已关闭，无法获取连接")

        try:
            conn = self._pool.get_nowait()
            return conn
        except asyncio.QueueEmpty:
            pass

        async with self._lock:
            if self._created < MAX_CONNECTIONS:
                conn = await self._create_connection()
                self._created += 1
                return conn

        try:
            conn = await asyncio.wait_for(
                self._pool.get(),
                timeout=CONNECT_TIMEOUT,
            )
            return conn
        except asyncio.TimeoutError:
            if self._closed:
                raise RuntimeError("连接池已关闭，无法获取连接")
            raise RuntimeError("获取数据库连接超时")

    async def _release(self, conn: aiosqlite.Connection):
        if self._closed:
            await conn.close()
            return
        try:
            self._pool.put_nowait(conn)
        except asyncio.QueueFull:
            await conn.close()

    @asynccontextmanager
    async def get_conn(self):
        """强制事务上下文，自动 BEGIN/COMMIT/ROLLBACK"""
        conn = await self._acquire()
        await conn.execute("BEGIN")
        try:
            yield conn
            await conn.commit()
        except Exception as e:
            await conn.rollback()
            logger.error(f"操作数据库异常：{e}")
        finally:
            await self._release(conn)

    async def close_all(self):
        self._closed = True
        async with self._lock:
            while self._created > 0:
                conn = await self._pool.get()
                await conn.close()
                self._created -= 1


db_pool = AsyncSqlitePool()
