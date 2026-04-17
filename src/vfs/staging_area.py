import hashlib
import os
from dataclasses import dataclass
import sqlite3

from src.config import DB_PATH, STAGING_AREA_PATH


# TODO 有无必要把要写入数据库的记录先缓存起来，再批量写入数据库
# TODO 把staging_path作为其他表的冗余项

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

def get_staging_area() -> StagingArea:
    """获取StagingArea单例"""
    staging_area = StagingArea()
    return staging_area

class StagingArea:
    """控制暂存区路径的分发"""

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.task_id = None  # 任务id
            self.mapping = {}  # 所有文件/目录路径到暂存区路径的映射
            self.deleted_mapping = {}  # 标记文件是否在暂存区被删除
            self.deleted_dir_mapping = {}  # 标记目录是否在暂存区被删除
            StagingArea._initialized = True

    def get_staging_path(self, path: str) -> str | None:
        """
        获取暂存区路径，如果已被删除或不存在则返回None
        """
        if not self.deleted_mapping.get(path, False) and path in self.mapping:
            # 遍历deleted_dir_mapping，检查path是否在已删除的目录下
            for dir_path, is_deleted in self.deleted_dir_mapping.items():
                if is_deleted and path.startswith(dir_path + "/"):
                    # 如果path在已删除的目录下，将deleted_mapping对应值设为True
                    self.deleted_mapping[path] = True
                    return None
            # 正常返回暂存区路径
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

    def register(self, path: str) -> str:
        """
        分配一条暂存区路径
        """
        # TODO 暂存区具体路径待定
        # 将path转换为哈希值并保留扩展名，作为暂存区路径的文件名，避免因为path中包含“/”而导致创建目录
        path_hash = hashlib.md5(path.encode()).hexdigest()
        _, ext = os.path.splitext(path)
        staging_path = f"{STAGING_AREA_PATH}/{self.task_id}/{path_hash}{ext}"

        # 更新缓存
        self.mapping[path] = staging_path
        # 更新删除状态缓存
        self.deleted_mapping[path] = False

        # 写入数据库
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row  # 使结果集可以通过列名访问
            cursor = conn.cursor()

            # 检查是否已存在记录
            cursor.execute('''
            SELECT id FROM staging_records 
            WHERE task_id = ? AND path = ?
            ''', (self.task_id, path))

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
                ''', (self.task_id, path, staging_path, False, False))

            conn.commit()
        except Exception as e:
            print(f"写入暂存区记录失败: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

        return staging_path

    def register_dir(self, path: str) -> str:
        """
        分配一条目录暂存区路径
        """
        staging_path = " "  # 不实际创建目录，作为占位符

        self.mapping[path] = staging_path
        self.deleted_dir_mapping[path] = False

        # 写入数据库
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row  # 使结果集可以通过列名访问
            cursor = conn.cursor()

            # 检查是否已存在记录
            cursor.execute('''
            SELECT id FROM staging_records 
            WHERE task_id = ? AND path = ?
            ''', (self.task_id, path))

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
                ''', (self.task_id, path, staging_path, True, False))

            conn.commit()
        except Exception as e:
            print(f"写入暂存区目录记录失败: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

        return staging_path

    def delete(self, path: str) -> None:
        """
        删除暂存区路径（设置deleted为True）
        """
        # # 如果path在暂存区中，就删除暂存区中的文件
        # staging_path = self.get_staging_path(path)
        # if staging_path:
        #     del self.mapping[path]
        #     # TODO: 删除文件
        #     # delete(staging_path)

        # 更新缓存中的删除状态
        self.deleted_mapping[path] = True

        # 更新数据库
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row  # 使结果集可以通过列名访问
            cursor = conn.cursor()

            # 检查是否已存在记录
            cursor.execute('''
            SELECT id FROM staging_records 
            WHERE task_id = ? AND path = ?
            ''', (self.task_id, path))

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
                ''', (self.task_id, path, None, False, True))

            conn.commit()
        except Exception as e:
            print(f"更新暂存区删除状态失败: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def is_deleted(self, path: str) -> bool:
        """判断path是否在暂存区内删除（真实路径可能还存在）"""
        return self.deleted_mapping.get(path, False)

    def delete_dir(self, path: str):
        """
        删除目录暂存区路径（设置deleted为True）
        """
        # 如果path在暂存区中，就删除暂存区中的目录
        staging_path = self.get_staging_dir_path(path)
        if staging_path:
            del self.mapping[path]

        # 更新缓存中的删除状态
        self.deleted_dir_mapping[path] = True

        # 遍历deleted_dir_mapping，更新子目录的删除状态
        for dir_path in list(self.deleted_dir_mapping.keys()):
            if dir_path.startswith(path + "/"):
                del self.mapping[dir_path]
                self.deleted_dir_mapping[dir_path] = True

        # 更新数据库
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row  # 使结果集可以通过列名访问
            cursor = conn.cursor()

            # 开始事务
            conn.execute('BEGIN TRANSACTION')

            # 处理主目录
            cursor.execute('''
            SELECT id FROM staging_records 
            WHERE task_id = ? AND path = ?
            ''', (self.task_id, path))

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
                ''', (self.task_id, path, None, True, True))

            # 处理子目录
            cursor.execute('''
            SELECT id FROM staging_records 
            WHERE task_id = ? AND path LIKE ? AND is_dir = True
            ''', (self.task_id, path + '/%'))

            for row in cursor.fetchall():
                cursor.execute('''
                UPDATE staging_records 
                SET deleted = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                ''', (True, row['id']))

            conn.commit()
        except Exception as e:
            print(f"更新暂存区目录删除状态失败: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def is_deleted_dir(self, path: str) -> bool:
        """判断path是否在暂存区内删除（真实路径可能还存在）"""
        return self.deleted_dir_mapping.get(path, False)

    def rename(self, old_path: str, new_path: str) -> None:
        """
        重命名暂存区路径
        """
        # 更新缓存中的路径映射关系
        self.mapping[new_path] = self.mapping[old_path]
        del self.mapping[old_path]

        # 更新删除状态缓存
        self.deleted_mapping[new_path] = self.deleted_mapping[old_path]
        # 标记原路径为已删除
        self.deleted_mapping[old_path] = True

        # 更新数据库
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row  # 使结果集可以通过列名访问
            cursor = conn.cursor()

            # 开始事务
            conn.execute('BEGIN TRANSACTION')

            # 检查旧路径是否存在
            cursor.execute('''
            SELECT id FROM staging_records 
            WHERE task_id = ? AND path = ?
            ''', (self.task_id, old_path))

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
                ''', (self.task_id, old_path, False, True))

            # 插入新路径记录
            cursor.execute('''
            INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted)
            VALUES (?, ?, ?, ?, ?)
            ''', (self.task_id, new_path, self.mapping[new_path], False, False))

            conn.commit()
        except Exception as e:
            print(f"更新暂存区重命名状态失败: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def rename_dir(self, old_dir_path: str, new_dir_path: str) -> None:
        """
        重命名目录暂存区路径
        """
        # 1、更新目录缓存
        # 更新缓存中的路径映射关系
        self.mapping[new_dir_path] = self.mapping[old_dir_path]
        del self.mapping[old_dir_path]
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
                del self.mapping[old_path]

                # 更新删除状态映射
                if old_path in self.deleted_mapping:
                    self.deleted_mapping[new_sub_path] = self.deleted_mapping[old_path]
                    self.deleted_mapping[old_path] = True
                elif old_path in self.deleted_dir_mapping:
                    self.deleted_dir_mapping[new_sub_path] = self.deleted_dir_mapping[old_path]
                    self.deleted_dir_mapping[old_path] = True

        # 更新数据库
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row  # 使结果集可以通过列名访问
            cursor = conn.cursor()

            # 开始事务
            conn.execute('BEGIN TRANSACTION')

            # 处理主目录
            cursor.execute('''
            SELECT id FROM staging_records 
            WHERE task_id = ? AND path = ?
            ''', (self.task_id, old_dir_path))

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
                ''', (self.task_id, old_dir_path, None, True, True))

            # 插入新目录记录
            cursor.execute('''
            INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted)
            VALUES (?, ?, ?, ?, ?)
            ''', (self.task_id, new_dir_path, self.mapping[new_dir_path], True, False))

            # 处理子目录和文件
            cursor.execute('''
            SELECT id, path FROM staging_records 
            WHERE task_id = ? AND path LIKE ? AND is_dir = TRUE
            ''', (self.task_id, old_dir_path + '/%'))

            for row in cursor.fetchall():
                old_sub_path = row['path']
                new_sub_path = new_dir_path + old_sub_path[len(old_dir_path):]
                # 更新旧路径记录为已删除
                cursor.execute('''
                UPDATE staging_records 
                SET deleted = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                ''', (True, row['id']))
                # 插入新路径记录
                cursor.execute('''
                INSERT INTO staging_records (task_id, path, staging_path, is_dir, deleted)
                VALUES (?, ?, ?, ?, ?)
                ''', (self.task_id, new_sub_path, row['staging_path'], row['is_dir'], False))

            conn.commit()
        except Exception as e:
            print(f"更新暂存区目录重命名状态失败: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def load(self, task_id: str):
        """
        从数据库加载暂存区

        Args:
            task_id: 任务 ID
        """
        # 清空当前缓存
        self.clear()
        self.task_id = task_id

        # 从数据库加载记录
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row  # 使结果集可以通过列名访问
            cursor = conn.cursor()

            # 查询所有该任务的暂存区记录
            cursor.execute('''
            SELECT path, staging_path, is_dir, deleted
            FROM staging_records
            WHERE task_id = ?
            ''', (task_id,))

            # 处理加载的记录
            for row in cursor.fetchall():
                path = row['path']
                staging_path = row['staging_path']
                is_dir = row['is_dir']
                deleted = row['deleted']

                # 更新映射缓存
                if staging_path is not None:
                    self.mapping[path] = staging_path

                # 更新删除状态缓存
                if is_dir:
                    self.deleted_dir_mapping[path] = deleted
                else:
                    self.deleted_mapping[path] = deleted
        except Exception as e:
            print(f"加载暂存区记录失败: {e}")
        finally:
            if conn:
                conn.close()

    def clear(self):
        """清空缓存"""
        self.task_id = None
        self.mapping.clear()
        self.deleted_mapping.clear()
        self.deleted_dir_mapping.clear()

