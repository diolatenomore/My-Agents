"""工具加载器 — 触发所有工具模块的 self-register

在应用启动时调用 discover_tools()，确保所有工具完成注册。
遵循 Hermes 模式：import 即注册。
"""

from src.utils.common import logger


def discover_tools():
    """发现并加载所有工具模块"""
    logger.info("开始加载工具模块...")
    registered_before = len(list_tools())

    import src.tools.vfs_tools  # noqa: F401
    import src.tools.skill_tools  # noqa: F401

    registered_after = len(list_tools())
    new_count = registered_after - registered_before
    logger.info(f"工具加载完成：共 {registered_after} 个工具（新增 {new_count} 个）")


def list_tools() -> list:
    """返回已注册的工具名称列表"""
    from src.tools.registry import registry
    return registry.list_tools()
