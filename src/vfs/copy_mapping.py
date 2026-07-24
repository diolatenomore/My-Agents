from dataclasses import dataclass
from typing import Optional, Dict, List
import os

import aiosqlite

from src.db.sqlite_pool import db_pool
from src.vfs.staging_area import StagingArea
from src.utils.vfs import copy
from src.utils.common import logger


@dataclass
class CopyRecord:
    task_id: str  #  任务id
    source_path: str  #  源路径
    target_path: str  #  目标路径
    is_copied: bool = False  #  该条记录是否已完成复制
    is_dir: bool = False  # 是否是目录操作
    staging_path: Optional[str] = None  #  暂存区路径


class CopyMapping:
    """复制映射类，用于存储复制记录（实例化，每个 task 独立一份）"""

    def __init__(self, task_id: str, staging_area: StagingArea):
        self.task_id: str = task_id
        self._staging_area = staging_area  # 同一 task 的 StagingArea 实例引用
        self.registered_num: Dict[str, int] = {}  # 记录某个文件作为source_path的次数
        self.copied_num: Dict[str, int] = {}  # 记录某个文件作为source_path已被拷贝的次数
        self.dir_mapping: Dict[str, str] = {}  # 记录从source_path到target_path的目录映射关系
        self.dir_copy_done: Dict[str, List[str]] = {}  # 记录某个目录已被拷贝的子文件路径
        # 反向映射（target → source），用于审批阶段反查 copy/move 来源
        self.file_reverse: Dict[str, str] = {}  # target_path -> source_path
        self.dir_reverse: Dict[str, str] = {}  # target_dir -> source_dir

    async def register(self, source_path: str, target_path: str, _conn: aiosqlite.Connection):
        """注册复制记录"""
        # 更新缓存
        self.registered_num[source_path] = self.registered_num.get(source_path, 0) + 1
        self.file_reverse[target_path] = source_path

        # 写入到数据库
        try:
            await _conn.execute(
                "INSERT INTO copy_records (task_id, source_path, target_path, is_copied, is_dir) VALUES (?, ?, ?, ?, ?)",
                (self.task_id, source_path, target_path, 0, False),
            )
        except Exception as e:
            logger.error(f"写入复制记录失败: {e}")
        logger.debug(f"注册文件复制记录，从{source_path}到{target_path}")

    async def register_dir(self, source_path: str, target_path: str, _conn: aiosqlite.Connection):
        """注册目录映射"""
        self.dir_mapping[source_path] = target_path
        self.dir_reverse[target_path] = source_path

        # 写入到数据库
        try:
            await _conn.execute(
                "INSERT INTO copy_records (task_id, source_path, target_path, is_copied, is_dir) VALUES (?, ?, ?, ?, ?)",
                (self.task_id, source_path, target_path, 0, True),
            )
        except Exception as e:
            logger.error(f"写入目录复制记录失败: {e}")
        logger.debug(f"注册目录复制记录，从{source_path}到{target_path}")

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

    async def mark_copied(self, source_path: str, _conn: aiosqlite.Connection):
        """
        拷贝所有未被拷贝的文件并修改标记
        :param _conn: 审批阶段注入的数据库连接，用于保持同一事务
        """
        records = await self.get_from_db(task_id=self.task_id, source_path=source_path)
        # 如果原文件有暂存区路径则使用
        source_staging_path = self._staging_area.mapping.get(source_path)  # 直接获取路径，不判断是否被删除
        path = source_staging_path if source_staging_path else source_path

        # 处理精确拷贝情况（source_path作为copy_file操作的原路径）
        update_ids = []
        for record in records:
            if not record.is_copied:
                target_staging_path = self._staging_area.get_staging_path(record.target_path)
                if not os.path.exists(target_staging_path):
                    # 拷贝文件
                    copy(path, target_staging_path)
                # 更新缓存
                self.copied_num[source_path] = self.copied_num.get(source_path, 0) + 1
                update_ids.append(record.id)

        # 更新数据库
        if update_ids:
            try:
                # 更新数据库，标记该条记录已完成复制
                for update_id in update_ids:
                    await _conn.execute(
                        "UPDATE copy_records SET is_copied = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (update_id,),
                    )
            except Exception as e:
                logger.error(f"标记复制完成失败: {e}")

        # 处理目录拷贝情况（copy_dir操作的原路径作为source_path的前缀）
        for dir_path in self.dir_mapping.keys():
            if source_path.startswith(dir_path + "/") and source_path not in self.dir_copy_done.get(dir_path, []):
                # 计算目标路径
                target_path = self.dir_mapping[dir_path] + source_path[len(dir_path):]
                target_staging_path = self._staging_area.get_staging_path(target_path)
                if not os.path.exists(target_staging_path):
                    # 拷贝文件
                    copy(path, target_staging_path)
                # 标记该该文件已完成对应的目录拷贝
                self.dir_copy_done.setdefault(dir_path, []).append(source_path)

        logger.debug(f"文件{source_path}发生修改，触发拷贝")

    def need_copied_dir(self, source_path: str) -> bool:
        """判断目录是否需要被拷贝"""
        return source_path in self.dir_mapping.keys()

    async def mark_copied_dir(self, source_path: str, _conn: aiosqlite.Connection):
        """
        拷贝所有该目录下的未被拷贝的文件并修改标记
        :param _conn: 审批阶段注入的数据库连接，用于保持同一事务
        """
        # 拷贝目录下的所有文件和子目录至暂存区
        target_path = self.dir_mapping[source_path]  # 目标目录完整路径
        for root, dirs, files in os.walk(source_path):
        # root: 当前遍历目录的完整路径      dirs: 当前目录下的子目录列表    files: 当前目录下的文件列表
            for file_name in files:
                # 构造目标文件完整路径
                source_file = os.path.join(root, file_name)         # 原文件完整路径
                target_file = source_file.replace(source_path, target_path, 1)  # 目标文件完整路径

                target_staging_path = self._staging_area.get_staging_path(target_file)
                # 如果暂存区路径不真实存在则拷贝文件到暂存区
                if not os.path.exists(target_staging_path):
                    # 如果原文件有暂存区路径则使用
                    source_staging_path = self._staging_area.mapping.get(source_file)  # 直接获取路径，不判断是否被删除
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

        try:
            # 更新所有目录复制记录，标记为已完成复制
            for dir_path in dir_paths_to_update:
                await _conn.execute(
                    "UPDATE copy_records SET is_copied = 1, updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND source_path = ? AND is_dir = 1",
                    (self.task_id, dir_path),
                )
        except Exception as e:
            logger.error(f"标记目录复制完成失败: {e}")

        logger.debug(f"目录{source_path}发生修改，触发拷贝")

    async def copy_if_need(self, target_path: str, _conn: aiosqlite.Connection):
        """
        判断target_path是否需要拷贝，如果是，拷贝并修改标记。
        :param _conn: 审批阶段注入的数据库连接，用于保持同一事务
        """
        # 如果暂存区路径在文件系统中实际已存在
        target_staging_path = self._staging_area.get_staging_path(target_path)
        if os.path.exists(target_staging_path):
            return

        # 判断是否为精确拷贝（target_path作为copy_file操作的目标路径）
        source_path = self.file_reverse.get(target_path)
        if source_path is not None:
            # 已拷贝，跳过
            if self.copied_num.get(source_path, 0) >= self.registered_num.get(source_path, 0):
                return

            # 如果原文件有暂存区路径则使用
            staging_path_source = self._staging_area.mapping.get(source_path)  # 直接获取路径，不判断是否被删除
            path = staging_path_source if staging_path_source else source_path

            copy(path, target_staging_path)
            logger.info(f"拷贝文件{source_path}到{target_path}")

            # 标记source_path已被拷贝一次
            self.copied_num[source_path] = self.copied_num.get(source_path, 0) + 1

            # 更新数据库中的字段
            try:
                # 更新数据库，标记该条记录已完成复制
                await _conn.execute(
                    "UPDATE copy_records SET is_copied = 1, updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND target_path = ? AND is_copied = 0",
                    (self.task_id, target_path),
                )
            except Exception as e:
                logger.error(f"标记复制完成失败: {e}")

        # 判断是否为目录拷贝（target_path作为copy_dir操作的目标路径）
        else:
            for dir_source_path, dir_target_path in self.dir_mapping.items():
                if target_path.startswith(dir_target_path + "/"):
                    # 计算源路径
                    source_path = dir_source_path + target_path[len(dir_target_path):]
                    # 已拷贝，结束
                    if source_path in self.dir_copy_done.get(dir_source_path, []):
                        break

                    if not os.path.exists(target_staging_path):
                        # 如果原文件有暂存区路径则使用
                        staging_path_source = self._staging_area.mapping.get(source_path)  # 直接获取路径，不判断是否被删除
                        path = staging_path_source if staging_path_source else source_path
                        # 拷贝文件
                        copy(path, target_staging_path)
                        logger.info(f"拷贝文件{source_path}到{target_path}")
                    # 标记source_path文件已完成对应的目录拷贝
                    self.dir_copy_done.setdefault(dir_source_path, []).append(source_path)
                    # 结束
                    break

    async def rename(self, old_path: str, new_path: str, _conn: aiosqlite.Connection):
        """修改映射"""

        # 如果old_path作为source_path，则更新缓存
        if old_path in self.copied_num:
            self.copied_num[new_path] = self.copied_num[old_path]
            self.registered_num[new_path] = self.registered_num[old_path]
            self.copied_num.pop(old_path, None)
            self.registered_num.pop(old_path, None)

        # 如果old_path作为target_path，则更新缓存
        if old_path in self.file_reverse:
            self.file_reverse[new_path] = self.file_reverse.pop(old_path)

        # 更新数据库，把old_path（source_path/target_path）替换为new_path
        try:
            # 更新原路径为old_path的记录
            await _conn.execute(
                "UPDATE copy_records SET source_path = ?, updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND source_path = ?",
                (new_path, self.task_id, old_path),
            )
            # 更新目标路径为old_path的记录
            await _conn.execute(
                "UPDATE copy_records SET target_path = ?, updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND target_path = ?",
                (new_path, self.task_id, old_path),
            )
        except Exception as e:
            logger.error(f"更新复制记录路径失败: {e}")

        logger.debug(f"修改文件复制映射，从{old_path}到{new_path}")

    async def rename_dir(self, old_dir_path: str, new_dir_path: str, _conn: aiosqlite.Connection):
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

        # 1b. 从 dir_mapping 重建 dir_reverse
        self.dir_reverse = {v: k for k, v in self.dir_mapping.items()}

        # 1c. 维护 file_reverse 中受目录重命名影响的 key 和 value（前缀替换）
        for target_path in list(self.file_reverse.keys()):
            source_path = self.file_reverse[target_path]
            new_key = target_path
            new_value = source_path
            # key（target_path）以 old_dir_path 为前缀
            if target_path.startswith(old_dir_path + "/"):
                new_key = new_dir_path + target_path[len(old_dir_path):]
            # value（source_path）以 old_dir_path 为前缀
            if source_path.startswith(old_dir_path + "/"):
                new_value = new_dir_path + source_path[len(old_dir_path):]
            if new_key != target_path or new_value != source_path:
                self.file_reverse.pop(target_path)
                self.file_reverse[new_key] = new_value

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
                self.dir_copy_done.pop(old_dir_path, None)

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
        try:
            # 情况 A：更新目录本身（is_dir = 1 且路径完全匹配）
            # 更新 source_path 匹配的记录
            await _conn.execute(
                "UPDATE copy_records SET source_path = ?, updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND source_path = ? AND is_dir = 1",
                (new_dir_path, self.task_id, old_dir_path),
            )
            # 更新 target_path 匹配的记录
            await _conn.execute(
                "UPDATE copy_records SET target_path = ?, updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND target_path = ? AND is_dir = 1",
                (new_dir_path, self.task_id, old_dir_path),
            )
            # 情况 B：更新子内容（以 old_dir_path/ 为前缀的文件和子目录）
            # 使用 SUBSTR 保留原路径的后缀部分
            # 更新 source_path 以 old_dir_path/ 开头的记录
            await _conn.execute(
                "UPDATE copy_records SET source_path = ? || SUBSTR(source_path, ?), updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND source_path LIKE ?",
                (new_dir_path, len(old_dir_path) + 1, self.task_id, old_dir_path + "/%"),
            )
            # 更新 target_path 以 old_dir_path/ 开头的记录
            await _conn.execute(
                "UPDATE copy_records SET target_path = ? || SUBSTR(target_path, ?), updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND target_path LIKE ?",
                (new_dir_path, len(old_dir_path) + 1, self.task_id, old_dir_path + "/%"),
            )
        except Exception as e:
            logger.error(f"更新数据库目录路径失败: {e}")

        logger.error(f"修改目录复制映射，从{old_dir_path}到{new_dir_path}")

    @staticmethod
    async def get_from_db(task_id: str, source_path: str = None, target_path: str = None) -> List[CopyRecord]:
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
        try:
            async with db_pool.get_conn() as conn:
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

                cursor = await conn.execute(query, params)
                for row in await cursor.fetchall():
                    record = CopyRecord(
                        task_id=row['task_id'],
                        source_path=row['source_path'],
                        target_path=row['target_path'],
                        is_copied=bool(row['is_copied']),
                        is_dir=bool(row['is_dir']),
                        staging_path=row['staging_path']
                    )
                    record.id = row['id']
                    records.append(record)
        except Exception as e:
            logger.error(f"查询复制记录失败: {e}")

        return records

    async def load(self):
        """从数据库加载记录"""
        # 从数据库加载记录
        try:
            async with db_pool.get_conn() as conn:
                cursor = await conn.execute(
                    "SELECT source_path, target_path, is_copied, is_dir FROM copy_records WHERE task_id = ?",
                    (self.task_id,),
                )
                for row in await cursor.fetchall():
                    source_path = row["source_path"]
                    target_path = row["target_path"]
                    is_copied = bool(row["is_copied"])
                    is_dir = bool(row["is_dir"])

                    if is_dir:
                        self.dir_mapping[source_path] = target_path
                        self.dir_reverse[target_path] = source_path
                    else:
                        self.registered_num[source_path] = self.registered_num.get(source_path, 0) + 1
                        self.file_reverse[target_path] = source_path
                        if is_copied:
                            self.copied_num[source_path] = self.copied_num.get(source_path, 0) + 1
        except Exception as e:
            logger.error(f"加载复制记录失败: {e}")

        logger.info(f"加载CopyMapping记录成功，任务 ID: {self.task_id}")

    def get_copy_source(self, path: str) -> Optional[str]:
        """
        根据目标路径反查原始来源路径。
        返回 None 表示该文件并非来自 copy/move 操作。
        """
        # 1. 精确文件匹配
        if path in self.file_reverse:
            return self.file_reverse[path]
        # 2. 目录前缀匹配（被 copy_dir/move_dir 覆盖的子文件）
        for target_dir, source_dir in self.dir_reverse.items():
            if path.startswith(target_dir + "/"):
                return source_dir + path[len(target_dir):]
        return None

    def clear(self):
        """清空缓存"""
        self.registered_num.clear()
        self.copied_num.clear()
        self.dir_mapping.clear()
        self.dir_copy_done.clear()
        self.file_reverse.clear()
        self.dir_reverse.clear()
        logger.info(f"CopyMapping清空成功, task_id={self.task_id}")
