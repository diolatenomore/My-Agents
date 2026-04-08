import os
from pathlib import Path

from copy_mapping import CopyMapping, copy
from diff_table import DiffRecord, OperationType, DiffTable
from context_manager import get_current_task_id
from staging_area import StagingArea
from utils import check_file_path, check_dir_path

"""
文件操作函数
只要涉及创建、修改文件/目录，都会放到暂存区
"""

# TODO 在此阶段要加上操作约束，比如不能创建已存在的文件/目录，不能删除不存在的文件/目录、不能再删除之后操作该文件/目录（除非再创建）

def read_file(source_path: str):
    # TODO 如果暂存区里有该文件，就返回暂存区里的内容，否则返回原文件内容
    pass

def create_file(source_path: str, content: str):
    """为了统一，这里把source_path作为目标路径"""

    # TODO 何得到task_id？
    # 目前思路是从上下文变量中获取task_id
    task_id = get_current_task_id()

    # 路径合法性检查
    result = check_file_path(source_path)
    if result:
        return result
    # 检查路径是否存在
    staging_path = StagingArea.get_staging_path(source_path)
    if staging_path:
        return "路径已存在"
    elif os.path.exists(source_path):
      return "路径已存在"

    # 在暂存区为source_path分配一条路径
    staging_path = StagingArea.register(source_path)

    # TODO 实现真实文件写入
    os.makedirs(os.path.dirname(staging_path), exist_ok=True)
    with open(staging_path, "w") as f:
        f.write(content)

    record = DiffRecord(task_id=task_id, operation_type=OperationType.CREATE_FILE, source_path=source_path)
    DiffTable.operate(record)

def delete_file(source_path: str):
    task_id = get_current_task_id()

    # 检查路径是否存在（真实路径/虚拟路径——是否已删除）
    staging_path = StagingArea.get_staging_path(source_path)
    if staging_path is None:
        # 检查是否被删除了
        if StagingArea.is_deleted(source_path):
            return "在暂存区中被删除"
        # 检查原文件是否存在
        if not os.path.exists(source_path):
            return "原路径不存在"

    # 检查文件是否是被拷贝的对象并且未触发拷贝
    if CopyMapping.need_copied(source_path):
        CopyMapping.mark_copied(source_path)

    # 在暂存区中标记删除
    StagingArea.delete(source_path)

    record = DiffRecord(task_id=task_id, operation_type=OperationType.DELETE_FILE, source_path=source_path)
    DiffTable.operate(record)

def rename_file(source_path: str, target_path: str):
    task_id = get_current_task_id()

    # 不允许跨目录重命名
    source_parent = str(Path(source_path).parent)
    target_parent = str(Path(target_path).parent)
    # 统一处理"."和"/"的情况
    if source_parent == "." or source_parent == "/":
        source_parent = ""
    if target_parent == "." or target_parent == "/":
        target_parent = ""
    
    if source_parent != target_parent:
        return "跨目录重命名不支持"

    # 检查target_path路径合法性
    result = check_file_path(target_path)
    if result:
        return result

    # 处理target_path命名冲突
    target_staging_path = StagingArea.get_staging_path(target_path)
    if target_staging_path:
        return "目标路径已存在"
    elif os.path.exists(target_path):
        return "目标路径已存在"

    # 检查source_path是否存在
    source_staging_path = StagingArea.get_staging_path(source_path)
    if source_staging_path is None:
        # 检查是否被删除了
        if StagingArea.is_deleted(source_path):
            return "原路径不存在"
        # 检查原文件是否存在
        if not os.path.exists(source_path):
            return "原路径不存在"
        # 从暂存区获取一条路径
        staging_path = StagingArea.register(source_path)

    # 修改对应的路径映射关系
    StagingArea.rename(source_path, target_path)
    CopyMapping.rename(source_path, target_path)

    record = DiffRecord(task_id=task_id, operation_type=OperationType.RENAME_FILE, source_path=source_path, target_path=target_path)
    DiffTable.operate(record)

def modify_file(source_path: str, content: str):
    task_id = get_current_task_id()

    # 检查source_path是否存在
    staging_path = StagingArea.get_staging_path(source_path)
    if staging_path is None:
        # 检查是否被删除了
        if StagingArea.is_deleted(source_path):
            return "原路径不存在"
        # 检查原文件是否存在
        if not os.path.exists(source_path):
            return "原路径不存在"
        # 从暂存区获取一条路径，并拷贝原文件
        staging_path = StagingArea.register(source_path)
        copy(source_path, staging_path)

    # 检查文件是否需要拷贝到暂存区
    CopyMapping.copy_if_need(source_path)

    # 检查文件是否是被拷贝的对象并且未触发拷贝
    if CopyMapping.need_copied(source_path):
        CopyMapping.mark_copied(source_path)

    # TODO 修改文件内容
    # modify(staging_path, content)

    record = DiffRecord(task_id=task_id, operation_type=OperationType.MODIFY_FILE, source_path=source_path)
    DiffTable.operate(record)

def copy_file(source_path: str, target_path: str):
    task_id = get_current_task_id()

    # 检查source_path是否存在 （真实路径）
    # 禁止拷贝原本不存在的文件（使用虚拟路径作为source_path）
    if not os.path.exists(source_path):
        return "原文件不存在"

    # 检查target_path路径合法性
    result = check_file_path(target_path)
    if result:
        return result

    # 检查target_path是否存在
    target_staging_path = StagingArea.get_staging_path(target_path)
    if target_staging_path:
        return "目标路径已存在"
    elif os.path.exists(target_path):
        return "目标路径已存在"

    # 在暂存区为target_path分配一条路径
    staging_path = StagingArea.register(target_path)

    # 写入一条复制记录，用于写时复制
    CopyMapping.register(source_path, target_path)

    record = DiffRecord(task_id=task_id, operation_type=OperationType.CREATE_FILE, source_path=target_path)
    DiffTable.operate(record)

def move_file(source_path: str, target_path: str):
    # TODO 待实现+优化，按照当前的机制，会立即触发拷贝，
    task_id = get_current_task_id()

    copy_file(source_path, target_path)
    record2 = DiffRecord(task_id=task_id, operation_type=OperationType.DELETE_FILE, source_path=source_path)

    DiffTable.operate(record2)

def mkdir(source_path: str):
    """为了统一，这里把source_path作为目标路径"""
    task_id = get_current_task_id()

    # 路径合法性检查
    result = check_dir_path(source_path)
    if result:
        return result

    # 检查路径是否存在
    target_staging_path = StagingArea.get_staging_dir_path(source_path)
    if target_staging_path:
        return "目录已存在"
    elif os.path.exists(source_path):
        return "目录已存在"

    # 在暂存区为source_path占位
    StagingArea.register_dir(source_path)

    record = DiffRecord(task_id=task_id, operation_type=OperationType.MKDIR, source_path=source_path)
    DiffTable.operate(record)

def delete_dir(source_path: str):
    task_id = get_current_task_id()

    # 检查source_path是否存在 （真实路径/虚拟路径——是否已删除）
    staging_path = StagingArea.get_staging_dir_path(source_path)
    if staging_path is None:
        # 检查是否被删除了
        if StagingArea.is_deleted_dir(source_path):
            return "目录不存在"
        # 检查原目录是否存在
        if not os.path.exists(source_path):
            return "目录不存在"

    # 检查文件是否是被拷贝的对象并且未触发拷贝
    if CopyMapping.need_copied_dir(source_path):
        CopyMapping.mark_copied_dir(source_path)

    # 在暂存区中删除
    StagingArea.delete_dir(source_path)

    record = DiffRecord(task_id=task_id, operation_type=OperationType.DELETE_DIR, source_path=source_path)
    DiffTable.operate(record)

def rename_dir(source_path: str, target_path: str):
    task_id = get_current_task_id()

    # 不允许跨目录重命名
    source_parent = str(Path(source_path).parent)
    target_parent = str(Path(target_path).parent)
    # 统一处理"."和"/"的情况
    if source_parent == "." or source_parent == "/":
        source_parent = ""
    if target_parent == "." or target_parent == "/":
        target_parent = ""
    
    if source_parent != target_parent:
        return "跨目录重命名不支持"

    # 检查target_path路径合法性
    result = check_dir_path(target_path)
    if result:
        return result

    # 处理命名冲突，检查target_path是否存在
    target_staging_path = StagingArea.get_staging_dir_path(target_path)
    if target_staging_path:
        return "目标目录已存在"
    elif os.path.exists(target_path):
        return "目标目录已存在"

    # 检查source_path是否存在 （真实路径/虚拟路径——是否已删除）
    staging_path = StagingArea.get_staging_dir_path(source_path)
    if staging_path is None:
        # 检查是否被删除了
        if StagingArea.is_deleted_dir(source_path):
            return "原目录不存在"
        # 检查原目录是否存在
        if not os.path.exists(source_path):
            return "原目录不存在"
        # 从暂存区获取一条路径，并拷贝原目录
        staging_path = StagingArea.register_dir(source_path)

    # 修改对应的映射关系
    StagingArea.rename_dir(source_path, target_path)
    CopyMapping.rename_dir(source_path, target_path)

    record = DiffRecord(task_id=task_id, operation_type=OperationType.RENAME_DIR, source_path=source_path, target_path=target_path)
    DiffTable.operate(record)

def copy_dir(source_path: str, target_path: str):
    task_id = get_current_task_id()

    # 检查source_path是否存在 （真实路径）
    # 禁止拷贝原本不存在的文件（使用虚拟路径作为source_path）
    if not os.path.exists(source_path):
        return "原路径不存在"

    # 检查target_path路径合法性
    result = check_dir_path(target_path)
    if result:
        return result

    # 处理命名冲突，检查target_path是否存在
    target_staging_path = StagingArea.get_staging_dir_path(target_path)
    if target_staging_path:
        return "目标目录已存在"
    elif os.path.exists(target_path):
        return "目标目录已存在"

    # 写入一条复制记录，用于写时复制
    CopyMapping.register_dir(source_path, target_path)

    # 递归写子目录和和文件的CREATE_FILE和MKDIR操作记录
    operations = []
    for root, dirs, files in os.walk(source_path):
    # root: 当前遍历目录的完整路径      dirs: 当前目录下的子目录列表    files: 当前目录下的文件列表
        for dir_name in dirs:
            # 构造目标目录完整路径
            source_dir = os.path.join(root, dir_name)           # 原目录完整路径
            target_dir = source_dir.replace(source_path, target_path, 1)  # 目标目录完整路径
            
            # 在暂存区为target_dir占位
            StagingArea.register_dir(target_dir)
            operations.append(DiffRecord(task_id=task_id, operation_type=OperationType.MKDIR, source_path=target_dir))
            
        for file_name in files:
            # 构造目标文件完整路径
            source_file = os.path.join(root, file_name)         # 原文件完整路径
            target_file = source_file.replace(source_path, target_path, 1)  # 目标文件完整路径
            
            # 在暂存区为target_file分配一条路径
            StagingArea.register(target_file)
            operations.append(DiffRecord(task_id=task_id, operation_type=OperationType.CREATE_FILE, source_path=target_file))

    # 批量写入操作记录
    DiffTable.operate_batch(operations)

def move_dir(source_path: str, target_path: str):
    task_id = get_current_task_id()

    # TODO 待实现+优化，按照当前的机制，会立即触发拷贝
    record1 = DiffRecord(task_id=task_id, operation_type=OperationType.COPY_DIR, source_path=source_path, target_path=target_path)
    record2 = DiffRecord(task_id=task_id, operation_type=OperationType.DELETE_DIR, source_path=source_path)

    DiffTable.operate_batch([record1, record2])
