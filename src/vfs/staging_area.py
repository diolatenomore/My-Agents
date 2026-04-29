import hashlib
import os
from dataclasses import dataclass
from typing import Optional

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
    """控制暂存区路径的分发"""
    task_id: Optional[str] = None  #  任务id
    mapping: dict[str, str] = {}  # 所有文件/目录路径到暂存区路径的映射
    deleted_mapping: dict[str, bool] = {}  # 标记文件是否在暂存区被删除
    deleted_dir_mapping: dict[str, bool] = {}  # 标记目录是否在暂存区被删除

    @classmethod
    def get_staging_path(cls, path: str) -> str | None:
        """
        获取暂存区路径，如果已被删除或不存在则返回None
        """
        if not cls.deleted_mapping.get(path, False) and path in cls.mapping:
            # 遍历deleted_dir_mapping，检查path是否在已删除的目录下
            for dir_path, is_deleted in cls.deleted_dir_mapping.items():
                if is_deleted and path.startswith(dir_path + "/"):
                    # 如果path在已删除的目录下，将deleted_mapping对应值设为True
                    cls.deleted_mapping[path] = True
                    return None
            # 正常返回暂存区路径
            return cls.mapping[path]
        return None

    @classmethod
    def get_staging_dir_path(cls, path: str) -> str | None:
        """
        获取暂存区目录路径，如果已被删除或不存在则返回None
        """
        if not cls.deleted_dir_mapping.get(path, False) and path in cls.mapping:
            # 如果path是目录，就返回目录路径
            return cls.mapping[path]
        return None

    @classmethod
    def register(cls, path: str) -> str:
        """
        分配一条暂存区路径
        """
        # TODO 暂存区具体路径待定
        # 将path转换为哈希值并保留扩展名，作为暂存区路径的文件名，避免因为path中包含“/”而导致创建目录
        path_hash = hashlib.md5(path.encode()).hexdigest()
        _, ext = os.path.splitext(path)
        staging_path = f"{STAGING_AREA_PATH}/{cls.task_id}/{path_hash}{ext}"

        # 更新缓存
        cls.mapping[path] = staging_path
        # 更新删除状态缓存
        cls.deleted_mapping[path] = False

        # 写入数据库
        try:
            with db_pool.get_conn() as conn:
                cursor = conn.cursor()
                # 检查是否已存在记录
                cursor.execute('''
                SELECT id FROM staging_records 
                WHERE task_id = ? AND path = ?
                ''', (cls.task_id, path))

                existing = cursor.fetchone()
                if existing:
                    # 更新现有记录
                    cursor.execute('''
                    UPDATE staging_records 
                    SET staging_path = ?, deleted = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    ''', (staging_path, False, existing['id']))
                else:
                    # 插入新记录
                    cursor.execute('''
                    INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted)
                    VALUES (?, ?, ?, ?, ?)
                    ''', (cls.task_id, path, staging_path, False, False))

                conn.commit()
        except Exception as e:
            logger.error(f"写入暂存区记录失败: {e}")

        logger.debug(f"为文件{path}分配暂存区路径: {staging_path}")
        return staging_path

    @classmethod
    def register_dir(cls, path: str) -> str:
        """
        分配一条目录暂存区路径
        """
        staging_path = " "  # 不实际创建目录，作为占位符

        cls.mapping[path] = staging_path
        cls.deleted_dir_mapping[path] = False

        # 写入数据库
        try:
            with db_pool.get_conn() as conn:
                cursor = conn.cursor()
                # 检查是否已存在记录
                cursor.execute('''
                SELECT id FROM staging_records 
                WHERE task_id = ? AND path = ?
                ''', (cls.task_id, path))

                existing = cursor.fetchone()
                if existing:
                    # 更新现有记录
                    cursor.execute('''
                    UPDATE staging_records 
                    SET staging_path = ?, is_dir = ?, deleted = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    ''', (staging_path, True, False, existing['id']))
                else:
                    # 插入新记录
                    cursor.execute('''
                    INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted)
                    VALUES (?, ?, ?, ?, ?)
                    ''', (cls.task_id, path, staging_path, True, False))

                conn.commit()
        except Exception as e:
            logger.error(f"写入暂存区目录记录失败: {e}")

        logger.debug(f"为目录{path}分配暂存区路径: {staging_path}")
        return staging_path

    @classmethod
    def delete(cls, path: str) -> None:
        """
        删除暂存区路径（设置deleted为True）
        """
        # # 如果path在暂存区中，就删除暂存区中的文件
        # staging_path = cls.get_staging_path(path)
        # if staging_path:
        #     del cls.mapping[path]
        #     # TODO: 删除文件
        #     # delete(staging_path)

        # 更新缓存中的删除状态
        cls.deleted_mapping[path] = True

        # 更新数据库
        try:
            with db_pool.get_conn() as conn:
                cursor = conn.cursor()
                # 检查是否已存在记录
                cursor.execute('''
                SELECT id FROM staging_records 
                WHERE task_id = ? AND path = ?
                ''', (cls.task_id, path))

                existing = cursor.fetchone()
                if existing:
                    # 更新现有记录
                    cursor.execute('''
                    UPDATE staging_records 
                    SET deleted = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    ''', (True, existing['id']))
                else:
                    # 插入新记录
                    cursor.execute('''
                    INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted)
                    VALUES (?, ?, ?, ?, ?)
                    ''', (cls.task_id, path, None, False, True))

                conn.commit()
        except Exception as e:
            logger.error(f"更新暂存区删除状态失败: {e}")
        
        logger.debug(f"在暂存区删除文件{path}")

    @classmethod
    def is_deleted(cls, path: str) -> bool:
        """判断path是否在暂存区内删除（真实路径可能还存在）"""
        return cls.deleted_mapping.get(path, False)

    @classmethod
    def delete_dir(cls, path: str):
        """
        删除目录暂存区路径（设置deleted为True）
        """
        # 如果path在暂存区中，就删除暂存区中的目录
        staging_path = cls.get_staging_dir_path(path)
        if staging_path:
            del cls.mapping[path]

        # 更新缓存中的删除状态
        cls.deleted_dir_mapping[path] = True

        # 遍历deleted_dir_mapping，更新子目录的删除状态
        for dir_path in list(cls.deleted_dir_mapping.keys()):
            if dir_path.startswith(path + "/"):
                del cls.mapping[dir_path]
                cls.deleted_dir_mapping[dir_path] = True

        # 更新数据库
        try:
            with db_pool.get_conn() as conn:
                cursor = conn.cursor()

                # 处理主目录
                # 检查是否已存在记录
                cursor.execute('''
                SELECT id FROM staging_records 
                WHERE task_id = ? AND path = ?
                ''', (cls.task_id, path))

                existing = cursor.fetchone()
                if existing:
                    # 更新现有记录
                    cursor.execute('''
                    UPDATE staging_records 
                    SET deleted = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    ''', (True, existing['id']))
                else:
                    # 插入新记录
                    cursor.execute('''
                    INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted)
                    VALUES (?, ?, ?, ?, ?)
                    ''', (cls.task_id, path, None, True, True))

                # 处理子目录
                cursor.execute('''
                SELECT id FROM staging_records 
                WHERE task_id = ? AND path LIKE ? AND is_dir = True
                ''', (cls.task_id, path + '/%'))

                for row in cursor.fetchall():
                    cursor.execute('''
                    UPDATE staging_records 
                    SET deleted = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    ''', (True, row['id']))

                conn.commit()
        except Exception as e:
            logger.error(f"更新暂存区目录删除状态失败: {e}")
        
        logger.debug(f"在暂存区删除目录{path}")

    @classmethod
    def is_deleted_dir(cls, path: str) -> bool:
        """判断path是否在暂存区内删除（真实路径可能还存在）"""
        return cls.deleted_dir_mapping.get(path, False)

    @classmethod
    def rename(cls, old_path: str, new_path: str) -> None:
        """
        重命名暂存区路径
        """
        # 更新缓存中的路径映射关系
        cls.mapping[new_path] = cls.mapping[old_path]
        del cls.mapping[old_path]

        # 更新删除状态缓存
        cls.deleted_mapping[new_path] = cls.deleted_mapping[old_path]
        # 标记原路径为已删除
        cls.deleted_mapping[old_path] = True

        # 更新数据库
        try:
            with db_pool.get_conn() as conn:
                cursor = conn.cursor()

                # 检查旧路径是否存在
                cursor.execute('''
                SELECT id FROM staging_records 
                WHERE task_id = ? AND path = ?
                ''', (cls.task_id, old_path))

                existing = cursor.fetchone()
                if existing:
                    # 更新旧路径记录为已删除
                    cursor.execute('''
                    UPDATE staging_records 
                    SET deleted = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    ''', (True, existing['id']))
                else:
                    # 插入旧路径删除记录
                    cursor.execute('''
                    INSERT INTO staging_records (task_id, path, is_dir, deleted)
                    VALUES (?, ?, ?, ?)
                    ''', (cls.task_id, old_path, False, True))

                # 插入新路径记录
                cursor.execute('''
                INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted)
                VALUES (?, ?, ?, ?, ?)
                ''', (cls.task_id, new_path, cls.mapping[new_path], False, False))

                conn.commit()
        except Exception as e:
            logger.error(f"更新暂存区重命名状态失败: {e}")
        
        logger.debug(f"在暂存区重命名文件{old_path}为{new_path}")
                
    @classmethod
    def rename_dir(cls, old_dir_path: str, new_dir_path: str) -> None:
        """
        重命名目录暂存区路径
        """
        # 1、更新目录缓存
        # 更新缓存中的路径映射关系
        cls.mapping[new_dir_path] = cls.mapping[old_dir_path]
        del cls.mapping[old_dir_path]
        # 更新删除状态缓存
        cls.deleted_dir_mapping[new_dir_path] = cls.deleted_dir_mapping[old_dir_path]
        # 标记原目录被删除
        cls.deleted_dir_mapping[old_dir_path] = True

        # 2、更新子目录缓存
        # 遍历所有已注册的路径，更新子文件/子目录的路径
        for old_path in list(cls.mapping.keys()):
            if old_path.startswith(old_dir_path + "/"):
                # 替换前缀
                new_sub_path = new_dir_path + old_path[len(old_dir_path):]
                cls.mapping[new_sub_path] = cls.mapping[old_path]
                del cls.mapping[old_path]

                # 更新删除状态映射
                if old_path in cls.deleted_mapping:
                    cls.deleted_mapping[new_sub_path] = cls.deleted_mapping[old_path]
                    cls.deleted_mapping[old_path] = True
                elif old_path in cls.deleted_dir_mapping:
                    cls.deleted_dir_mapping[new_sub_path] = cls.deleted_dir_mapping[old_path]
                    cls.deleted_dir_mapping[old_path] = True

        # 更新数据库
        try:
            with db_pool.get_conn() as conn:
                cursor = conn.cursor()

                # 处理主目录
                # 检查旧目录记录是否存在
                cursor.execute('''
                SELECT id FROM staging_records 
                WHERE task_id = ? AND path = ?
                ''', (cls.task_id, old_dir_path))

                existing = cursor.fetchone()
                if existing:
                    # 更新旧目录记录为已删除
                    cursor.execute('''
                    UPDATE staging_records 
                    SET deleted = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    ''', (True, existing['id']))
                else:
                    cursor.execute('''
                    INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted)
                    VALUES (?, ?, ?, ?, ?)
                    ''', (cls.task_id, old_dir_path, None, True, True))

                # 插入新目录记录
                cursor.execute('''
                INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted)
                VALUES (?, ?, ?, ?, ?)
                ''', (cls.task_id, new_dir_path, cls.mapping[new_dir_path], True, False))

                # 处理子目录和文件
                cursor.execute('''
                SELECT id, path, staging_path, is_dir FROM staging_records 
                WHERE task_id = ? AND path LIKE ? AND is_dir = TRUE
                ''', (cls.task_id, old_dir_path + '/%'))

                for row in cursor.fetchall():
                    old_sub_path = row['path']
                    new_sub_path = new_dir_path + old_sub_path[len(old_dir_path):]
                    # 更新旧路径为已删除
                    cursor.execute('''
                    UPDATE staging_records 
                    SET deleted = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    ''', (True, row['id']))
                    # 插入新路径记录
                    cursor.execute('''
                    INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted)
                    VALUES (?, ?, ?, ?, ?)
                    ''', (cls.task_id, new_sub_path, row['staging_path'], row['is_dir'], False))

                conn.commit()
        except Exception as e:
            logger.error(f"更新暂存区目录重命名状态失败: {e}")
        
        logger.debug(f"在暂存区重命名目录{old_dir_path}为{new_dir_path}")
                
    @classmethod
    def load(cls, task_id: str):
        """
        从数据库加载暂存区

        Args:
            task_id: 任务 ID
        """
        # 检查当前是否有其他文件整理任务正在进行
        if cls.task_id is not None:
            raise ValueError(f"当前正在处理任务 ID {cls.task_id}")

        cls.task_id = task_id

        # 从数据库加载记录
        try:
            with db_pool.get_conn() as conn:
                cursor = conn.cursor()
                # 查询所有该任务的暂存区记录
                cursor.execute('''
                SELECT path, staging_path, is_dir, deleted
                FROM staging_records
                WHERE task_id = ?
                ''', (task_id,))

                for row in cursor.fetchall():
                    path = row['path']
                    staging_path = row['staging_path']
                    is_dir = row['is_dir']
                    deleted = row['deleted']

                    # 更新映射缓存
                    if staging_path is not None:
                        cls.mapping[path] = staging_path

                    # 更新删除状态缓存
                    if is_dir:
                        cls.deleted_dir_mapping[path] = deleted
                    else:
                        cls.deleted_mapping[path] = deleted
        except Exception as e:
            logger.error(f"加载暂存区记录失败: {e}")
        
        logger.info(f"加载StagingArea记录成功，任务 ID: {task_id}")
                
    @classmethod
    def clear(cls):
        """清空缓存"""
        cls.task_id = None
        cls.mapping.clear()
        cls.deleted_mapping.clear()
        cls.deleted_dir_mapping.clear()
        logger.info("StagingArea清空成功")

