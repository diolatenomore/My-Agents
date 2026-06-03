from src.vfs.staging_area import StagingArea
from src.vfs.operations import list_dir
from src.vfs.diff_table import DiffTable


# 打印操作树
def print_operation_tree(tree, indent=0):
    """递归打印操作树"""
    prefix = "  " * indent
    print(f"{prefix}路径: {tree.path}")

    # 打印目录操作
    if tree.dir_operation:
        print(f"{prefix}  目录操作: {tree.dir_operation.operation_type.value}")
        print(f"{prefix}    源路径: {tree.dir_operation.source_path}")
        if tree.dir_operation.target_path:
            print(f"{prefix}    目标路径: {tree.dir_operation.target_path}")

    # 打印文件操作
    if tree.file_operations:
        print(f"{prefix}  文件操作:")
        for file_path, ops in tree.file_operations.items():
            print(f"{prefix}    {file_path}:")
            for op in ops:
                print(f"{prefix}      - {op.operation_type.value}")
                print(f"{prefix}        源路径: {op.source_path}")
                if op.target_path:
                    print(f"{prefix}        目标路径: {op.target_path}")

    # 递归打印子目录
    if tree.sub_groups:
        print(f"{prefix}  子目录:")
        for sub_path, sub_tree in tree.sub_groups.items():
            print_operation_tree(sub_tree, indent + 3)


StagingArea.load("d43a4891-824c-41e5-81f4-292f53c1d151")
result = list_dir("/Users/tinklingowl/PycharmProjects/AI-Agents/tests/dir_for_test_file_organize")
print(result)
# ops = DiffTable.list("d43a4891-824c-41e5-81f4-292f53c1d151")
# tree = DiffTable.merge(ops)
#
# print_operation_tree(tree)