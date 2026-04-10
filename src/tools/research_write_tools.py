import os
from langchain_core.tools import tool
from tavily import TavilyClient

from config import AGENT_WORKSPACE_PATH


@tool
async def tavily_search(query: str, max_results: int = 5) -> str:
    """使用 Tavily 搜索引擎查找最新信息"""
    print(f"tavily_search:{query}")
    tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    result = tavily.search(query=query, max_results=max_results)
    return str(result)


@tool
async def write_file(filepath: str, content: str, append: bool = False) -> str:
    """将结果写入文件"""
    print(f"write_file {filepath} {append}....")
    filepath = f"{AGENT_WORKSPACE_PATH}/{filepath}"
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    mode = "a" if append else "w"
    with open(filepath, mode, encoding="utf-8") as f:
        f.write(content)

    return f"✅ 已写入 {filepath}，共 {len(content)} 字"

@tool
async def read_file(filepath: str) -> str:
    """读取文件内容"""
    print(f"read_file {filepath}....")
    try:
        with open(f"{AGENT_WORKSPACE_PATH}/{filepath}", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"错误：文件不存在"
    except Exception as e:
        return f"读取失败：{str(e)}"

