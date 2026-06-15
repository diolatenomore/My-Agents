"""网络工具 — web_request 和 web_search

每个工具在模块导入时通过 registry.register() 自注册。
"""

import json
import os
from typing import Optional

import httpx
from pydantic import BaseModel, Field
from tavily import AsyncTavilyClient

from src.tools.registry import registry

# 支持的 HTTP 方法
SUPPORTED_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]


# ============ web_request ============

class WebRequestInput(BaseModel):
    url: str = Field(description="目标 URL 地址")
    method: str = Field(
        default="GET",
        description=f"HTTP 方法，可选: {', '.join(SUPPORTED_METHODS)}",
    )
    headers: Optional[dict] = Field(
        default=None,
        description="可选的 HTTP 请求头，如 {\"Authorization\": \"Bearer xxx\"}",
    )
    body: Optional[str] = Field(
        default=None,
        description="可选的请求体。POST/PUT/PATCH 时使用，JSON 字符串",
    )
    timeout: int = Field(default=15, description="请求超时秒数，默认 15 秒")


async def web_request(
    url: str,
    method: str = "GET",
    headers: Optional[dict] = None,
    body: Optional[str] = None,
    timeout: int = 15,
) -> str:
    """通用 HTTP 请求，支持 GET/POST/PUT/DELETE/PATCH
    用于抓取网页、调用 REST API、提交数据等。

    Returns:
        响应文本内容（超长自动截断到 8000 字符）
    """
    method_upper = method.upper()
    if method_upper not in SUPPORTED_METHODS:
        return f"不支持的 HTTP 方法: {method}，可选: {', '.join(SUPPORTED_METHODS)}"

    if headers is None:
        headers = {}
    headers.setdefault("User-Agent", "AI-Agent/1.0")  # 避免被服务器拒绝

    if body is not None and method_upper in ("POST", "PUT", "PATCH"):
        if "content-type" not in (k.lower() for k in headers):
            headers["Content-Type"] = "application/json"

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.request(method_upper, url, headers=headers, content=body)
            resp.raise_for_status()

            content = resp.text
            content_type = resp.headers.get("content-type", "")
            if "json" in content_type:
                try:
                    content = json.dumps(resp.json(), ensure_ascii=False, indent=2)
                except (json.JSONDecodeError, ValueError):
                    pass

            max_len = 8000
            if len(content) > max_len:
                content = content[:max_len] + f"\n...(截断，原长度 {len(content)} 字符)"

            return content

        except httpx.TimeoutException:
            return f"请求超时 ({timeout}s): {method_upper} {url}"
        except httpx.ConnectError as e:
            return f"连接失败: {url} - {e}"
        except httpx.HTTPStatusError as e:
            return f"HTTP 错误 ({e.response.status_code}): {method_upper} {url}"
        except Exception as e:
            return f"请求失败: {method_upper} {url} - {e}"


# ============ web_search ============

class WebSearchInput(BaseModel):
    query: str = Field(description="搜索关键词")
    max_results: int = Field(default=5, description="最大返回结果数，默认 5")


async def web_search(query: str, max_results: int = 5) -> str:
    """使用 Tavily 搜索引擎查找最新信息"""
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return "Tavily API key 未配置，请设置环境变量 TAVILY_API_KEY"
    try:
        async with AsyncTavilyClient(api_key=api_key) as client:
            result = await client.search(query=query, max_results=max_results)
            return str(result)
    except Exception as e:
        return f"搜索失败: {e}"


# ============ 注册工具 ============

registry.register(
    name="web_request",
    description=(
        "发起 HTTP 请求（类 curl），支持 GET/POST/PUT/DELETE/PATCH。"
        "用于抓取网页、调用 REST API、提交 JSON 数据等。"
    ),
    handler=web_request,
    args_schema=WebRequestInput,
)

registry.register(
    name="web_search",
    description="搜索网页获取最新信息。",
    handler=web_search,
    args_schema=WebSearchInput,
)
