"""工具加载器 — 触发所有工具模块的 self-register

在应用启动时调用 discover_tools()，确保所有工具完成注册。
遵循 Hermes 模式：import 即注册。
"""

from src.utils.common import logger


def discover_tools():
    """发现并加载所有工具模块"""
    logger.info("开始加载工具模块...")

    import src.tools.vfs_tools  # noqa: F401
    import src.tools.skill_tools  # noqa: F401
    import src.tools.web_tools  # noqa: F401
    import src.tools.execute_tools  # noqa: F401
    import src.tools.memory_tools  # noqa: F401
    import src.tools.subagent  # noqa: F401
    import src.tools.todo_tools  # noqa: F401

    logger.info(f"工具加载完成：共 {len(list_tools())} 个工具")


def list_tools() -> list:
    """返回已注册的工具名称列表"""
    from src.tools.registry import registry
    return registry.list_tools()
