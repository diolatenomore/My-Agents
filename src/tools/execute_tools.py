"""执行工具 — shell 命令执行

用于运行 skills 中的 scripts，以及通用的 shell 命令。
每个工具在模块导入时通过 registry.register() 自注册。
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from src.tools.registry import registry

# 项目根目录，用于解析相对 cwd（无论进程从哪启动，. 始终 = 项目根）
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
# 确保是目錄
if not os.path.isdir(_PROJECT_ROOT):
    raise RuntimeError(f"项目根目录不存在: {_PROJECT_ROOT}")


class ExecuteInput(BaseModel):
    command: str = Field(
        description=(
            "要执行的 shell 命令。请使用当前平台适用的命令格式。"
            "Windows 下为 cmd.exe 命令（如 dir、type、date /T），"
            "如需 PowerShell 命令请使用 powershell -Command \"...\"。"
        )
    )
    cwd: str = Field(
        default=".",
        description=(
            "命令的工作目录。执行 skill 脚本时，应设为 skills/<skill-name>，如 'skills/file-organize'"
        ),
    )
    timeout: int = Field(
        default=60,
        description=(
            "命令超时秒数。请根据任务类型估算，上限为600秒。"
        ),
    )


def _resolve_cwd(cwd: str) -> str:
    """将相对 cwd 解析为绝对路径（相对于项目根目录）"""
    if os.path.isabs(cwd):
        return cwd
    resolved = os.path.normpath(os.path.join(_PROJECT_ROOT, cwd))
    if not os.path.isdir(resolved):
        return resolved  # 目录不存在也返回，让 subprocess 报错
    return resolved


def _format_output(stdout: bytes, stderr: bytes) -> str:
    """将 stdout/stderr 格式化为字符串，超长时保留头尾"""
    output = ""
    if stdout:
        output += stdout.decode() if isinstance(stdout, bytes) else stdout
    if stderr:
        stderr_text = stderr.decode() if isinstance(stderr, bytes) else stderr
        if output:
            output += "\n--- stderr ---\n"
        output += stderr_text

    if not output:
        return ""

    _HEAD_KEEP = 2000
    _TAIL_KEEP = 3000
    _MAX_KEEP = _HEAD_KEEP + _TAIL_KEEP
    if len(output) > _MAX_KEEP:
        skipped = len(output) - _MAX_KEEP
        output = output[:_HEAD_KEEP] + f"\n...(中间省略 {skipped} 字符)...\n" + output[-_TAIL_KEEP:]
    return output


async def execute(
    command: str,
    cwd: str = ".",
    timeout: int = 60,
    _cancel_event: Optional[asyncio.Event] = None,
) -> str:
    """执行 shell 命令并返回 stdout + stderr

    用于运行 skill 附带的脚本（Python、Shell、Node.js 等），
    安装依赖（pip install），或调用外部 CLI 工具（curl、jq 等）。

    注意：不同平台命令格式不同，请使用当前平台适用的命令。
    当前平台：{os_name}（Shell: {shell_name}）。

    Args:
        command: shell 命令
        cwd: 工作目录
        timeout: 超时秒数，会被硬限制在 600 秒以内
        _cancel_event: 取消事件，由主循环注入，单工具场景下用于中断长时间命令

    Returns:
        命令的 stdout + stderr 输出（超长截断到 5000 字符）
    """.format(
        os_name="Windows" if sys.platform == "win32" else "macOS/Linux",
        shell_name="cmd.exe" if sys.platform == "win32" else "bash/sh",
    )
    # cwd 的相对路径始终相对于项目根目录解析，不依赖进程的当前工作目录。
    cwd = _resolve_cwd(cwd)
    timeout = max(timeout, 5)
    timeout = min(timeout, 600)  # 硬上限 600 秒，防止 LLM 传离谱值
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        try:
            # 三路竞速：进程完成 / 超时 / 用户取消
            communicate_task = asyncio.create_task(proc.communicate())
            wait_tasks = [communicate_task]
            if _cancel_event:
                cancel_task = asyncio.create_task(_cancel_event.wait())
                wait_tasks.append(cancel_task)

            done, pending = await asyncio.wait(
                wait_tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()

            if communicate_task in done:
                stdout, stderr = communicate_task.result()
            elif not done:
                # 超时：先 kill 再 communicate 拿缓冲中的输出
                proc.kill()
                stdout, stderr = await proc.communicate()
                partial = _format_output(stdout, stderr)
                if partial:
                    return f"命令超时 ({timeout}s): {command[:100]}\n\n--- 超时前输出 ---\n{partial}"
                return f"命令超时 ({timeout}s): {command[:100]}"
            else:
                # cancel_event 被触发
                proc.kill()
                stdout, stderr = await proc.communicate()
                partial = _format_output(stdout, stderr)
                if partial:
                    return f"命令被用户中断\n\n--- 中断前输出 ---\n{partial}"
                return "命令被用户中断"

        except asyncio.CancelledError:
            # 多工具场景：被 task.cancel() 取消
            proc.kill()
            stdout, stderr = await proc.communicate()
            partial = _format_output(stdout, stderr)
            if partial:
                return f"命令被用户中断\n\n--- 中断前输出 ---\n{partial}"
            return "命令被用户中断"

        output = _format_output(stdout, stderr)
        return output or "(命令执行完毕，无输出)"

    except Exception as e:
        return f"命令执行失败: {e}"


# ============ 注册工具 ============

_current_os = "Windows" if sys.platform == "win32" else "macOS/Linux"
registry.register(
    name="execute",
    description=(
        f"在终端中执行 shell 命令（当前平台：{_current_os}）。"
        "用于运行 skill 附带的脚本（scripts/ 目录）、"
        "安装依赖（pip install）、调用外部 CLI（curl、jq、python 等）。"
        "执行 skill 脚本时，请将 cwd 设为 skills/<skill-name>。"
    ),
    handler=execute,
    args_schema=ExecuteInput,
    requires_approval=True,
)
