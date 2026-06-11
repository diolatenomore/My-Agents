"""文件整理工具 — VFS 文件操作

每个工具在模块导入时通过 registry.register() 自注册。
遵循 Hermes 模式：schema + handler 同文件定义。
"""

from pydantic import BaseModel, Field

import src.vfs.operations as ops
from src.tools.registry import registry

# ============ 输入模型 ============

class ListDirInput(BaseModel):
    source_path: str = Field(description="要查看的目录的绝对路径")

class ReadFileInput(BaseModel):
    path: str = Field(description="要读取的文件的绝对路径")

class CreateFileInput(BaseModel):
    path: str = Field(description="要创建的文件的绝对路径")
    content: str = Field(description="要写入文件的内容")

class DeleteFileInput(BaseModel):
    path: str = Field(description="要删除的文件的绝对路径")

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

# ============ 注册工具 ============

registry.register(
    name="list_dir",
    description="列出指定目录下的所有文件和子目录",
    handler=ops.list_dir,
    args_schema=ListDirInput,
)

registry.register(
    name="read_file",
    description="读取指定文件的内容",
    handler=ops.read_file,
    args_schema=ReadFileInput,
)

registry.register(
    name="create_file",
    description="创建文件并写入内容",
    handler=ops.create_file,
    args_schema=CreateFileInput,
)

registry.register(
    name="delete_file",
    description="删除指定文件",
    handler=ops.delete_file,
    args_schema=DeleteFileInput,
)

registry.register(
    name="rename_file",
    description="重命名文件，只支持在同一目录下重命名文件，不支持跨目录重命名",
    handler=ops.rename_file,
    args_schema=RenameFileInput,
)

registry.register(
    name="modify_file",
    description="修改文件内容",
    handler=ops.modify_file,
    args_schema=ModifyFileInput,
)

registry.register(
    name="copy_file",
    description="复制文件到指定目标路径",
    handler=ops.copy_file,
    args_schema=CopyFileInput,
)

registry.register(
    name="move_file",
    description="移动文件到指定目标路径",
    handler=ops.move_file,
    args_schema=MoveFileInput,
)

registry.register(
    name="mkdir",
    description="创建目录",
    handler=ops.mkdir,
    args_schema=MkdirInput,
)

registry.register(
    name="delete_dir",
    description="删除指定目录",
    handler=ops.delete_dir,
    args_schema=DeleteDirInput,
)

registry.register(
    name="rename_dir",
    description="重命名目录，只支持在同一目录下重命名目录，不支持跨目录重命名",
    handler=ops.rename_dir,
    args_schema=RenameDirInput,
)

registry.register(
    name="copy_dir",
    description="复制目录到指定目标路径",
    handler=ops.copy_dir,
    args_schema=CopyDirInput,
)

registry.register(
    name="move_dir",
    description="移动目录到指定目标路径",
    handler=ops.move_dir,
    args_schema=MoveDirInput,
)
