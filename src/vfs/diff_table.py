from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Tuple
from pathlib import Path

from datetime import datetime

from src.db.sqlite_pool import db_pool
from src.utils.common import logger


def print_tree(group, indent=0):
    """递归打印目录树结构"""
    prefix = "  " * indent
    print(f"{prefix}{group.path}")

    # 打印目录操作
    if group.dir_operations:
        print(f"{prefix}  目录操作:")
        for _, record in group.dir_operations:
            print(f"{prefix}    - {record.operation_type.value}")

    # 打印文件操作
    if group.file_operations:
        print(f"{prefix}  文件操作:")
        for file_path, ops in group.file_operations.items():
            print(f"{prefix}    {file_path}:")
            for _, record in ops:
                print(f"{prefix}      - {record.operation_type.value}")

    # 递归打印子目录
    if group.sub_groups:
        print(f"{prefix}  子目录:")
        for sub_path, sub_group in group.sub_groups.items():
            print_tree(sub_group, indent + 3)

class OperationType(Enum):
    # 文件级
    CREATE_FILE = "CREATE_FILE"
    DELETE_FILE = "DELETE_FILE"
    RENAME_FILE = "RENAME_FILE"
    MODIFY_FILE = "MODIFY_FILE"
    # 目录级
    MKDIR = "MKDIR"
    DELETE_DIR = "DELETE_DIR"
    RENAME_DIR = "RENAME_DIR"

@dataclass
class DiffRecord:
    """单条操作记录"""
    task_id: str  # 任务id
    operation_type: OperationType  # 操作类型
    source_path: Optional[str] = None  # 原文件路径
    target_path: Optional[str] = None  # 目标路径
    step: int = 0  # 在任务中的步数，可用于回撤
    # TODO step怎么记录
    created_at: str = field(default_factory=lambda: str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))  # 创建时间

    def to_dict(self) -> dict:
        return {
           "task_id": self.task_id,
           "operation_type": self.operation_type.value,
           "source_path": self.source_path,
           "target_path": self.target_path,
           "step": self.step,
           "created_at": self.created_at
       }

@dataclass
class DirGroup:
    """
    统一的分组结构（组内组外同构）
    """
    path: str  # 当前组路径
    dir_operations: List[Tuple[int, DiffRecord]] | None = None  # 当前路径的目录操作记录
    parent: Optional['DirGroup'] = None  # 父组引用，方便向上查找
    sub_groups: Dict[str, 'DirGroup'] | None = None  # 子路径分组
    file_operations: Dict[str, List[Tuple[int, DiffRecord]]] = field(default_factory=dict)  # 当前路径的文件操作记录

@dataclass
class OperationTree:
    """最简操作集的树"""
    path: str  # 当前路径
    dir_operation: DiffRecord | None = None  # 当前路径的目录操作记录
    # parent: Optional['OperationTree'] | None = None  # 父树引用，方便向上查找
    sub_groups: Dict[str, 'OperationTree'] | None = None  # 子路径分组
    file_operations: Dict[str, List[DiffRecord]] = field(default_factory=dict)  # 当前路径的文件操作记录

class DiffTable:
    """操作记录交互类，可以存储任务中的操作记录，输出待审核结果"""
    
    @staticmethod
    async def operate(record: DiffRecord):
        try:
            async with db_pool.get_conn() as conn:
                if record.operation_type in (OperationType.RENAME_FILE, OperationType.RENAME_DIR):
                    # 检查是否已有链式重命名记录：若已有 a->b，本次为 b->c，则更新为 a->c
                    cursor = await conn.execute('''
                    SELECT id, created_at FROM diff_records
                    WHERE task_id = ? AND operation_type = ? AND target_path = ? AND is_reviewed = 0
                    LIMIT 1
                    ''', (record.task_id, record.operation_type.value, record.source_path))
                    row = await cursor.fetchone()
                    if row:
                        rename_id = row['id']
                        rename_created_at = row['created_at']
                        # 更新 rename 记录：a->b 变为 a->c
                        await conn.execute('''
                        UPDATE diff_records SET target_path = ? WHERE id = ?
                        ''', (record.target_path, rename_id))
                        # 将 rename 之后引用 b 作为 source_path 的记录同步改为 c
                        await conn.execute('''
                        UPDATE diff_records SET source_path = ?
                        WHERE task_id = ? AND is_reviewed = 0 AND source_path = ? AND created_at > ?
                        ''', (record.target_path, record.task_id, record.source_path, rename_created_at))
                        return

                await conn.execute('''
                INSERT INTO diff_records (task_id, operation_type, source_path, target_path, step, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    record.task_id,
                    record.operation_type.value,
                    record.source_path,
                    record.target_path,
                    record.step,
                    record.created_at
                ))
        except Exception as e:
            logger.error(f"写入操作记录失败: {e}")

    @staticmethod
    async def operate_batch(records: List[DiffRecord]):
        """
        批量写入数据库
        """
        if not records:
            return
        data = []
        for record in records:
            data.append((
                record.task_id,
                record.operation_type.value,
                record.source_path,
                record.target_path,
                record.step,
                record.created_at
            ))
        try:
            async with db_pool.get_conn() as conn:
                await conn.executemany('''
                INSERT INTO diff_records (task_id, operation_type, source_path, target_path, step, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', data)
        except Exception as e:
            logger.error(f"批量写入操作记录失败: {e}")

    @staticmethod
    async def list(task_id: str) -> List[DiffRecord]:
        """
        根据task_id导出所有操作
        """
        records = []
        try:
            async with db_pool.get_conn() as conn:
                cursor = await conn.execute('''
                SELECT id, task_id, operation_type, source_path, target_path, step, created_at
                FROM diff_records
                WHERE task_id = ? AND is_reviewed = 0
                ORDER BY created_at ASC
                ''', (task_id,))

                rows = await cursor.fetchall()
                for row in rows:
                    record = DiffRecord(
                        task_id=row['task_id'],
                        operation_type=OperationType(row['operation_type']),
                        source_path=row['source_path'],
                        target_path=row['target_path'],
                        step=row['step']
                    )
                    records.append(record)
        except Exception as e:
            logger.error(f"导出操作记录失败: {e}")

        return records

    @staticmethod
    async def has_unreviewed(task_id: str) -> bool:
        """检查是否有未审批的操作记录"""
        try:
            async with db_pool.get_conn() as conn:
                cursor = await conn.execute(
                    "SELECT COUNT(*) as cnt FROM diff_records WHERE task_id = ? AND is_reviewed = 0",
                    (task_id,),
                )
                row = await cursor.fetchone()
                return row['cnt'] > 0
        except Exception as e:
            logger.error(f"检查未审批记录失败: {e}")
            return False

    @staticmethod
    async def mark_reviewed(task_id: str):
        """将 task 的所有未审批记录标记为已审批"""
        try:
            async with db_pool.get_conn() as conn:
                await conn.execute(
                    "UPDATE diff_records SET is_reviewed = 1 WHERE task_id = ? AND is_reviewed = 0",
                    (task_id,),
                )
        except Exception as e:
            logger.error(f"标记已审批失败: {e}")

    @staticmethod
    def merge(records: List[DiffRecord]) -> OperationTree | None:
        """
        合并操作记录，生成最简操作集的树
        
        Args:
            records: 操作记录列表
            
        Returns:
            OperationTree | None: 最简操作集的树，如果没有操作则返回None
        """
        if not records:
            return None

        # 1、反向遍历，建立路径映射并应用
        # 目的：处理重命名操作对在它之前操作路径的影响
        mapping = {} # old_path -> new_path
        
        for record in reversed(records):
            if record.operation_type in (OperationType.RENAME_DIR, OperationType.RENAME_FILE):
                if record.target_path in mapping:
                    # 处理链式重命名：如果本次操作 a->b，之前有b->c，则修改为 a->c
                    record.target_path = mapping[record.target_path]
                # 建立映射关系
                mapping[record.source_path] = record.target_path
            else:
                if record.source_path:
                    # 其他操作应用路径映射
                    record.source_path = DiffTable._apply_mapping(record.source_path, mapping)

        # 2、分组（两次遍历）
        # 目的：将操作按照目录结构分组，便于后续合并
        # 第一遍遍历，提取目录级操作，构建目录树
        root = DirGroup(path="")
        path_to_group: Dict[str, DirGroup] = {"" : root}  # path到某一DirGroup的索引，避免每次递归查询

        for i, record in enumerate(records):
            if record.operation_type not in (OperationType.MKDIR, OperationType.DELETE_DIR, OperationType.RENAME_DIR):
                continue

            # 是MKDIR或者DELETE_DIR，用source_path作为key
            if record.operation_type in (OperationType.MKDIR, OperationType.DELETE_DIR):
                path = record.source_path
            # 是RENAME_DIR，用target_path作为key
            elif record.operation_type == OperationType.RENAME_DIR:
                path = record.target_path
            group = DiffTable._get_or_create_group(path, path_to_group)

            if group.dir_operations is None:
                group.dir_operations = []
            group.dir_operations.append((i, record))

        # 第二次遍历，处理文件级操作
        for i, record in enumerate(records):
            # 是目录级操作，跳过
            if record.operation_type in (OperationType.MKDIR, OperationType.DELETE_DIR, OperationType.RENAME_DIR):
                continue

            # RENAME_FILE 操作用到了target_path，需要特殊处理
            if record.operation_type == OperationType.RENAME_FILE:
                dir_group = DiffTable._is_subpath(record.target_path, path_to_group)
                # 如果存在目录组，就划分到对应组的文件操作
                if dir_group:
                    path_to_group[dir_group].file_operations.setdefault(record.target_path, []).append((i, record))
                # 否则划分到root的文件操作下
                else:
                    root.file_operations.setdefault(record.target_path, []).append((i, record))
            # 其他文件操作，用source_path作为key
            else:
                dir_group = DiffTable._is_subpath(record.source_path, path_to_group)
                # 如果存在目录组，就划分到对应组的文件操作
                if dir_group:
                    path_to_group[dir_group].file_operations.setdefault(record.source_path, []).append((i, record))
                # 否则划分到root的文件操作下
                else:
                    root.file_operations.setdefault(record.source_path, []).append((i, record))

        # print_tree(root)
        # return root

        # 3、按照组别合并操作
        operation_tree, _ = DiffTable._build_operation_tree(root)

        # 4、返回最简操作集的树
        return operation_tree[0] if operation_tree else None

    @staticmethod
    def _apply_mapping(path: str, mapping: Dict[str, str]) -> str:
        """应用映射：精确匹配（文件重命名） 或 前缀替换（目录重命名）"""
        if not path:
            return path
        
        # 1. 精确匹配
        if path in mapping:
            return mapping[path]
        
        # 2. 前缀匹配：检查是否是某个已映射目录的子路径
        for old_path, new_path in mapping.items():
            # 确保是目录前缀（以 / 结尾或后面跟着 /）
            if path == old_path or path.startswith(old_path + "/"):
                return new_path + path[len(old_path):]
        
        # 3. 未匹配到任何路径，返回原始路径
        return path

    @staticmethod
    def _is_subpath(path: str, parent_candidates: Dict[str, 'DirGroup']) -> Optional[str]:
        """检查 path 是否是 parent_candidates 中任一目录的子路径，如果是则返回该路径，否则返回None"""
        if path is None:
            return None
        
        p = Path(path)
        
        # 逐层向上检查：/a/b/c → /a/b → /a → /
        for parent in list(p.parents):
            parent_str = str(parent)
            if parent_str in parent_candidates:
                return parent_str
        return None

    @staticmethod
    def _find_child(new_path: str, parent: 'DirGroup') -> Optional['DirGroup']:
        """
            在 parent 的现有子节点中，找应该被 new_path 收养的子节点
            条件：子节点路径以 new_path 为前缀，且是最近匹配
        """
        if not parent.sub_groups:
            return None

        prefix = new_path + "/"

        for name, child in parent.sub_groups.items():
            if child.path.startswith(prefix):
                return child
        return None

    @staticmethod
    def _link(parent: 'DirGroup', child: 'DirGroup'):
        """建立双向链接"""
        child.parent = parent
        if parent.sub_groups is None:
            parent.sub_groups = {}
        parent.sub_groups[child.path] = child

    @staticmethod
    def _get_or_create_group(path: str, path_to_group: Dict[str, 'DirGroup']) -> 'DirGroup':
        """获取或创建组，动态维护树结构"""
        if path in path_to_group:
            return path_to_group[path]

        # 不存在则创建新组
        group = DirGroup(path=path)
        path_to_group[path] = group

        # 找最优父节点
        parent_path = DiffTable._is_subpath(path, path_to_group)
        if not parent_path:
            parent_path = ""

        parent = path_to_group[parent_path]

        # 找子节点
        child = DiffTable._find_child(path, parent)

        # 创建三者之间的连接
        if child:
            # 解除旧连接,parent的sub_groups不再指向child
            del parent.sub_groups[child.path]
            DiffTable._link(parent, group)
            DiffTable._link(group, child)
        else:
            DiffTable._link(parent, group)

        return group

    @staticmethod
    def _build_operation_tree(group: DirGroup, delete_index: int = -1) -> Tuple[List[OperationTree] | None, Dict[str, List[DiffRecord]] | None]:
        """
        递归构建操作树，合并组内操作
        
        Args:
            group: 当前目录组
            delete_index: 上一级delete_dir的下标，-1表示无删除操作
、
        Returns:
            Tuple[List[OperationTree] | None, Dict[str, List[DiffRecord]] | None]: 
                - 第一个元素：待加入主树的子操作树列表，为None表示无操作
                - 第二个元素：待加入主树的文件操作列表，为None表示无操作
        """
        tree = OperationTree(path=group.path)
        level_disable = False  # 标记当前层是否作为操作树的一层（为True时，往上传递子操作树）
        file_operations: Dict[str, List[DiffRecord]] = {}  # 往上传递的文件操作
        sub_groups: List[OperationTree] = []  # 往上传递的子操作树

        # 1、合并目录级操作
        final_dir_op = None
        delete_after_create = False  # 标记是否是先创建后删除的情况
        is_create_dir = False  # 标记当前目录是否是新建的
        
        if group.dir_operations:
            if delete_index > -1:
                # 如果上一级有删除操作，创建一个DELETE_DIR记录作为初始值
                final_dir_op = DiffRecord(
                    task_id=group.dir_operations[0][1].task_id,
                    operation_type=OperationType.DELETE_DIR,
                    source_path=group.path
                )
            
            # 检查第一个操作是否是MKDIR
            if group.dir_operations[0][1].operation_type == OperationType.MKDIR:
                is_create_dir = True
                # 如果MKDIR操作在删除操作之前，标记为创建后删除
                if group.dir_operations[0][0] < delete_index:
                    delete_after_create = True

            # 遍历目录操作记录
            for idx, record in group.dir_operations:
                if idx < delete_index:
                    # 跳过删除操作之前的操作
                    continue
                # 如果有delete_dir操作，更新delete_index
                if record.operation_type == OperationType.DELETE_DIR:
                    delete_index = idx
                    # 如果当前目录是新建的，标记为创建后删除
                    delete_after_create = True if is_create_dir else False
                
                # 合并操作
                final_dir_op = DiffTable._match(final_dir_op, record)

        # 检查是否需要禁用当前层
        # 情况1：目录被创建后又删除，最终无操作
        if final_dir_op is None and delete_after_create:
            level_disable = True
        elif final_dir_op is not None:
            # 情况2：目录最终操作是DELETE_DIR，且是新建的目录
            if final_dir_op.operation_type == OperationType.DELETE_DIR and is_create_dir:
                level_disable = True
            else:
                # 否则，设置当前目录的操作
                tree.dir_operation = final_dir_op

        # 2、合并文件级操作
        # 对于原本不存在的文件（第一个操作为create_file），它的最终状态只会是create/None，可以不必关心中间过程
        # 此时只需看操作链的最后一个，为delete或者上一层有delete_dir，那么操作就被抵消了，最终为none
        #
        # 对于原本存在的文件（第一个操作不为create_file），它的最终状态只会是modify/delete，rename因为不涉及修改内容所以作为附加操作
        # 此时需要遍历操作链，按照规则合并操作
        if group.file_operations:
            for file_path, records in group.file_operations.items():
                final_file_op = None
                # 如果第一个操作是create_file，那么可以直接看最后一个操作
                if records[0][1].operation_type == OperationType.CREATE_FILE:
                    # 如果最后一个操作不是delete_file，并且在delete_dir（如果有）之后还有操作，那么合并为create_file
                    if records[-1][1].operation_type != OperationType.DELETE_FILE and records[-1][0] > delete_index:
                        final_file_op = records[0][1]  # 引用第一个操作
                    # 否则就抵消create_file
                    else:
                        final_file_op = None
                    # final_file_op 不为None，直接添加到树
                    if final_file_op is not None:
                        file_operations.setdefault(file_path, []).append(final_file_op)
                    
                # 否则，需要遍历所有操作，按照规则合并为最终操作
                else:
                    if delete_index > -1:
                        # 如果上一级有删除操作，创建一个DELETE_FILE记录作为初始值
                        final_file_op = DiffRecord(
                            task_id=records[0][1].task_id,
                            operation_type=OperationType.DELETE_FILE,
                            source_path=file_path
                        )
                    rename_op = None
                    for idx, record in records:
                        # 保留第一条rename_file操作
                        if not rename_op and record.operation_type == OperationType.RENAME_FILE:
                            rename_op = record
                        # 跳过delete之前的操作
                        if idx < delete_index:
                            continue
                        # 合并操作
                        final_file_op = DiffTable._match(final_file_op, record)
                    # 如果有最终是delete_file操作,且有rename_file操作,需要把delete_file的source_path改为原本的路径
                    if final_file_op and final_file_op.operation_type == OperationType.DELETE_FILE and rename_op:
                        final_file_op.source_path = rename_op.source_path
                        file_operations.setdefault(file_path, []).append(final_file_op)
                    elif final_file_op:
                        if rename_op:
                            file_operations.setdefault(file_path, []).append(rename_op)
                        file_operations.setdefault(file_path, []).append(final_file_op)

        # 3、递归处理子树
        if group.sub_groups:
            for name, child in group.sub_groups.items():
                # 传递更新后的delete_index
                child_groups, child_ops = DiffTable._build_operation_tree(child, delete_index)
                
                # 处理子树返回的操作树
                if child_groups:
                    sub_groups.extend(child_groups)
                
                # 处理子树返回的文件操作
                if child_ops:
                    for file_path, ops in child_ops.items():
                        if file_path not in file_operations:
                            file_operations[file_path] = []
                        file_operations[file_path].extend(ops)

        # 4、根据level_disable决定返回方式
        if level_disable:
            # 如果当前层被禁用，向上传递子操作和文件操作
            return sub_groups, file_operations
        
        # 构建当前层的操作树
        # 构建子树字典
        if sub_groups:
            tree.sub_groups = {}
            for sub_tree in sub_groups:
                tree.sub_groups[sub_tree.path] = sub_tree
        # 设置文件操作
        tree.file_operations = file_operations

        # 检查是否需要返回tree
        # 只有当tree包含操作时才返回，否则返回None
        if tree.dir_operation or tree.sub_groups or tree.file_operations:
            return [tree], None  # 返回当前树，文件操作已包含在树中
        else:
            return None, None  # 无操作，返回None

    @staticmethod
    def _match(prev_record: Optional[DiffRecord], cur_record: DiffRecord) -> Optional[DiffRecord]:
        """
        操作合并规则
        目录级：
        None + any = any
        mkdir + rename_dir = mkdir
        None/rename_dir + delete_dir = delete_dir
        mkdir/delete_dir + mkdir/delete_dir = None

        文件级：只适用于原文件存在的情况
        None + any(除了rename_file) = any
        delete_file + create_file = modify_file
        create_file + delete_file = delete_file
        modify_file + modify_file = modify_file
        """
        # 提取操作类型
        prev_op = prev_record.operation_type if prev_record else None
        cur_op = cur_record.operation_type
        
        # 定义合并规则映射
        merge_rules = {
            # 目录级操作规则
            (None, OperationType.MKDIR): OperationType.MKDIR,
            (None, OperationType.DELETE_DIR): OperationType.DELETE_DIR,
            (None, OperationType.RENAME_DIR): OperationType.RENAME_DIR,
            (OperationType.MKDIR, OperationType.RENAME_DIR): OperationType.MKDIR,
            (OperationType.MKDIR, OperationType.DELETE_DIR): None,
            (OperationType.DELETE_DIR, OperationType.MKDIR): None,
            (OperationType.RENAME_DIR, OperationType.DELETE_DIR): OperationType.DELETE_DIR,
            
            # 文件级操作规则
            (None, OperationType.DELETE_FILE): OperationType.DELETE_FILE,
            (None, OperationType.MODIFY_FILE): OperationType.MODIFY_FILE,
            (OperationType.DELETE_FILE, OperationType.CREATE_FILE): OperationType.MODIFY_FILE,
            (OperationType.MODIFY_FILE, OperationType.DELETE_FILE): OperationType.DELETE_FILE,
            (OperationType.MODIFY_FILE, OperationType.MODIFY_FILE): OperationType.MODIFY_FILE,
        }
        
        # 查找规则映射
        key = (prev_op, cur_op)
        if key not in merge_rules:
            raise ValueError(f"未定义合并规则：{key}")
        
        result_op = merge_rules[key]
        if result_op is None:
            return None
        
        # 根据合并结果返回或创建记录
        # 只有RENAME_DIR会用到target_path, 需要特殊判断
        if result_op == OperationType.RENAME_DIR:
            # 对应 None + rename_dir = rename_dir，直接返回第二个
            return cur_record
        
        return DiffRecord(
            task_id=cur_record.task_id,
            operation_type=result_op,
            # 如果第二个操作为RENAME_DIR，就得取它的target_path
            source_path=cur_record.source_path if cur_record.operation_type != OperationType.RENAME_DIR else cur_record.target_path
        )
