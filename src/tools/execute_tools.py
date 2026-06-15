"""执行工具 — shell 命令执行

用于运行 skills 中的 scripts，以及通用的 shell 命令。
每个工具在模块导入时通过 registry.register() 自注册。
"""

import os
import subprocess

from pydantic import BaseModel, Field

from src.tools.registry import registry


class ExecuteInput(BaseModel):
    command: str = Field(
        description=(
            "要执行的 shell 命令。示例: 'pip install -r requirements.txt'、"
            "'python scripts/batch_rename.py --help'、'curl -s https://example.com/api'"
        )
    )
    cwd: str = Field(
        default=".",
        description="命令的工作目录。默认为项目根目录。执行 skill 脚本时，应设为 skills/<skill-name>",
    )
    timeout: int = Field(
        default=60,
        description="命令超时秒数，默认 60 秒。长时间运行的命令应设置更高",
    )


def execute(command: str, cwd: str = ".", timeout: int = 60) -> str:
    """执行 shell 命令并返回 stdout + stderr

    用于运行 skill 附带的脚本（Python、Shell、Node.js 等），
    安装依赖（pip install），或调用外部 CLI 工具（curl、jq 等）。

    Args:
        command: shell 命令
        cwd: 工作目录
        timeout: 超时秒数

    Returns:
        命令的 stdout + stderr 输出（超长截断到 5000 字符）
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env={**os.environ},
        )

        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            if output:
                output += "\n--- stderr ---\n"
            output += result.stderr

        if not output:
            output = "(命令执行完毕，无输出)"

        # 截断超长输出
        max_len = 5000
        if len(output) > max_len:
            output = output[:max_len] + f"\n...(截断，原长度 {len(output)} 字符)"

        return output

    except subprocess.TimeoutExpired:
        return f"命令超时 ({timeout}s): {command[:100]}"
    except Exception as e:
        return f"命令执行失败: {e}"


# ============ 注册工具 ============

registry.register(
    name="execute",
    description=(
        "在终端中执行 shell 命令。用于运行 skill 附带的脚本（scripts/ 目录）、"
        "安装依赖（pip install）、调用外部 CLI（curl、jq、python 等）。"
        "执行 skill 脚本时，请将 cwd 设为 skills/<skill-name>。"
    ),
    handler=execute,
    args_schema=ExecuteInput,
)
