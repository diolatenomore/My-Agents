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

        # 5. 写入 review_items 表
        try:
            async with db_pool.get_conn() as conn:
                # 先清理旧的 pending 项，避免重复
                await conn.execute(
                    "DELETE FROM review_items WHERE task_id = ? AND status = 'pending'",
                    (task_id,),
                )
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
                    """SELECT id, parent_id, op_type, source, target, copy_source
                       FROM review_items WHERE task_id = ? AND status = 'pending'
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
        try:
            async with db_pool.get_conn() as conn:
                # 1. 查 item
                cursor = await conn.execute(
                    "SELECT id, parent_id, op_type, source, target "
                    "FROM review_items WHERE id = ? AND status = 'pending'",
                    (item_id,),
                )
                row = await cursor.fetchone()
                if not row:
                    logger.warning(f"审批项 {item_id} 已处理或不存在")
                    return

                parent_id = row['parent_id']
                op_type = row['op_type']
                source = row['source']
                target = row['target']

                # 2a. 通过时级联通过父操作和rename操作
                if approved:
                    if parent_id:
                        await ReviewManager._cascade_approve_parents(conn, task_id, parent_id)
                    # 判断是否有 target == source 的 rename 操作，有则先通过
                    rename_cursor = await conn.execute(
                        "SELECT id, op_type, source, target FROM review_items "
                        "WHERE task_id = ? AND op_type = 'RENAME_FILE'"
                        "AND target = ? AND status = 'pending'",
                        (task_id, source),
                    )
                    rename_row = await rename_cursor.fetchone()
                    if rename_row:
                        r_op = rename_row['op_type']
                        r_source = rename_row['source']
                        r_target = rename_row['target']
                        await ReviewManager._apply_operation(r_op, r_source, r_target)
                        await ReviewManager._clean_rename_diff_records(
                            conn, task_id, r_op, r_source, r_target, True)
                        await conn.execute(
                            "UPDATE review_items SET status = 'approved' WHERE id = ?",
                            (rename_row['id'],),
                        )

                # 2b. 拒绝目录操作时级联拒绝子操作
                if not approved and op_type in ('MKDIR', 'RENAME_DIR', 'DELETE_DIR'):
                    await ReviewManager._cascade_reject_children(conn, task_id, item_id)

                # 3. 通过时：检查写时复制 → 执行真实文件操作
                if approved:
                    await ReviewManager._do_write_copy_checks(conn, op_type, source)
                    await ReviewManager._apply_operation(op_type, source, target)

                # 4. 清理 VFS 状态
                await ReviewManager._clean_vfs_state(
                    conn, task_id, op_type, source, target, approved)

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
    async def _cascade_approve_parents(conn, task_id: str, parent_id: str):
        """递归执行父级审批链（仅通过时调用）。先处理更上级的祖先，再处理当前父级。"""
        cursor = await conn.execute(
            "SELECT id, parent_id, op_type, source, target "
            "FROM review_items WHERE id = ? AND status = 'pending'",
            (parent_id,),
        )
        parent_row = await cursor.fetchone()
        if not parent_row:
            return

        # 先递归处理祖父
        if parent_row['parent_id']:
            await ReviewManager._cascade_approve_parents(conn, task_id, parent_row['parent_id'])

        # 执行当前父级
        p_op = parent_row['op_type']
        p_source = parent_row['source']
        p_target = parent_row['target']

        await ReviewManager._do_write_copy_checks(conn, p_op, p_source)
        await ReviewManager._apply_operation(p_op, p_source, p_target)
        await ReviewManager._clean_vfs_state(
            conn, task_id, p_op, p_source, p_target, True)
        await conn.execute(
            "UPDATE review_items SET status = 'approved' WHERE id = ?",
            (parent_id,),
        )

    @staticmethod
    async def _cascade_reject_children(conn, task_id: str, parent_id: str):
        """拒绝目录操作时递归级联拒绝所有子孙操作。不执行 apply，仅清理 VFS + 标记 rejected。"""
        cursor = await conn.execute(
            "SELECT id, op_type, source, target FROM review_items "
            "WHERE parent_id = ? AND status = 'pending'",
            (parent_id,),
        )
        children = await cursor.fetchall()
        for child in children:
            # 先递归处理子节点的子节点
            await ReviewManager._cascade_reject_children(conn, task_id, child['id'])
            # 清理 VFS
            await ReviewManager._clean_vfs_state(
                conn, task_id, child['op_type'],
                child['source'], child['target'], False)
            await conn.execute(
                "UPDATE review_items SET status = 'rejected' WHERE id = ?",
                (child['id'],),
            )

    @staticmethod
    async def _do_write_copy_checks(conn, op_type: str, path: str):
        """根据操作类型检查并触发写时复制"""
        copy_mapping = get_copy_mapping()
        if op_type in ('CREATE_FILE', 'MODIFY_FILE'):
            await copy_mapping.copy_if_need(path, _conn=conn)
        if op_type in ('MODIFY_FILE', 'DELETE_FILE'):
            if copy_mapping.need_copied(path):
                await copy_mapping.mark_copied(path, _conn=conn)
        if op_type == 'DELETE_DIR':
            if copy_mapping.need_copied_dir(path):
                await copy_mapping.mark_copied_dir(path, _conn=conn)

    @staticmethod
    async def _apply_operation(op_type: str, source: str, target: str):
        """执行真实文件系统操作"""
        # TODO 待确认
        try:
            if op_type == 'MKDIR':
                logger.info(f"[APPLY] MKDIR: {source}")
                # os.makedirs(source, exist_ok=True)
            elif op_type == 'CREATE_FILE':
                logger.info(f"[APPLY] CREATE_FILE: {source}")
                # staging_path = ReviewManager._resolve_staging_path(source)
                # if staging_path and os.path.exists(staging_path):
                #     os.makedirs(os.path.dirname(source), exist_ok=True)
                #     shutil.copy(staging_path, source)
            elif op_type == 'MODIFY_FILE':
                logger.info(f"[APPLY] MODIFY_FILE: {source}")
                # staging_path = ReviewManager._resolve_staging_path(source)
                # if staging_path and os.path.exists(staging_path):
                #     shutil.copy(staging_path, source)
            elif op_type == 'DELETE_FILE':
                logger.info(f"[APPLY] DELETE_FILE: {source}")
                # if os.path.exists(source):
                #     os.remove(source)
            elif op_type == 'RENAME_FILE':
                logger.info(f"[APPLY] RENAME_FILE: {source} -> {target}")
                # if os.path.exists(source):
                #     os.makedirs(os.path.dirname(target), exist_ok=True)
                #     os.rename(source, target)
            elif op_type == 'DELETE_DIR':
                logger.info(f"[APPLY] DELETE_DIR: {source}")
                # if os.path.exists(source):
                #     shutil.rmtree(source)
            elif op_type == 'RENAME_DIR':
                logger.info(f"[APPLY] RENAME_DIR: {source} -> {target}")
                # if os.path.exists(source):
                #     os.rename(source, target)
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
    async def _clean_rename_diff_records(conn, task_id: str, op_type: str,
                                         source: str, target: str, approved: bool):
        """清理 rename 的 diff_records，拒绝时同步回退 staging_area 和 copy_mapping

        拒绝 rename 时，staging_area 和 copy_mapping 中原先已记录了 rename 的影响，
        需反向调用 rename/rename_dir 将路径恢复为原值。
        """
        rename_cursor = await conn.execute(
            "SELECT id, created_at FROM diff_records "
            "WHERE task_id = ? AND operation_type = ? AND source_path = ? AND is_reviewed = 0",
            (task_id, op_type, source),
        )
        rename_row = await rename_cursor.fetchone()
        if not rename_row:
            return

        if not approved:
            if op_type == 'RENAME_FILE':
                # diff_records：rename 之后引用 target 的 source_path 回退为 source
                await conn.execute(
                    "UPDATE diff_records SET source_path = ? "
                    "WHERE task_id = ? AND is_reviewed = 0 "
                    "AND source_path = ? AND created_at > ?",
                    (source, task_id, target, rename_row['created_at']),
                )
                # staging_area / copy_mapping 回退
                staging_area = get_staging_area()
                await staging_area.rename(target, source, conn)
                copy_mapping = get_copy_mapping()
                await copy_mapping.rename(target, source, conn)
            else:
                # diff_records：source_path / target_path 前缀为 target 的改回 source
                await conn.execute(
                    "UPDATE diff_records SET source_path = ? || SUBSTR(source_path, ?) "
                    "WHERE task_id = ? AND is_reviewed = 0 AND operation_type != ? "
                    "AND (source_path = ? OR source_path LIKE ? || '/%') "
                    "AND created_at > ?",
                    (source, len(target) + 1, task_id, OperationType.RENAME_DIR.value,
                     target, target, rename_row['created_at']),
                )
                await conn.execute(
                    "UPDATE diff_records SET target_path = ? || SUBSTR(target_path, ?) "
                    "WHERE task_id = ? AND is_reviewed = 0 "
                    "AND target_path IS NOT NULL AND operation_type != ? "
                    "AND (target_path = ? OR target_path LIKE ? || '/%') "
                    "AND created_at > ?",
                    (source, len(target) + 1, task_id, OperationType.RENAME_DIR.value,
                     target, target, rename_row['created_at']),
                )
                # staging_area / copy_mapping 回退
                staging_area = get_staging_area()
                await staging_area.rename_dir(target, source, conn)
                copy_mapping = get_copy_mapping()
                await copy_mapping.rename_dir(target, source, conn)

        # 标记 rename 自身为已审批
        await conn.execute(
            "UPDATE diff_records SET is_reviewed = 1 WHERE id = ?",
            (rename_row['id'],),
        )

    @staticmethod
    async def _clean_vfs_state(conn, task_id: str, op_type: str, source: str,
                               target: str, approved: bool):
        """清理该路径相关的 VFS 状态：diff_records + staging_records + copy_records + 磁盘文件

        Args:
            conn:      数据库连接（从外层事务注入）
            task_id:   任务 ID
            op_type:   操作类型
            source:    source_path
            target:    target_path（rename 时使用）
            approved:  True=通过, False=拒绝
        """
        # 1. 清理 diff_records
        if op_type in ('RENAME_FILE', 'RENAME_DIR'):
            await ReviewManager._clean_rename_diff_records(conn, task_id, op_type, source, target, approved)
            return
        else:
            await conn.execute(
                "UPDATE diff_records SET is_reviewed = 1 "
                "WHERE task_id = ? AND source_path = ? AND is_reviewed = 0",
                (task_id, source),
            )
            # 检查是否存在 target_path == source 的 rename 记录
            # 场景：rename a->b，后续操作 source=b，需连带清理 rename 及之前的记录
            rename_cursor = await conn.execute(
                "SELECT id, created_at, source_path FROM diff_records "
                "WHERE task_id = ? AND operation_type = 'RENAME_FILE' AND target_path = ? AND is_reviewed = 0",
                (task_id, source),
            )
            rename_row = await rename_cursor.fetchone()
            if rename_row:
                # 标记 rename 之前 source_path 与 rename_source 匹配的记录
                await conn.execute(
                    "UPDATE diff_records SET is_reviewed = 1 "
                    "WHERE task_id = ? AND is_reviewed = 0 "
                    "AND source_path = ? AND created_at < ?",
                    (task_id, rename_row['source_path'], rename_row['created_at']),
                )

        # 2. copy_records（可能作为 source 或 target）
        await conn.execute(
            "DELETE FROM copy_records WHERE task_id = ? AND (source_path = ? OR target_path = ?)",
            (task_id, source, source),
        )

        # 3. 磁盘 staging 文件
        staging_area = get_staging_area()
        staging_path = staging_area.get_staging_path(source)
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

