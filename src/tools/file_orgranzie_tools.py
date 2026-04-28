from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

import src.vfs.operations as ops

"""由于传入task_id有限制，这里的tools仅作为给agent的输入参数说明，实际上不调用"""

# ============ 输入模型 ============
class ListDirInput(BaseModel):
    source_path: str = Field(description="要查看的目录的绝对路径")

class ReadFileInput(BaseModel):
    path: str = Field(description="要读取的文件的绝对路径")

class DeleteFileInput(BaseModel):
    path: str = Field(description="要删除的文件的绝对路径")

class CreateFileInput(BaseModel):
    path: str = Field(description="要创建的文件的绝对路径")
    content: str = Field(description="要写入文件的内容")

class RenameFileInput(BaseModel):
    source_path: str = Field(description="要重命名的旧文件的绝对路径")
    target_path: str = Field(description="要重命名的新文件的绝对路径")

class ModifyFileInput(BaseModel):
    path: str = Field(description="要修改的文件的绝对路径")
    content: str = Field(description="要写入文件的内容")

class CopyFileInput(BaseModel):
    source_path: str = Field(description="要复制的源文件的绝对路径")
    target_path: str = Field(description="源文件要被复制到的目标绝对路径")

class MoveFileInput(BaseModel):
    source_path: str = Field(description="要移动的源文件的绝对路径")
    target_path: str = Field(description="源文件要被移动到的目标绝对路径")

class MkdirInput(BaseModel):
    path: str = Field(description="要创建的目录的绝对路径")

class DeleteDirInput(BaseModel):
    path: str = Field(description="要删除的目录的绝对路径")

class RenameDirInput(BaseModel):
    source_path: str = Field(description="要重命名的旧目录的绝对路径")
    target_path: str = Field(description="要重命名的新目录的绝对路径")

class CopyDirInput(BaseModel):
    source_path: str = Field(description="要复制的源目录的绝对路径")
    target_path: str = Field(description="源目录要被复制到的目标绝对路径")

class MoveDirInput(BaseModel):
    source_path: str = Field(description="要移动的源目录的绝对路径")
    target_path: str = Field(description="源目录要被移动到的目标绝对路径")

# ============ 工具定义 ============

@tool(args_schema=ListDirInput)
async def list_dir(source_path: str) -> str:
    """列出指定目录下的所有文件和子目录"""
    return ops.list_dir(source_path)

@tool(args_schema=ReadFileInput)
async def read_file(path: str) -> str:
    """读取指定文件的内容"""
    return ops.read_file(path)

@tool(args_schema=CreateFileInput)
async def create_file(path: str, content: str, _task_id: Optional[str]= None) -> str:
    """创建文件并写入内容"""
    return ops.create_file(path, content, _task_id)

@tool(args_schema=DeleteFileInput)
async def delete_file(path: str) -> str:
    """删除指定文件"""
    return ops.delete_file(path)

@tool(args_schema=RenameFileInput)
async def rename_file(old_path: str, new_path: str) -> str:
    """重命名文件，只支持在同一目录下重命名文件，不支持跨目录重命名"""
    return ops.rename_file(old_path, new_path)

@tool(args_schema=ModifyFileInput)
async def modify_file(path: str, content: str) -> str:
    """修改文件内容"""
    return ops.modify_file(path, content)

@tool(args_schema=CopyFileInput)
async def copy_file(source_path: str, target_path: str) -> str:
    """复制文件到指定目标路径"""
    return ops.copy_file(source_path, target_path)

@tool(args_schema=MoveFileInput)
async def move_file(source_path: str, target_path: str) -> str:
    """移动文件到指定目标路径"""
    return ops.move_file(source_path, target_path)

@tool(args_schema=MkdirInput)
async def mkdir(path: str) -> str:
    """创建目录"""
    return ops.mkdir(path)

@tool(args_schema=DeleteDirInput)
async def delete_dir(path: str) -> str:
    """删除目录"""
    return ops.delete_dir(path)

@tool(args_schema=RenameDirInput)
async def rename_dir(old_path: str, new_path: str) -> str:
    """重命名目录，只支持在同一目录下重命名目录，不支持跨目录重命名"""
    return ops.rename_dir(old_path, new_path)

@tool(args_schema=CopyDirInput)
async def copy_dir(source_path: str, target_path: str) -> str:
    """复制目录到指定目标路径"""
    return ops.copy_dir(source_path, target_path)

@tool(args_schema=MoveDirInput)
async def move_dir(source_path: str, target_path: str) -> str:
    """移动目录到指定目标路径"""
    return ops.move_dir(source_path, target_path)
