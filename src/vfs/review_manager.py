"""VFS 审批管理器

负责：
1. 将 merge 结果构建为前端树形结构，同时持久化到 review_items 表
2. 返回审批列表给前端
3. 处理审批（通过/拒绝），清理 VFS 状态
"""

import os
import shutil
import uuid
from typing import Optional

from src.config import STAGING_AREA_PATH
from src.db.sqlite_pool import db_pool
from src.vfs.diff_table import DiffTable, OperationType
from src.vfs.task_context import get_copy_mapping, get_staging_area
from src.utils.common import logger


class ReviewManager:

    @staticmethod
    async def build_review_tree(task_id: str) -> Optional[dict]:
        """
        获取未审批的 diff_records → merge → 遍历 OperationTree：
          - 同时构建前端树形结构和 DB 行数据
          - 写入 review_items 表
          - 标记 diff_records 已处理

        返回前端树形结构；无新操作则返回 None。
        """
        # 1. 获取未审批记录
        records = await DiffTable.list(task_id)
        if not records:
            return None

        # 2. merge
        tree = DiffTable.merge(records)
        if tree is None:
            # 全部抵消，标记已审批
            await DiffTable.mark_reviewed(task_id)
            return None

        # 3. 获取 copy_mapping（用于补 copy_source）
        copy_mapping = get_copy_mapping()


        # 4. 遍历 OperationTree，同时产出前端树和 DB 行
        root_items = []
        db_rows = []

        def _walk(node, parent_node: Optional[dict] = None):
            """parent_node: 前端树中的父节点（dict），None 表示 root"""
            dir_item = None

            # 目录操作
            if node.dir_operation:
                op = node.dir_operation
                item_id = str(uuid.uuid4())
                dir_item = {
                    'id': item_id,
                    'op_type': op.operation_type.value,
                    'source': op.source_path,
                    'target': op.target_path or '',
                    'copy_source': '',
                    'status': 'pending',
                }
                db_rows.append((item_id, task_id,
                                parent_node['id'] if parent_node else None,
                                op.operation_type.value, op.source_path, op.target_path, None))
                # 挂到父节点
                if parent_node:
                    parent_node.setdefault('children', []).append(dir_item)
                else:
                    root_items.append(dir_item)
            else:
                item_id = None

            # 文件操作：父节点为 dir_item（如果有）否则为 parent_node
            effective_parent = dir_item or parent_node
            if node.file_operations:
                for file_path, ops in node.file_operations.items():
                    for op in ops:
                        fid = str(uuid.uuid4())
                        copy_src = None
                        if op.operation_type == OperationType.CREATE_FILE:
                            copy_src = copy_mapping.get_copy_source(file_path)
                        file_item = {
                            'id': fid,
                            'op_type': op.operation_type.value,
                            'source': op.source_path,
                            'target': op.target_path or '',
                            'copy_source': copy_src or '',
                            'status': 'pending',
                        }
                        if effective_parent:
                            effective_parent.setdefault('children', []).append(file_item)
                        else:
                            root_items.append(file_item)
                        db_rows.append((fid, task_id,
                                        effective_parent['id'] if effective_parent else None,
                                        op.operation_type.value, op.source_path, op.target_path, copy_src))

            # 递归子目录：传入 dir_item 作为父节点
            if node.sub_groups:
                for _, child in node.sub_groups.items():
                    _walk(child, dir_item)

        _walk(tree)

        # TODO 需要考虑上一次的未审批完的情况
        # 5. 写入 review_items 表
        try:
            async with db_pool.get_conn() as conn:
                await conn.executemany(
                    """INSERT OR REPLACE INTO review_items 
                       (id, task_id, parent_id, op_type, source, target, copy_source)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    db_rows,
                )
        except Exception as e:
            logger.error(f"写入 review_items 失败: {e}")
            return None

        logger.info(f"已为 task_id={task_id} 创建 {len(db_rows)} 条审批项")
        return {'task_id': task_id, 'items': root_items}

    @staticmethod
    async def get_review_tree(task_id: str) -> Optional[dict]:
        """
        从 review_items 表查询，按 parent_id 构建树形结构返回前端。
        用于页面刷新时重新获取审批列表。
        """
        try:
            async with db_pool.get_conn() as conn:
                cursor = await conn.execute(
                    """SELECT id, parent_id, op_type, source, target, copy_source, status
                       FROM review_items WHERE task_id = ?
                       ORDER BY CASE WHEN parent_id IS NULL THEN 0 ELSE 1 END, created_at""",
                    (task_id,),
                )
                rows = await cursor.fetchall()
        except Exception as e:
            logger.error(f"查询 review_items 失败: {e}")
            return None

        if not rows:
            return None

        lookup: dict = {}
        root_items = []

        for row in rows:
            item = {
                'id': row['id'],
                'op_type': row['op_type'],
                'source': row['source'],
                'target': row['target'] or '',
                'copy_source': row['copy_source'] or '',
                'status': row['status'],
            }
            lookup[row['id']] = item

            parent_id = row['parent_id'] or ''
            if not parent_id:
                root_items.append(item)
            else:
                parent = lookup.get(parent_id)
                if parent:
                    parent.setdefault('children', []).append(item)

        return {'task_id': task_id, 'items': root_items}

    @staticmethod
    async def process_review(task_id: str, approved: bool):
        """
        全部通过/拒绝：遍历所有 pending 项，逐条执行。
        通过 = 执行真实文件操作 + 清理 VFS 状态
        拒绝 = 仅清理 VFS 状态
        """
        # 1. 加载审批项
        try:
            async with db_pool.get_conn() as conn:
                cursor = await conn.execute(
                    "SELECT id FROM review_items WHERE task_id = ? AND status = 'pending'",
                    (task_id,),
                )
                rows = await cursor.fetchall()
        except Exception as e:
            logger.error(f"加载审批项失败: {e}")
            return

        if not rows:
            logger.warning(f"task_id={task_id} 无待审批项")
            return

        for row in rows:
            await ReviewManager.process_single_item(task_id, row['id'], approved)

        logger.info(f"task_id={task_id} 全部审批完成, approved={approved}")

    @staticmethod
    async def process_single_item(task_id: str, item_id: str, approved: bool):
        """
        处理单条审批的核心逻辑。
        """
        staging_area = get_staging_area()
        copy_mapping = get_copy_mapping()
        # 在事务内进行
        try:
            async with db_pool.get_conn() as conn:
                # 1. 查 item
                cursor = await conn.execute(
                    "SELECT id, parent_id, op_type, source, target, status "
                    "FROM review_items WHERE id = ?",
                    (item_id,),
                )
                row = await cursor.fetchone()
                if not row:
                    logger.warning(f"审批项 {item_id} 不存在")
                    return
                if row['status'] != 'pending':
                    logger.warning(f"审批项 {item_id} 已处理")
                    return

                parent_id = row['parent_id']
                op_type = row['op_type']
                source = row['source']
                target = row['target']

                # 2. 级联处理父级 TODO 改为调用递归函数，并注入conn
                if parent_id:
                    p_cursor = await conn.execute(
                        "SELECT id, op_type, source, target, status "
                        "FROM review_items WHERE id = ?",
                        (parent_id,),
                    )
                    parent_row = await p_cursor.fetchone()

                    if parent_row and parent_row['status'] == 'pending':
                        p_op = parent_row['op_type']
                        p_source = parent_row['source']
                        p_target = parent_row['target']

                        # 父级 DB 外的操作需在事务内尽早执行
                        if approved:
                            await ReviewManager._do_write_copy_checks(copy_mapping, p_op, p_source)
                            await ReviewManager._apply_operation(p_op, p_source, p_target)

                        await ReviewManager._clean_vfs_state(
                            conn, task_id, p_op, p_source, p_target, True, staging_area)
                        await conn.execute(
                            "UPDATE review_items SET status = 'approved' WHERE id = ?",
                            (parent_id,),
                        )

                # 3. 通过时：检查写时复制 → 执行真实文件操作
                if approved:
                    await ReviewManager._do_write_copy_checks(copy_mapping, op_type, source)
                    await ReviewManager._apply_operation(op_type, source, target)

                # 4. 清理 VFS 状态
                await ReviewManager._clean_vfs_state(
                    conn, task_id, op_type, source, target, approved, staging_area)

                # 5. 更新 review_items.status
                new_status = 'approved' if approved else 'rejected'
                await conn.execute(
                    "UPDATE review_items SET status = ? WHERE id = ?",
                    (new_status, item_id),
                )

                logger.info(f"审批项 {item_id} [{op_type} {source}] → {new_status}")
        except Exception as e:
            logger.error(f"处理审批项失败: {e}")


    @staticmethod
    async def _do_write_copy_checks(copy_mapping, op_type: str, path: str):
        """根据操作类型检查并触发写时复制"""
        # TODO 待确认
        if op_type in ('CREATE_FILE', 'MODIFY_FILE'):
            await copy_mapping.copy_if_need(path)
        if op_type in ('MODIFY_FILE', 'DELETE_FILE'):
            if copy_mapping.need_copied(path):
                await copy_mapping.mark_copied(path)
        if op_type == 'DELETE_DIR':
            if copy_mapping.need_copied_dir(path):
                await copy_mapping.mark_copied_dir(path)

    @staticmethod
    async def _apply_operation(op_type: str, source: str, target: str):
        """执行真实文件系统操作"""
        # TODO 待确认
        try:
            if op_type == 'MKDIR':
                os.makedirs(source, exist_ok=True)
            elif op_type == 'CREATE_FILE':
                staging_path = ReviewManager._resolve_staging_path(source)
                if staging_path and os.path.exists(staging_path):
                    os.makedirs(os.path.dirname(source), exist_ok=True)
                    shutil.copy(staging_path, source)
            elif op_type == 'MODIFY_FILE':
                staging_path = ReviewManager._resolve_staging_path(source)
                if staging_path and os.path.exists(staging_path):
                    shutil.copy(staging_path, source)
            elif op_type == 'DELETE_FILE':
                if os.path.exists(source):
                    os.remove(source)
            elif op_type == 'RENAME_FILE':
                if os.path.exists(source):
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    os.rename(source, target)
            elif op_type == 'DELETE_DIR':
                if os.path.exists(source):
                    shutil.rmtree(source)
            elif op_type == 'RENAME_DIR':
                if os.path.exists(source):
                    os.rename(source, target)
        except Exception as e:
            logger.error(f"执行真实文件操作失败 [{op_type} {source}]: {e}")

    @staticmethod
    def _resolve_staging_path(source: str) -> Optional[str]:
        """根据源路径推断暂存区路径"""
        try:
            staging = get_staging_area()
            return staging.get_staging_path(source)
        except RuntimeError:
            pass
        return None

    @staticmethod
    async def _clean_vfs_state(conn, task_id: str, op_type: str, source: str,
                               target: str, approved: bool, staging):
        """清理该路径相关的 VFS 状态：diff_records + staging_records + copy_records + 磁盘文件

        Args:
            conn:      数据库连接（从外层事务注入）
            task_id:   任务 ID
            op_type:   操作类型
            source:    source_path
            target:    target_path（rename 时使用）
            approved:  True=通过, False=拒绝
            staging:   StagingArea 实例（可选）
        """
        # 1. 清理 diff_records
        if op_type in ('RENAME_FILE', 'RENAME_DIR'):
            rename_cursor = await conn.execute(
                "SELECT id, created_at FROM diff_records "
                "WHERE task_id = ? AND operation_type = ? AND source_path = ? AND is_reviewed = 0",
                (task_id, op_type, source),
            )
            rename_row = await rename_cursor.fetchone()
            if rename_row:
                if approved:
                    # 通过：rename 之前的操作 source_path 改为 target_path
                    if op_type == 'RENAME_FILE':
                        # 精确匹配
                        await conn.execute(
                            "UPDATE diff_records SET source_path = ? "
                            "WHERE task_id = ? AND is_reviewed = 0 "
                            "AND source_path = ? AND created_at < ?",
                            (target, task_id, source, rename_row['created_at']),
                        )
                    else:
                        # 前缀匹配
                        await conn.execute(
                            "UPDATE diff_records SET source_path = ? || SUBSTR(source_path, ?) "
                            "WHERE task_id = ? AND is_reviewed = 0 "
                            "AND source_path LIKE ? AND created_at < ?",
                            (target, len(source) + 1, task_id,
                             source + "/%", rename_row['created_at']),
                        )
                else:
                    # 拒绝：rename 之后的操作 source_path 回退
                    if op_type == 'RENAME_FILE':
                        # 精确匹配
                        await conn.execute(
                            "UPDATE diff_records SET source_path = ? "
                            "WHERE task_id = ? AND is_reviewed = 0 "
                            "AND source_path = ? AND created_at > ?",
                            (source, task_id, target, rename_row['created_at']),
                        )
                    else:
                        # 前缀匹配
                        await conn.execute(
                            "UPDATE diff_records SET source_path = ? || SUBSTR(source_path, ?) "
                            "WHERE task_id = ? AND is_reviewed = 0 "
                            "AND source_path LIKE ? AND created_at > ?",
                            (source, len(target) + 1, task_id,
                             target + "/%", rename_row['created_at']),
                        )
                # 标记 rename 自身
                await conn.execute(
                    "UPDATE diff_records SET is_reviewed = 1 WHERE id = ?",
                    (rename_row['id'],),
                )
        else:
            await conn.execute(
                "UPDATE diff_records SET is_reviewed = 1 "
                "WHERE task_id = ? AND source_path = ? AND is_reviewed = 0",
                (task_id, source),
            )

        # 2. copy_records（可能作为 source 或 target）
        await conn.execute(
            "DELETE FROM copy_records WHERE task_id = ? AND (source_path = ? OR target_path = ?)",
            (task_id, source, source),
        )

        # 3. 磁盘 staging 文件
        if staging:
            staging_path = staging.get_staging_path(source)
            if staging_path and os.path.exists(staging_path):
                try:
                    os.remove(staging_path)
                except Exception as e:
                    logger.error(f"删除暂存区文件失败 {staging_path}: {e}")

        # 4. staging_records
        await conn.execute(
            "DELETE FROM staging_records WHERE task_id = ? AND path = ?",
            (task_id, source),
        )

