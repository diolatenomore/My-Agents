from dataclasses import dataclass
from typing import Optional, Dict, List
import sqlite3
import os

from src.config import DB_PATH
from src.vfs.staging_area import get_staging_area
from src.utils.vfs import copy

# TODO 有无必要把要写入数据库的记录先缓存起来，再批量写入数据库

@dataclass
class CopyRecord:
    task_id: str  #  任务id
    source_path: str  #  源路径
    target_path: str  #  目标路径
    is_copied: bool = False  #  该条记录是否已完成复制
    is_dir: bool = False  # 是否是目录操作
    staging_path: Optional[str] = None  #  暂存区路径


def get_copy_mapping() -> CopyMapping:
    """获取CopyMapping单例"""
    copy_mapping = CopyMapping()
    return copy_mapping


class CopyMapping:
    """复制映射类，用于存储复制记录"""
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.task_id = None  #  任务id
            self.registered_num = {}  # 记录某个文件作为source_path的次数
            self.copied_num = {}  # 记录某个文件作为source_path已被拷贝的次数
            self.dir_mapping = {}  # 记录从source_path到target_path的目录映射关系
            self.dir_copy_done = {}  # 记录某个目录已被拷贝的子文件路径
            CopyMapping._initialized = True

    def register(self, source_path: str, target_path: str):
        """注册复制记录"""
        # 更新缓存
        self.registered_num[source_path] = self.registered_num.get(source_path, 0) + 1

        # 写入到数据库
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row  # 使结果集可以通过列名访问
            cursor = conn.cursor()
            
            # 插入复制记录
            cursor.execute('''
            INSERT INTO copy_records (task_id, source_path, target_path, is_copied, is_dir)
            VALUES (?, ?, ?, ?, ?)
            ''', (
                self.task_id,
                source_path,
                target_path,
                0,  # 初始未复制
                False  # 非目录操作
            ))
            
            conn.commit()
        except Exception as e:
            print(f"写入复制记录失败: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
        
    def register_dir(self, source_path: str, target_path: str):
        """注册目录映射"""
        self.dir_mapping[source_path] = target_path

        # 写入到数据库
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row  # 使结果集可以通过列名访问
            cursor = conn.cursor()
            
            # 插入目录复制记录
            cursor.execute('''
            INSERT INTO copy_records (task_id, source_path, target_path, is_copied, is_dir)
            VALUES (?, ?, ?, ?, ?)
            ''', (
                self.task_id,
                source_path,
                target_path,
                0,  # 初始未复制
                True  # 目录操作
            ))
            
            conn.commit()
        except Exception as e:
            print(f"写入目录复制记录失败: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def need_copied(self, source_path: str) -> bool:
        """
        判断原文件是否需要被拷贝或无需拷贝
        返回false：无需拷贝或者已经被拷贝
        返回true：需要被拷贝
        """
        # 从缓存获取数据
        copied_num = self.copied_num.get(source_path, 0)
        registered_num = self.registered_num.get(source_path, 0)

        # 加上对应的目录拷贝次数
        for dir_path in self.dir_mapping.keys():
            if source_path.startswith(dir_path + "/"):
                registered_num += 1
        
        # 已被拷贝数与总数不一致则返回true
        return copied_num != registered_num
        

    def mark_copied(self, source_path: str):
        """拷贝所有未被拷贝的文件并修改标记"""
        records = self.get_from_db(task_id=self.task_id, source_path=source_path)
        # 如果原文件有暂存区路径则使用
        staging_area = get_staging_area()
        source_staging_path = staging_area.mapping.get(source_path)  # TODO 直接获取路径，不判断是否被删除
        path = source_staging_path if source_staging_path else source_path
        
        # 处理精确拷贝情况（source_path作为copy_file操作的原路径）
        update_ids = []
        for record in records:
            if not record.is_copied:
                target_staging_path = staging_area.get_staging_path(record.target_path)
                if not os.path.exists(target_staging_path):
                    # 拷贝文件
                    copy(path, target_staging_path)
                # 更新缓存
                self.copied_num[source_path] = self.copied_num.get(source_path, 0) + 1
                update_ids.append(record.id)

        # 更新数据库
        if update_ids:
            # 开始事务
            conn = None
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row  # 使结果集可以通过列名访问
                conn.execute('BEGIN TRANSACTION')
                cursor = conn.cursor()
                # 更新数据库，标记该条记录已完成复制
                for update_id in update_ids:
                    cursor.execute('''
                    UPDATE copy_records 
                    SET is_copied = 1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    ''', (update_id,))  # get_from_db返回的record会附带上id字段 
                conn.commit()
            except Exception as e:
                print(f"标记复制完成失败: {e}")
                if conn:
                    conn.rollback()
            finally:
                if conn:
                    conn.close()
                    
        # 处理目录拷贝情况（copy_dir操作的原路径作为source_path的前缀）
        for dir_path in self.dir_mapping.keys():
            if source_path.startswith(dir_path + "/") and source_path not in self.dir_copy_done.get(dir_path, []):
                # 计算目标路径
                target_path = self.dir_mapping[dir_path] + source_path[len(dir_path):]
                target_staging_path = staging_area.get_staging_path(target_path)
                if not os.path.exists(target_staging_path):                
                    # 拷贝文件
                    copy(path, target_staging_path)
                # 标记该该文件已完成对应的目录拷贝
                self.dir_copy_done.setdefault(dir_path, []).append(source_path)
        

    def need_copied_dir(self, source_path: str) -> bool:
        """判断目录是否需要被拷贝"""
        return source_path in self.dir_mapping.keys()

    def mark_copied_dir(self, source_path: str):
        """拷贝所有该目录下的未被拷贝的文件并修改标记"""
        # 拷贝目录下的所有文件和子目录至暂存区
        target_path = self.dir_mapping[source_path]  # 目标目录完整路径
        staging_area = get_staging_area()
        for root, dirs, files in os.walk(source_path):
        # root: 当前遍历目录的完整路径      dirs: 当前目录下的子目录列表    files: 当前目录下的文件列表
            for file_name in files:
                # 构造目标文件完整路径
                source_file = os.path.join(root, file_name)         # 原文件完整路径
                target_file = source_file.replace(source_path, target_path, 1)  # 目标文件完整路径
                
                target_staging_path = staging_area.get_staging_path(target_file)
                # 如果暂存区路径不真实存在则拷贝文件到暂存区
                if not os.path.exists(target_staging_path):
                    # 如果原文件有暂存区路径则使用
                    source_staging_path = staging_area.mapping.get(source_file)  # TODO 直接获取路径，不判断是否被删除
                    path = source_staging_path if source_staging_path else source_file
                    # 拷贝文件
                    copy(path, target_staging_path)
               
        # 修改数据库，标记该目录及所有子目录已完成复制
        # 收集所有需要标记的目录路径
        dir_paths_to_update = [source_path]
        # 从缓存中查找所有子目录的复制记录
        for dir_source_path in self.dir_mapping.keys():
            if dir_source_path.startswith(source_path + '/'):
                dir_paths_to_update.append(dir_source_path)

        # 开始事务
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row  # 使结果集可以通过列名访问
            conn.execute('BEGIN TRANSACTION')
            cursor = conn.cursor()
            
            # 更新所有目录复制记录，标记为已完成复制
            for dir_path in dir_paths_to_update:
                cursor.execute('''
                UPDATE copy_records 
                SET is_copied = 1, updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ? AND source_path = ? AND is_dir = 1
                ''', (self.task_id, dir_path))
            
            conn.commit()
        except Exception as e:
            print(f"标记目录复制完成失败: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def copy_if_need(self, target_path: str):
        """
        判断target_path是否需要拷贝，如果是，拷贝并修改标记。
        """
        # TODO 改为从缓存中查询，或者根据staging_path是否真正存在来判断
        # 判断是否为精确拷贝（target_path作为copy_file操作的目标路径）
        record = self.get_from_db(task_id=self.task_id, target_path=target_path)
        staging_area = get_staging_area()
        # 不为None，说明是精确拷贝
        if record:
            # 已拷贝，跳过
            if record[0].is_copied:
                return
            
            # 如果原文件有暂存区路径则使用
            staging_path_source = staging_area.mapping.get(record[0].source_path)  # TODO 直接获取路径，不判断是否被删除
            path = staging_path_source if staging_path_source else record[0].source_path
            
            copy(path, staging_area.get_staging_path(target_path))
            
            # 标记source_path已被拷贝一次
            self.copied_num[record[0].source_path] = self.copied_num.get(record[0].source_path, 0) + 1

            # 更新数据库中的字段
            conn = None
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row  # 使结果集可以通过列名访问
                cursor = conn.cursor()

                # 更新数据库，标记该条记录已完成复制
                cursor.execute('''
                UPDATE copy_records 
                SET is_copied = 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                ''', (record[0].id,))  # get_from_db返回的record会附带上id字段
                conn.commit()
            except Exception as e:
                print(f"标记复制完成失败: {e}")
                if conn:
                    conn.rollback()
            finally:
                if conn:
                    conn.close()

        # 判断是否为目录拷贝（target_path作为copy_dir操作的目标路径）
        else:        
            
            for dir_source_path, dir_target_path in self.dir_mapping.items():
                if target_path.startswith(dir_target_path + "/"):
                    # 计算源路径
                    source_path = dir_source_path + target_path[len(dir_target_path):]
                    # 已拷贝，结束
                    if source_path in self.dir_copy_done.get(dir_source_path, []):
                        break

                    target_staging_path = staging_area.get_staging_path(target_path)
                    if not os.path.exists(target_staging_path):    
                        # 如果原文件有暂存区路径则使用
                        staging_path_source = staging_area.mapping.get(source_path)  # 直接获取路径，不判断是否被删除
                        path = staging_path_source if staging_path_source else source_path
                        # 拷贝文件
                        copy(path, target_staging_path)
                    # 标记source_path文件已完成对应的目录拷贝
                    self.dir_copy_done.setdefault(dir_source_path, []).append(source_path)
                    # 结束
                    break

    def rename(self, old_path: str, new_path: str):
        """修改映射"""

        # 如果old_path作为source_path，则更新缓存
        if old_path in self.copied_num:
            self.copied_num[new_path] = self.copied_num[old_path]
            self.registered_num[new_path] = self.registered_num[old_path]
            del self.copied_num[old_path]
            del self.registered_num[old_path]

        # 更新数据库，把old_path（source_path/target_path）替换为new_path
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row  # 使结果集可以通过列名访问
            conn.execute('BEGIN TRANSACTION')
            cursor = conn.cursor()
            
            # 更新源路径为old_path的记录
            cursor.execute('''
            UPDATE copy_records 
            SET source_path = ?, updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND source_path = ?
            ''', (new_path, self.task_id, old_path))
            
            # 更新目标路径为old_path的记录
            cursor.execute('''
            UPDATE copy_records 
            SET target_path = ?, updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND target_path = ?
            ''', (new_path, self.task_id, old_path))
            
            conn.commit()
        except Exception as e:
            print(f"更新复制记录路径失败: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def rename_dir(self, old_dir_path: str, new_dir_path: str):
        """修改目录映射"""
        # 1. 处理 dir_mapping
        new_dir_mapping = {}
        for source, target in self.dir_mapping.items():
            # 替换 key 中的 old_dir_path
            if source == old_dir_path:
                new_dir_mapping[new_dir_path] = target
            # 替换 value 中的 old_dir_path
            elif target == old_dir_path:
                new_dir_mapping[source] = new_dir_path
            else:
                new_dir_mapping[source] = target
        self.dir_mapping = new_dir_mapping

        # 2. 处理 dir_copy_done
        for source, paths in list(self.dir_copy_done.items()):
            # 替换 key 中的 old_dir_path
            if source == old_dir_path:
                # 替换list中的前缀
                new_paths = []
                for path in paths:
                    new_path = new_dir_path + path[len(old_dir_path):]
                    new_paths.append(new_path)

                self.dir_copy_done[new_dir_path] = new_paths
                del self.dir_copy_done[old_dir_path]

        # 3. 处理 registered_num 和 copied_num 的前缀
        def replace_prefix(mapping):
            new_mapping = {}
            for path, value in mapping.items():
                if path.startswith(old_dir_path + '/'):
                    # 替换前缀
                    new_path = new_dir_path + path[len(old_dir_path):]
                    new_mapping[new_path] = value
                else:
                    new_mapping[path] = value
            return new_mapping

        self.registered_num = replace_prefix(self.registered_num)
        self.copied_num = replace_prefix(self.copied_num)

        # 更新数据库
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            conn.execute('BEGIN TRANSACTION')

            # 情况 A：更新目录本身（is_dir = 1 且路径完全匹配）
            # 更新 source_path 匹配的记录
            cursor.execute('''
                UPDATE copy_records 
                SET source_path = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ? 
                  AND source_path = ? 
                  AND is_dir = 1
            ''', (new_dir_path, self.task_id, old_dir_path))

            # 更新 target_path 匹配的记录
            cursor.execute('''
                UPDATE copy_records 
                SET target_path = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ? 
                  AND target_path = ? 
                  AND is_dir = 1
            ''', (new_dir_path, self.task_id, old_dir_path))

            # 情况 B：更新子内容（以 old_dir_path/ 为前缀的文件和子目录）
            # 使用 SUBSTR 保留原路径的后缀部分

            # 更新 source_path 以 old_dir_path/ 开头的记录
            cursor.execute('''
                UPDATE copy_records 
                SET source_path = ? || SUBSTR(source_path, ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ? 
                  AND source_path LIKE ?
            ''', (
                new_dir_path,  # 新前缀
                len(old_dir_path) + 1,
                self.task_id,
                old_dir_path + '/%'
            ))

            # 更新 target_path 以 old_dir_path/ 开头的记录
            cursor.execute('''
                UPDATE copy_records 
                SET target_path = ? || SUBSTR(target_path, ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ? 
                  AND target_path LIKE ?
            ''', (
                new_dir_path,
                len(old_dir_path) + 1,
                self.task_id,
                old_dir_path + '/%'
            ))

            conn.commit()

        except Exception as e:
            print(f"更新数据库目录路径失败: {e}")
            if conn:
                conn.rollback()
            raise  # 重新抛出，让上层处理
        finally:
            if conn:
                conn.close()
        pass

    @staticmethod
    def get_from_db(task_id: str, source_path: str = None, target_path: str = None) -> List[CopyRecord]:
        """
        从数据库查询复制记录
        
        Args:
            task_id: 任务 ID
            source_path: 源路径（可选）
            target_path: 目标路径（可选）
            
        Returns:
            List[CopyRecord]: 复制记录列表
        """
        records = []
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row  # 使结果集可以通过列名访问
            cursor = conn.cursor()
            
            # 构建查询条件
            query = '''
            SELECT id, task_id, source_path, target_path, is_copied, is_dir, staging_path
            FROM copy_records
            WHERE task_id = ?
            '''
            params = [task_id]
            
            if source_path:
                query += ' AND source_path = ?'
                params.append(source_path)
            
            if target_path:
                query += ' AND target_path = ?'
                params.append(target_path)
            
            # 执行查询
            cursor.execute(query, params)
            
            # 转换为 CopyRecord 对象
            for row in cursor.fetchall():
                record = CopyRecord(
                    task_id=row['task_id'],
                    source_path=row['source_path'],
                    target_path=row['target_path'],
                    is_copied=bool(row['is_copied']),
                    is_dir=bool(row['is_dir']),
                    staging_path=row['staging_path']
                )
                # 添加 id 属性，用于后续更新操作
                record.id = row['id']
                records.append(record)
        except Exception as e:
            print(f"查询复制记录失败: {e}")
        finally:
            if conn:
                conn.close()
        
        return records

    def load(self, task_id: str):
        """
        从数据库加载复制记录到缓存
        
        Args:
            task_id: 任务 ID
        """
        # 清空当前缓存
        self.clear()  # TODO 检测缓存不为空就报错
        self.task_id = task_id

        # 从数据库加载记录
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row  # 使结果集可以通过列名访问
            cursor = conn.cursor()
            
            # 查询所有该任务的复制记录
            cursor.execute('''
            SELECT source_path, target_path, is_copied, is_dir
            FROM copy_records
            WHERE task_id = ?
            ''', (task_id,))
            
            # 处理加载的记录
            for row in cursor.fetchall():
                source_path = row['source_path']
                target_path = row['target_path']
                is_copied = bool(row['is_copied'])
                is_dir = bool(row['is_dir'])
                
                if is_dir:
                    # 处理目录映射
                    self.dir_mapping[source_path] = target_path
                else:
                    # 处理文件复制记录
                    # 更新 registered_num
                    self.registered_num[source_path] = self.registered_num.get(source_path, 0) + 1
                    # 更新 copied_num
                    if is_copied:
                        self.copied_num[source_path] = self.copied_num.get(source_path, 0) + 1
        except Exception as e:
            print(f"加载复制记录失败: {e}")
        finally:
            if conn:
                conn.close()

    def clear(self):
        """清空缓存"""
        self.task_id = None
        self.copied_num.clear()
        self.registered_num.clear()
        self.dir_mapping.clear()
        self.dir_copy_done.clear()

