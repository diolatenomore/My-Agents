import hashlib
import os
from dataclasses import dataclass
from typing import Optional

import aiosqlite

from src.config import STAGING_AREA_PATH
from src.db.sqlite_pool import db_pool
from src.utils.common import logger

@dataclass
class StagingRecord:
    """暂存区记录"""
    task_id: str  # 任务id
    path: str  # 文件路径（source_path/target_path）
    staging_path: str | None = None  # 暂存区路径
    is_dir: bool = False  # 是目录——不在暂存区真正创建，只作为占位
    deleted: bool = False  # 标记是否被删除
    # deleted的作用是，原文件source_path被删除在文件系统中还存在，同时暂存区里也没有它的路径。
    # 假如此时想在source_path创建文件，由于原文件在文件系统中还存在，会发生命名冲突(实际上不应该发生)
    # 所以删除文件把deleted设置为True，表示文件已被删除，就再不会到文件系统中判断命名冲突。

class StagingArea:
    """控制暂存区路径的分发（实例化，每个 task 独立一份）"""

    def __init__(self, task_id: str):
        self.task_id: str = task_id
        self.mapping: dict[str, str] = {}  # 所有文件/目录路径到暂存区路径的映射
        self.deleted_mapping: dict[str, bool] = {}  # 标记文件是否在暂存区被删除
        self.deleted_dir_mapping: dict[str, bool] = {}  # 标记目录是否在暂存区被删除

    def get_staging_path(self, path: str) -> str | None:
        """获取暂存区路径，如果已被删除或不存在则返回 None"""
        if not self.deleted_mapping.get(path, False) and path in self.mapping:
            return self.mapping[path]
        return None

    def get_staging_dir_path(self, path: str) -> str | None:
        """
        获取暂存区目录路径，如果已被删除或不存在则返回None
        """
        if not self.deleted_dir_mapping.get(path, False) and path in self.mapping:
            # 如果path是目录，就返回目录路径
            return self.mapping[path]
        return None

    async def register(self, path: str, _conn: aiosqlite.Connection) -> str:
        """
        分配一条暂存区路径
        """
        # 将path转换为哈希值并保留扩展名，作为暂存区路径的文件名，避免因为path中包含"/"而导致创建目录
        path_hash = hashlib.md5(path.encode()).hexdigest()
        _, ext = os.path.splitext(path)
        staging_path = f"{STAGING_AREA_PATH}/{self.task_id}/{path_hash}{ext}"

        # 更新缓存
        self.mapping[path] = staging_path
        # 更新删除状态缓存
        self.deleted_mapping[path] = False

        # 写入数据库
        try:
            cursor = await _conn.execute(
                "SELECT id FROM staging_records WHERE task_id = ? AND path = ?",
                (self.task_id, path),
            )
            existing = await cursor.fetchone()
            if existing:
                # 更新现有记录
                await _conn.execute(
                    "UPDATE staging_records SET staging_path = ?, deleted = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (staging_path, False, existing["id"]),
                )
            else:
                # 插入新记录
                await _conn.execute(
                    "INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted) VALUES (?, ?, ?, ?, ?)",
                    (self.task_id, path, staging_path, False, False),
                )
        except Exception as e:
            logger.error(f"写入暂存区记录失败: {e}")

        logger.debug(f"为文件{path}分配暂存区路径: {staging_path}")
        return staging_path

    async def register_dir(self, path: str, _conn: aiosqlite.Connection) -> str:
        """
        分配一条目录暂存区路径
        """
        staging_path = " "  # 不实际创建目录，作为占位符

        self.mapping[path] = staging_path
        self.deleted_dir_mapping[path] = False

        # 写入数据库
        try:
            cursor = await _conn.execute(
                "SELECT id FROM staging_records WHERE task_id = ? AND path = ?",
                (self.task_id, path),
            )
            existing = await cursor.fetchone()
            if existing:
                await _conn.execute(
                    "UPDATE staging_records SET staging_path = ?, is_dir = ?, deleted = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (staging_path, True, False, existing["id"]),
                )
            else:
                await _conn.execute(
                    "INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted) VALUES (?, ?, ?, ?, ?)",
                    (self.task_id, path, staging_path, True, False),
                )
        except Exception as e:
            logger.error(f"写入暂存区目录记录失败: {e}")

        logger.debug(f"为目录{path}分配暂存区路径: {staging_path}")
        return staging_path

    async def delete(self, path: str, _conn: aiosqlite.Connection) -> None:
        """
        删除暂存区路径（设置deleted为True）
        """
        self.deleted_mapping[path] = True

        # 更新数据库
        try:
            cursor = await _conn.execute(
                "SELECT id FROM staging_records WHERE task_id = ? AND path = ?",
                (self.task_id, path),
            )
            existing = await cursor.fetchone()
            if existing:
                await _conn.execute(
                    "UPDATE staging_records SET deleted = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (True, existing["id"]),
                )
            else:
                await _conn.execute(
                    "INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted) VALUES (?, ?, ?, ?, ?)",
                    (self.task_id, path, None, False, True),
                )
        except Exception as e:
            logger.error(f"更新暂存区删除状态失败: {e}")

        logger.debug(f"在暂存区删除文件{path}")

    def is_deleted(self, path: str) -> bool:
        """判断path是否在暂存区内删除（真实路径可能还存在）"""
        return self.deleted_mapping.get(path, False)

    async def delete_dir(self, path: str, _conn: aiosqlite.Connection):
        """
        删除目录暂存区路径（设置deleted为True）
        """
        # 如果path在暂存区中，就删除暂存区中的目录
        staging_path = self.get_staging_dir_path(path)
        if staging_path:
            self.mapping.pop(path, None)

        # 更新缓存中的删除状态
        self.deleted_dir_mapping[path] = True

        # 遍历mapping，将该目录下所有文件标记为已删除
        for file_path in list(self.mapping.keys()):
            if file_path.startswith(path + "/"):
                self.deleted_mapping[file_path] = True

        # 遍历deleted_dir_mapping，更新子目录的删除状态
        for dir_path in list(self.deleted_dir_mapping.keys()):
            if dir_path.startswith(path + "/"):
                self.mapping.pop(dir_path, None)  # 不存在也不报错
                self.deleted_dir_mapping[dir_path] = True

        try:
            # 处理主目录
            cursor = await _conn.execute(
                "SELECT id FROM staging_records WHERE task_id = ? AND path = ?",
                (self.task_id, path),
            )
            existing = await cursor.fetchone()
            if existing:
                await _conn.execute(
                    "UPDATE staging_records SET deleted = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (True, existing["id"]),
                )
            else:
                await _conn.execute(
                    "INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted) VALUES (?, ?, ?, ?, ?)",
                    (self.task_id, path, None, True, True),
                )

            # 处理子目录
            cursor = await _conn.execute(
                "SELECT id FROM staging_records WHERE task_id = ? AND path LIKE ? AND is_dir = 1",
                (self.task_id, path + "/%"),
            )
            for row in await cursor.fetchall():
                await _conn.execute(
                    "UPDATE staging_records SET deleted = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (True, row["id"]),
                )
        except Exception as e:
            logger.error(f"更新暂存区目录删除状态失败: {e}")

        logger.debug(f"在暂存区删除目录{path}")

    def is_deleted_dir(self, path: str) -> bool:
        """判断path是否在暂存区内删除（真实路径可能还存在）"""
        return self.deleted_dir_mapping.get(path, False)

    async def rename(self, old_path: str, new_path: str, _conn: aiosqlite.Connection) -> None:
        """
        重命名暂存区路径
        """
        # 更新缓存中的路径映射关系
        self.mapping[new_path] = self.mapping[old_path]
        self.mapping.pop(old_path, None)

        # 更新删除状态缓存
        self.deleted_mapping[new_path] = self.deleted_mapping[old_path]
        # 标记原路径为已删除
        self.deleted_mapping[old_path] = True

        # 更新数据库
        try:
            # 检查旧路径是否存在
            cursor = await _conn.execute(
                "SELECT id FROM staging_records WHERE task_id = ? AND path = ?",
                (self.task_id, old_path),
            )
            existing = await cursor.fetchone()
            if existing:
                # 更新旧路径记录为已删除
                await _conn.execute(
                    "UPDATE staging_records SET deleted = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (True, existing["id"]),
                )
            else:
                # 插入旧路径删除记录
                await _conn.execute(
                    "INSERT INTO staging_records (task_id, path, is_dir, deleted) VALUES (?, ?, ?, ?)",
                    (self.task_id, old_path, False, True),
                )

            # 插入新路径记录
            await _conn.execute(
                "INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted) VALUES (?, ?, ?, ?, ?)",
                (self.task_id, new_path, self.mapping[new_path], False, False),
            )
        except Exception as e:
            logger.error(f"更新暂存区重命名状态失败: {e}")

        logger.debug(f"在暂存区重命名文件{old_path}为{new_path}")

    async def rename_dir(self, old_dir_path: str, new_dir_path: str, _conn: aiosqlite.Connection) -> None:
        """
        重命名目录暂存区路径
        """
        # 1、更新目录缓存
        # 更新缓存中的路径映射关系
        self.mapping[new_dir_path] = self.mapping[old_dir_path]
        self.mapping.pop(old_dir_path, None)
        # 更新删除状态缓存
        self.deleted_dir_mapping[new_dir_path] = self.deleted_dir_mapping[old_dir_path]
        # 标记原目录被删除
        self.deleted_dir_mapping[old_dir_path] = True

        # 2、更新子目录缓存
        # 遍历所有已注册的路径，更新子文件/子目录的路径
        for old_path in list(self.mapping.keys()):
            if old_path.startswith(old_dir_path + "/"):
                # 替换前缀
                new_sub_path = new_dir_path + old_path[len(old_dir_path):]
                self.mapping[new_sub_path] = self.mapping[old_path]
                self.mapping.pop(old_path, None)

                # 更新删除状态映射
                if old_path in self.deleted_mapping:
                    self.deleted_mapping[new_sub_path] = self.deleted_mapping[old_path]
                    self.deleted_mapping[old_path] = True
                elif old_path in self.deleted_dir_mapping:
                    self.deleted_dir_mapping[new_sub_path] = self.deleted_dir_mapping[old_path]
                    self.deleted_dir_mapping[old_path] = True

        # 更新数据库
        try:
            # 处理主目录
            # 检查旧目录记录是否存在
            cursor = await _conn.execute(
                "SELECT id FROM staging_records WHERE task_id = ? AND path = ?",
                (self.task_id, old_dir_path),
            )
            existing = await cursor.fetchone()
            if existing:
                await _conn.execute(
                    "UPDATE staging_records SET deleted = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (True, existing["id"]),
                )
            else:
                await _conn.execute(
                    "INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted) VALUES (?, ?, ?, ?, ?)",
                    (self.task_id, old_dir_path, None, True, True),
                )

            # 插入新目录记录
            await _conn.execute(
                "INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted) VALUES (?, ?, ?, ?, ?)",
                (self.task_id, new_dir_path, self.mapping[new_dir_path], True, False),
            )

            # 处理子目录和文件
            cursor = await _conn.execute(
                "SELECT id, path, staging_path, is_dir FROM staging_records WHERE task_id = ? AND path LIKE ? AND is_dir = 1",
                (self.task_id, old_dir_path + "/%"),
            )
            for row in await cursor.fetchall():
                old_sub_path = row["path"]
                new_sub_path = new_dir_path + old_sub_path[len(old_dir_path):]
                # 更新旧路径为已删除
                await _conn.execute(
                    "UPDATE staging_records SET deleted = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (True, row["id"]),
                )
                # 插入新路径记录
                await _conn.execute(
                    "INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted) VALUES (?, ?, ?, ?, ?)",
                    (self.task_id, new_sub_path, row["staging_path"], row["is_dir"], False),
                )
        except Exception as e:
            logger.error(f"更新暂存区目录重命名状态失败: {e}")

        logger.debug(f"在暂存区重命名目录{old_dir_path}为{new_dir_path}")

    async def load(self):
        """从数据库加载暂存区"""
        # 从数据库加载记录
        try:
            async with db_pool.get_conn() as conn:
                cursor = await conn.execute(
                    "SELECT path, staging_path, is_dir, deleted FROM staging_records WHERE task_id = ?",
                    (self.task_id,),
                )
                for row in await cursor.fetchall():
                    path = row["path"]
                    staging_path = row["staging_path"]
                    is_dir = row["is_dir"]
                    deleted = row["deleted"]

                    # 更新映射缓存
                    if staging_path is not None:
                        self.mapping[path] = staging_path

                    # 更新删除状态缓存
                    if is_dir:
                        self.deleted_dir_mapping[path] = deleted
                    else:
                        self.deleted_mapping[path] = deleted
        except Exception as e:
            logger.error(f"加载暂存区记录失败: {e}")

        logger.info(f"加载StagingArea记录成功，任务 ID: {self.task_id}")

    def clear(self):
        """清空缓存"""
        self.mapping.clear()
        self.deleted_mapping.clear()
        self.deleted_dir_mapping.clear()
        logger.info(f"StagingArea清空成功, task_id={self.task_id}")
