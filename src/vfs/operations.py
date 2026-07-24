import os
from pathlib import Path
from typing import Optional

from src.vfs.diff_table import DiffRecord, OperationType, DiffTable
from src.vfs.task_context import get_current_task_id, get_staging_area, get_copy_mapping, get_vfs_lock
from src.utils.vfs import check_file_path, check_dir_path, isfile, isdir, copy

"""
文件操作函数
只要涉及创建、修改文件/目录，都会放到暂存区
"""

# TODO 后续加上工作目录的概念（传入工作目录路径并拼接？）

async def list_dir(source_path: str):
    """列出目录下的所有文件和子目录"""
    # 路径合法性检查
    result = check_dir_path(source_path)
    if result:
        return result

    # 检查目录是否存在
    staging_area = get_staging_area()
    staging_path = staging_area.get_staging_dir_path(source_path)
    if staging_path is None:
        # 检查是否被删除了
        if staging_area.is_deleted_dir(source_path):
            return f"ERROR：目录{source_path}不存在"
        # 检查原目录是否存在
        if not os.path.exists(source_path):
            return f"ERROR：目录{source_path}不存在"

    # 从真实文件系统获取目录内容
    real_files = set()
    real_dirs = set()
    # 当source_path为虚拟的路径，os.listdir会报错，此时跳过即可
    try:
        for item in os.listdir(source_path):
            item_path = os.path.join(source_path, item)
            if os.path.isfile(item_path):
                real_files.add(item)
            elif os.path.isdir(item_path):
                real_dirs.add(item)
    except FileNotFoundError:
        pass

    # 从暂存区获取目录内容
    staged_files = set()
    staged_dirs = set()
    deleted_files = set()
    deleted_dirs = set()

    # 遍历暂存区中的所有路径
    for path in staging_area.mapping:
        # 检查是否是当前目录的直接子项
        if path.startswith(source_path + "/"):
            # 提取子项名称
            relative_path = path[len(source_path) + 1:]
            if "/" not in relative_path:
                if isfile(path):
                    staged_files.add(relative_path)
                elif isdir(path):
                    staged_dirs.add(relative_path)

    # 检查已删除的文件（不在映射中但被标记为删除的文件）
    for path in staging_area.deleted_mapping:
        if staging_area.deleted_mapping[path] and path.startswith(source_path + "/"):
            relative_path = path[len(source_path) + 1:]
            if "/" not in relative_path:
                deleted_files.add(relative_path)

    # 检查已删除的目录（不在映射中但被标记为删除的目录）
    for path in staging_area.deleted_dir_mapping:
        if staging_area.deleted_dir_mapping[path] and path.startswith(source_path + "/"):
            relative_path = path[len(source_path) + 1:]
            if "/" not in relative_path:
                deleted_dirs.add(relative_path)

    # 合并结果，排除已删除的项
    final_files = (real_files | staged_files) - deleted_files
    final_dirs = (real_dirs | staged_dirs) - deleted_dirs

    # 构建返回结果
    result = {
        "files": sorted(list(final_files)),
        "dirs": sorted(list(final_dirs))
    }

    return result


async def read_file(path: str):
    """如果暂存区里有该文件，就返回暂存区里的内容，否则返回原文件内容"""
    # 检查路径是否存在（真实路径/虚拟路径——是否已删除）
    staging_area = get_staging_area()
    staging_path = staging_area.get_staging_path(path)
    if staging_path is None:
        # 检查是否被删除了
        if staging_area.is_deleted(path):
            return f"ERROR：文件{path}不存在"
        # 检查原文件是否存在
        if not os.path.exists(path):
            return f"ERROR：文件{path}不存在"
    if staging_path:
        return open(staging_path, "r").read()
    else:
        return open(path, "r").read()


async def create_file(path: str, content: str):
    task_id = get_current_task_id()
    async with get_vfs_lock():
        # 路径合法性检查
        result = check_file_path(path)
        if result:
            return result
        # 检查路径是否存在（真实路径/虚拟路径——是否已删除）
        staging_area = get_staging_area()
        staging_path = staging_area.get_staging_path(path)
        if staging_path:
            return f"ERROR：命名冲突，文件{path}已存在"
        # 如果文件在暂存区被标记为删除，允许在同路径重新创建
        if not staging_area.is_deleted(path) and os.path.exists(path):
            return f"ERROR：命名冲突，文件{path}已存在"

        # 在暂存区为path分配一条路径
        staging_path = await staging_area.register(path)

        os.makedirs(os.path.dirname(staging_path), exist_ok=True)
        with open(staging_path, "w") as f:
            f.write(content)

        record = DiffRecord(task_id=task_id, operation_type=OperationType.CREATE_FILE, source_path=path)
        await DiffTable.operate(record)

        return f"文件{path}创建成功"


async def delete_file(path: str):
    task_id = get_current_task_id()
    async with get_vfs_lock():
        # 检查路径是否存在（真实路径/虚拟路径——是否已删除）
        staging_area = get_staging_area()
        staging_path = staging_area.get_staging_path(path)
        if staging_path is None:
            # 检查是否被删除了
            if staging_area.is_deleted(path):
                return f"ERROR：文件{path}不存在"
            # 检查原文件是否存在
            if not os.path.exists(path):
                return f"ERROR：文件{path}不存在"

        # 检查文件是否是被拷贝的对象并且未触发拷贝
        copy_mapping = get_copy_mapping()
        if copy_mapping.need_copied(path):
            await copy_mapping.mark_copied(path)

        # 在暂存区中标记删除
        await staging_area.delete(path)

        record = DiffRecord(task_id=task_id, operation_type=OperationType.DELETE_FILE, source_path=path)
        await DiffTable.operate(record)

        return f"文件{path}删除成功"


async def rename_file(source_path: str, target_path: str):
    task_id = get_current_task_id()
    async with get_vfs_lock():
        # 不允许跨目录重命名
        source_parent = str(Path(source_path).parent)
        target_parent = str(Path(target_path).parent)
        # 统一处理"."和"/"的情况
        if source_parent == "." or source_parent == "/":
            source_parent = ""
        if target_parent == "." or target_parent == "/":
            target_parent = ""

        if source_parent != target_parent:
            return f"ERROR：不支持跨目录重命名 {source_path}->{target_path}"

        # 检查target_path路径合法性
        result = check_file_path(target_path)
        if result:
            return result

        # 处理target_path命名冲突
        staging_area = get_staging_area()
        target_staging_path = staging_area.get_staging_path(target_path)
        if target_staging_path:
            return f"ERROR：命名冲突，目标路径{target_path}已存在"
        elif not staging_area.is_deleted(target_path) and os.path.exists(target_path):
            return f"ERROR：命名冲突，目标路径{target_path}已存在"

        # 检查source_path是否存在
        source_staging_path = staging_area.get_staging_path(source_path)
        if source_staging_path is None:
            # 检查是否被删除了
            if staging_area.is_deleted(source_path):
                return f"ERROR：原文件{source_path}不存在"
            # 检查原文件是否存在
            if not os.path.exists(source_path):
                return f"ERROR：原文件{source_path}不存在"
            # 从暂存区获取一条路径
            await staging_area.register(source_path)

        # 修改对应的路径映射关系
        await staging_area.rename(source_path, target_path)
        copy_mapping = get_copy_mapping()
        await copy_mapping.rename(source_path, target_path)

        record = DiffRecord(task_id=task_id, operation_type=OperationType.RENAME_FILE, source_path=source_path,
                            target_path=target_path)
        await DiffTable.operate(record)

        return f"文件{source_path}重命名为{target_path}成功"

# TODO 考虑多会话之间的合并冲突
async def modify_file(path: str, new_str: str, replace: bool, old_str: str = None):
    """
    修改文件内容

    Args:
        path: 文件路径
        new_str: 文件内容。replace=False 时为完整新内容；replace=True 时为替换后的新内容
        replace: 是否使用 SEARCH/REPLACE 模式。True=增量替换，False=全量覆盖
        old_str: SEARCH/REPLACE 模式下要查找替换的原始内容。仅 replace=True 时使用
    """
    task_id = get_current_task_id()
    async with get_vfs_lock():
        # 检查path是否存在
        staging_area = get_staging_area()
        staging_path = staging_area.get_staging_path(path)
        if staging_path is None:
            # 检查是否被删除了
            if staging_area.is_deleted(path):
                return f"ERROR：文件{path}不存在"
            # 检查原文件是否存在
            if not os.path.exists(path):
                return f"ERROR：文件{path}不存在"
            # 从暂存区获取一条路径，并拷贝原文件
            staging_path = await staging_area.register(path)
            copy(path, staging_path)

        # 检查文件是否需要拷贝到暂存区
        copy_mapping = get_copy_mapping()
        await copy_mapping.copy_if_need(path)

        # 检查文件是否是被拷贝的对象并且未触发拷贝
        if copy_mapping.need_copied(path):
            await copy_mapping.mark_copied(path)

        if replace:
            if old_str is None:
                return f"ERROR：SEARCH/REPLACE 模式下必须提供 old_str"
            # SEARCH/REPLACE 模式：在文件中查找 old_str 并替换为 new_str
            with open(staging_path, "r") as f:
                file_content = f.read()

            count = file_content.count(old_str)
            if count == 0:
                return f"ERROR：未在文件{path}中找到要替换的内容，请检查 old_str 是否正确"
            if count > 1:
                return f"ERROR：old_str 在文件{path}中出现了 {count} 次（不唯一），请提供更多上下文以保证唯一匹配"

            new_content = file_content.replace(old_str, new_str)
            with open(staging_path, "w") as f:
                f.write(new_content)
        else:
            # 全量覆盖模式
            os.makedirs(os.path.dirname(staging_path), exist_ok=True)
            with open(staging_path, "w") as f:
                f.write(new_str)

        record = DiffRecord(task_id=task_id, operation_type=OperationType.MODIFY_FILE, source_path=path)
        await DiffTable.operate(record)

        return f"文件{path}修改成功"


async def copy_file(source_path: str, target_path: str):
    task_id = get_current_task_id()
    async with get_vfs_lock():
        # 检查source_path是否存在 （真实路径）
        # 禁止拷贝原本不存在的文件（使用虚拟路径作为source_path）
        if not os.path.exists(source_path):
            return f"ERROR：原文件{source_path}不存在/无法拷贝新创建的文件"

        # 检查target_path路径合法性
        result = check_file_path(target_path)
        if result:
            return result

        # 检查target_path是否存在
        staging_area = get_staging_area()
        target_staging_path = staging_area.get_staging_path(target_path)
        if target_staging_path:
            return f"ERROR：命名冲突，目标路径{target_path}已存在"
        elif not staging_area.is_deleted(target_path) and os.path.exists(target_path):
            return f"ERROR：命名冲突，目标路径{target_path}已存在"
        # 在暂存区为target_path分配一条路径
        await staging_area.register(target_path)

        # 写入一条复制记录，用于写时复制
        copy_mapping = get_copy_mapping()
        await copy_mapping.register(source_path, target_path)

        record = DiffRecord(task_id=task_id, operation_type=OperationType.CREATE_FILE, source_path=target_path)
        await DiffTable.operate(record)

        return f"文件{source_path}复制到{target_path}成功"


async def move_file(source_path: str, target_path: str):
    task_id = get_current_task_id()
    async with get_vfs_lock():
        # 检查source_path是否存在 （真实路径）
        # 禁止移动原本不存在的文件（使用虚拟路径作为source_path）
        if not os.path.exists(source_path):
            return f"ERROR：原文件{source_path}不存在/无法移动新创建的文件"

        # 检查target_path路径合法性
        result = check_file_path(target_path)
        if result:
            return result

        # 检查target_path是否存在
        staging_area = get_staging_area()
        target_staging_path = staging_area.get_staging_path(target_path)
        if target_staging_path:
            return f"ERROR：命名冲突，目标路径{target_path}已存在"
        elif not staging_area.is_deleted(target_path) and os.path.exists(target_path):
            return f"ERROR：命名冲突，目标路径{target_path}已存在"
        # 在暂存区为target_path分配一条路径
        await staging_area.register(target_path)

        # 写入一条复制记录，用于写时复制
        copy_mapping = get_copy_mapping()
        await copy_mapping.register(source_path, target_path)

        # 在暂存区中标记删除
        await staging_area.delete(source_path)

        record1 = DiffRecord(task_id=task_id, operation_type=OperationType.CREATE_FILE, source_path=target_path)
        record2 = DiffRecord(task_id=task_id, operation_type=OperationType.DELETE_FILE, source_path=source_path)

        await DiffTable.operate_batch([record1, record2])

        return f"文件{source_path}移动到{target_path}成功"


async def mkdir(path: str):
    """为了统一，这里把path作为目标路径"""
    task_id = get_current_task_id()
    async with get_vfs_lock():
        # 路径合法性检查
        result = check_dir_path(path)
        if result:
            return result

        # 检查路径是否存在
        staging_area = get_staging_area()
        source_staging_path = staging_area.get_staging_dir_path(path)
        if source_staging_path:
            return f"ERROR：命名冲突，目录{path}已存在"
        elif not staging_area.is_deleted_dir(path) and os.path.exists(path):
            return f"ERROR：命名冲突，目录{path}已存在"

        # 在暂存区为path占位
        await staging_area.register_dir(path)

        record = DiffRecord(task_id=task_id, operation_type=OperationType.MKDIR, source_path=path)
        await DiffTable.operate(record)

        return f"目录{path}创建成功"


async def delete_dir(path: str):
    task_id = get_current_task_id()
    async with get_vfs_lock():
        # 检查path是否存在 （真实路径/虚拟路径——是否已删除）
        staging_area = get_staging_area()
        staging_path = staging_area.get_staging_dir_path(path)
        if staging_path is None:
            # 检查是否被删除了
            if staging_area.is_deleted_dir(path):
                return f"ERROR：目录{path}不存在"
            # 检查原目录是否存在
            if not os.path.exists(path):
                return f"ERROR：目录{path}不存在"

        # 检查文件是否是被拷贝的对象并且未触发拷贝
        copy_mapping = get_copy_mapping()
        if copy_mapping.need_copied_dir(path):
            await copy_mapping.mark_copied_dir(path)

        # 在暂存区中删除
        await staging_area.delete_dir(path)

        record = DiffRecord(task_id=task_id, operation_type=OperationType.DELETE_DIR, source_path=path)
        await DiffTable.operate(record)

        return f"目录{path}删除成功"


async def rename_dir(source_path: str, target_path: str):
    task_id = get_current_task_id()
    async with get_vfs_lock():
        # 不允许跨目录重命名
        source_parent = str(Path(source_path).parent)
        target_parent = str(Path(target_path).parent)
        # 统一处理"."和"/"的情况
        if source_parent == "." or source_parent == "/":
            source_parent = ""
        if target_parent == "." or target_parent == "/":
            target_parent = ""

        if source_parent != target_parent:
            return f"ERROR：不支持跨目录重命名 {source_path} -> {target_path}"

        # 检查target_path路径合法性
        result = check_dir_path(target_path)
        if result:
            return result

        # 处理命名冲突，检查target_path是否存在
        staging_area = get_staging_area()
        target_staging_path = staging_area.get_staging_dir_path(target_path)
        if target_staging_path:
            return f"ERROR：命名冲突，目标目录{target_path}已存在"
        elif not staging_area.is_deleted_dir(target_path) and os.path.exists(target_path):
            return f"ERROR：命名冲突，目标目录{target_path}已存在"

        # 检查source_path是否存在 （真实路径/虚拟路径——是否已删除）
        staging_path = staging_area.get_staging_dir_path(source_path)
        if staging_path is None:
            # 检查是否被删除了
            if staging_area.is_deleted_dir(source_path):
                return f"ERROR：目录{source_path}不存在"
            # 检查原目录是否存在
            if not os.path.exists(source_path):
                return f"ERROR：目录{source_path}不存在"
            # 从暂存区获取一条路径，并拷贝原目录
            staging_path = await staging_area.register_dir(source_path)

        # 修改对应的映射关系
        await staging_area.rename_dir(source_path, target_path)
        await get_copy_mapping().rename_dir(source_path, target_path)

        record = DiffRecord(task_id=task_id, operation_type=OperationType.RENAME_DIR, source_path=source_path,
                            target_path=target_path)
        await DiffTable.operate(record)

        return f"目录{source_path}重命名为{target_path}成功"


async def copy_dir(source_path: str, target_path: str):
    task_id = get_current_task_id()
    async with get_vfs_lock():
        # 检查source_path是否存在 （真实路径）
        # 禁止拷贝原本不存在的文件（使用虚拟路径作为source_path）
        if not os.path.exists(source_path):
            return f"ERROR：目录{source_path}不存在/无法拷贝新创建的目录"

        # 检查target_path路径合法性
        result = check_dir_path(target_path)
        if result:
            return result

        # 处理命名冲突，检查target_path是否存在
        staging_area = get_staging_area()
        target_staging_path = staging_area.get_staging_dir_path(target_path)
        if target_staging_path:
            return f"ERROR：命名冲突，目标目录{target_path}已存在"
        elif not staging_area.is_deleted_dir(target_path) and os.path.exists(target_path):
            return f"ERROR：命名冲突，目标目录{target_path}已存在"
        # 在暂存区为target_path注册
        await staging_area.register_dir(target_path)

        # 写入一条复制记录，用于写时复制
        copy_mapping = get_copy_mapping()
        await copy_mapping.register_dir(source_path, target_path)

        # 递归写子目录和文件的CREATE_FILE和MKDIR操作记录
        operations = []
        for root, dirs, files in os.walk(source_path):
            # root: 当前遍历目录的完整路径      dirs: 当前目录下的子目录列表    files: 当前目录下的文件列表
            for dir_name in dirs:
                # 构造目标目录完整路径
                source_dir = os.path.join(root, dir_name)  # 原目录完整路径
                target_dir = source_dir.replace(source_path, target_path, 1)  # 目标目录完整路径

                # 在暂存区为target_dir占位
                await staging_area.register_dir(target_dir)
                operations.append(DiffRecord(task_id=task_id, operation_type=OperationType.MKDIR, source_path=target_dir))

            for file_name in files:
                # 构造目标文件完整路径
                source_file = os.path.join(root, file_name)  # 原文件完整路径
                target_file = source_file.replace(source_path, target_path, 1)  # 目标文件完整路径

                # 在暂存区为target_file分配一条路径
                await staging_area.register(target_file)
                operations.append(DiffRecord(task_id=task_id, operation_type=OperationType.CREATE_FILE, source_path=target_file))

        # 批量写入操作记录
        await DiffTable.operate_batch(operations)

        return f"目录{source_path}复制到{target_path}成功"


async def move_dir(source_path: str, target_path: str):
    task_id = get_current_task_id()
    async with get_vfs_lock():
        # 检查source_path是否存在 （真实路径）
        # 禁止拷贝原本不存在的文件（使用虚拟路径作为source_path）
        if not os.path.exists(source_path):
            return f"ERROR：目录{source_path}不存在/无法移动新创建的目录"

        # 检查target_path路径合法性
        result = check_dir_path(target_path)
        if result:
            return result

        # 处理命名冲突，检查target_path是否存在
        staging_area = get_staging_area()
        target_staging_path = staging_area.get_staging_dir_path(target_path)
        if target_staging_path:
            return f"ERROR：命名冲突，目标目录{target_path}已存在"
        elif not staging_area.is_deleted_dir(target_path) and os.path.exists(target_path):
            return f"ERROR：命名冲突，目标目录{target_path}已存在"
        # 在暂存区为target_path注册
        await staging_area.register_dir(target_path)

        # 写入一条复制记录，用于写时复制
        copy_mapping = get_copy_mapping()
        await copy_mapping.register_dir(source_path, target_path)

        # 在暂存区中删除原目录
        await staging_area.delete_dir(source_path)

        # 递归写子目录和文件的CREATE_FILE和MKDIR操作记录
        operations = [
            DiffRecord(task_id=task_id, operation_type=OperationType.MKDIR, source_path=target_path),
            DiffRecord(task_id=task_id, operation_type=OperationType.DELETE_DIR, source_path=source_path)
        ]
        for root, dirs, files in os.walk(source_path):
            # root: 当前遍历目录的完整路径      dirs: 当前目录下的子目录列表    files: 当前目录下的文件列表
            for dir_name in dirs:
                # 构造目标目录完整路径
                source_dir = os.path.join(root, dir_name)  # 原目录完整路径
                target_dir = source_dir.replace(source_path, target_path, 1)  # 目标目录完整路径

                # 在暂存区为target_dir占位
                await staging_area.register_dir(target_dir)
                operations.append(
                    DiffRecord(task_id=task_id, operation_type=OperationType.MKDIR, source_path=target_dir))

            for file_name in files:
                # 构造目标文件完整路径
                source_file = os.path.join(root, file_name)  # 原文件完整路径
                target_file = source_file.replace(source_path, target_path, 1)  # 目标文件完整路径

                # 在暂存区为target_file分配一条路径
                await staging_area.register(target_file)
                operations.append(DiffRecord(task_id=task_id, operation_type=OperationType.CREATE_FILE, source_path=target_file))

        await DiffTable.operate_batch(operations)

        return f"目录{source_path}移动到{target_path}成功"
