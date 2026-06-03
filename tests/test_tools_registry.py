import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tools.registry import registry
from src.tools.loader import discover_tools


async def test_registry():
    discover_tools()
    all_tools = registry.list_tools()
    print(f"工具总数: {len(all_tools)}")
    print(f"工具列表: {all_tools}")
    assert len(all_tools) == len(set(all_tools)), "存在重复工具名称"
    print("无重复名称: OK")

    schemas = registry.get_schemas(["list_dir", "read_file"])
    assert len(schemas) == 2
    for s in schemas:
        fn = s["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        print(f"  Schema OK: {fn['name']}")

    schemas_all = registry.get_schemas()
    print(f"全局 Schema 数: {len(schemas_all)}")

    from src.vfs.task_context import set_current_task_id, clean_current_task_id
    from src.vfs.staging_area import StagingArea
    from src.vfs.copy_mapping import CopyMapping

    set_current_task_id("test-tool-001")
    StagingArea.load("test-tool-001")
    CopyMapping.load("test-tool-001")

    test_calls = [
        {"name": "list_dir", "args": {"source_path": "."}, "id": "call_1"},
    ]
    results = await registry.dispatch(test_calls)
    assert len(results) == 1
    assert results[0]["role"] == "tool"
    assert results[0]["tool_call_id"] == "call_1"
    print(f"Dispatch OK: {results[0]['content'][:60]}...")

    bad_calls = [{"name": "nonexistent", "args": {}, "id": "call_err"}]
    results = await registry.dispatch(bad_calls)
    assert "错误" in results[0]["content"]
    print(f"错误处理 OK: {results[0]['content']}")

    StagingArea.clear()
    CopyMapping.clear()
    clean_current_task_id()
    print("清理 OK")

    from langchain_openai import ChatOpenAI
    from src.config import MODEL, DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY
    model = registry.bind_tools(ChatOpenAI(model=MODEL, base_url=DEEPSEEK_BASE_URL, api_key=DEEPSEEK_API_KEY), ["list_dir"])
    print(f"模型绑定 OK: {type(model).__name__}")

    lc_tool = registry.to_langchain_tool("list_dir")
    assert lc_tool.name == "list_dir"
    assert lc_tool.description == "列出指定目录下的所有文件和子目录"
    print(f"LangChain 转换 OK: {lc_tool.name}")

    print("\n所有测试通过!")


if __name__ == "__main__":
    asyncio.run(test_registry())
