from typing import Any
from src.tools.base import Tool
from src.vfs.operations import read_file, create_file, delete_file, rename_file, modify_file, copy_file, move_file, mkdir, delete_dir, rename_dir, copy_dir, move_dir

class FileTools(Tool):
    """文件操作工具"""
    # TODO 待修改
    def __init__(self):
        super().__init__("file_tools", "文件操作工具，包括创建、读取、修改、删除文件等操作")
    
    def run(self, operation: str, **kwargs) -> Any:
        """运行文件操作
        
        Args:
            operation: 操作类型，包括 read_file, create_file, delete_file, rename_file, modify_file, copy_file, move_file, mkdir, delete_dir, rename_dir, copy_dir, move_dir
            **kwargs: 操作参数
        """
        if operation == "read_file":
            return read_file(kwargs.get("source_path"))
        elif operation == "create_file":
            return create_file(kwargs.get("source_path"), kwargs.get("content"))
        elif operation == "delete_file":
            return delete_file(kwargs.get("source_path"))
        elif operation == "rename_file":
            return rename_file(kwargs.get("source_path"), kwargs.get("target_path"))
        elif operation == "modify_file":
            return modify_file(kwargs.get("source_path"), kwargs.get("content"))
        elif operation == "copy_file":
            return copy_file(kwargs.get("source_path"), kwargs.get("target_path"))
        elif operation == "move_file":
            return move_file(kwargs.get("source_path"), kwargs.get("target_path"))
        elif operation == "mkdir":
            return mkdir(kwargs.get("source_path"))
        elif operation == "delete_dir":
            return delete_dir(kwargs.get("source_path"))
        elif operation == "rename_dir":
            return rename_dir(kwargs.get("source_path"), kwargs.get("target_path"))
        elif operation == "copy_dir":
            return copy_dir(kwargs.get("source_path"), kwargs.get("target_path"))
        elif operation == "move_dir":
            return move_dir(kwargs.get("source_path"), kwargs.get("target_path"))
        else:
            return f"不支持的操作: {operation}"