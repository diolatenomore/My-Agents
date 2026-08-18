import asyncio
import inspect
import threading
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel

from src.utils.common import logger


class ToolEntry:
    """Metadata for a single registered tool."""

    def __init__(self, name, description, schema, handler, requires_approval=False):
        self.name = name
        self.description = description
        self.schema = schema
        self.handler = handler
        self.requires_approval = requires_approval


def _clean_prop(prop: dict, defs: dict) -> dict:
    """递归清理单个属性，解析 $ref 和嵌套对象/数组"""
    # 解析 $ref 引用
    if "$ref" in prop:
        ref_path = prop["$ref"]
        ref_name = ref_path.split("/")[-1]
        if ref_name in defs:
            return _clean_prop(defs[ref_name], defs)

    cleaned = {"type": prop.get("type", "string")}

    if "description" in prop:
        cleaned["description"] = prop["description"]
    if "enum" in prop:
        cleaned["enum"] = prop["enum"]

    # 递归处理嵌套对象
    if prop.get("type") == "object" and "properties" in prop:
        cleaned["properties"] = {
            k: _clean_prop(v, defs)
            for k, v in prop["properties"].items()
        }
        if "required" in prop:
            cleaned["required"] = prop["required"]

    # 递归处理数组的 items
    if prop.get("type") == "array" and "items" in prop:
        cleaned["items"] = _clean_prop(prop["items"], defs)

    return cleaned


def _pydantic_to_openai_params(model: Type[BaseModel]) -> Dict[str, Any]:
    """将 Pydantic BaseModel 转换为 OpenAI Function Calling 的 parameters"""
    schema = model.model_json_schema()
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    defs = schema.get("$defs", {})

    cleaned_properties = {}
    for name, prop in properties.items():
        cleaned_properties[name] = _clean_prop(prop, defs)

    return {
        "type": "object",
        "properties": cleaned_properties,
        "required": required,
    }


def _infer_params_from_fn(fn: Callable) -> Dict[str, Any]:
    """从函数签名推断参数 schema"""
    sig = inspect.signature(fn)
    properties = {}
    required = []
    for name, param in sig.parameters.items():
        if name in ("self", "cls", "return"):
            continue
        properties[name] = {"type": "string", "description": f"参数 {name}"}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


class ToolRegistry:
    """工具注册中心 — 单例，仿 Hermes 的自注册模式"""

    def __init__(self):
        self._tools: Dict[str, ToolEntry] = {}
        self._lock = threading.RLock()

    def register(
        self,
        name: str,
        description: str,
        handler: Callable,
        parameters: Optional[Dict[str, Any]] = None,
        args_schema: Optional[Type[BaseModel]] = None,
        requires_approval: bool = False,
    ):
        """注册一个工具

        Args:
            name: 工具名称（必须唯一，与 LLM tool_call 中的 name 匹配）
            description: 工具描述（LLM 据此决定是否调用）
            handler: 处理函数（同步或异步，接收 **kwargs，返回字符串）
            parameters: OpenAI 格式的 parameters dict（与 args_schema 二选一）
            args_schema: Pydantic BaseModel，自动转为 parameters
            requires_approval: 执行前是否需要用户审批
        """
        with self._lock:
            if name in self._tools:
                logger.warning(f"工具 '{name}' 重复注册，将被覆盖")

            if parameters is None and args_schema is not None:
                parameters = _pydantic_to_openai_params(args_schema)
            elif parameters is None:
                parameters = _infer_params_from_fn(handler)

            self._tools[name] = ToolEntry(
                name=name,
                description=description,
                schema=parameters,
                handler=handler,
                requires_approval=requires_approval,
            )
            logger.debug(f"工具已注册: {name}")

    def get(self, name: str) -> Optional[ToolEntry]:
        with self._lock:
            return self._tools.get(name)

    def requires_approval(self, name: str) -> bool:
        """检查工具是否需要用户审批"""
        entry = self._tools.get(name)
        return entry.requires_approval if entry else False

    def list_tools(self) -> List[str]:
        with self._lock:
            return list(self._tools.keys())

    def get_all_schemas(self) -> List[Dict[str, Any]]:
        """获取所有工具的 OpenAI Function Calling 格式定义"""
        return self.get_schemas()

    def get_schemas(self, names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """获取 OpenAI Function Calling 格式的工具定义列表

        Args:
            names: 只返回指定名称的工具，None 表示全部
        """
        with self._lock:
            if names is None:
                entries = list(self._tools.values())
            else:
                entries = [self._tools[n] for n in names if n in self._tools]

            return [
                {
                    "type": "function",
                    "function": {
                        "name": e.name,
                        "description": e.description,
                        "parameters": e.schema,
                    },
                }
                for e in entries
            ]

    def bind_tools(self, model, names: Optional[List[str]] = None):
        """绑定工具到 LangChain 模型"""
        return model.bind_tools(self.get_schemas(names))

    async def dispatch(self, name: str, args: Dict[str, Any]) -> str:
        """执行单个工具调用

        Args:
            name: 工具名称
            args: 工具参数字典

        Returns:
            工具执行结果字符串
        """
        with self._lock:
            entry = self._tools.get(name)

        if not entry:
            return f"错误：找不到工具 '{name}'"

        try:
            handler = entry.handler
            if inspect.iscoroutinefunction(handler):
                observation = await handler(**args)
            else:
                observation = await asyncio.to_thread(lambda: handler(**args))
            return str(observation)
        except Exception as e:
            logger.error(f"工具 '{name}' 执行失败: {e}", exc_info=True)
            return f"工具 '{name}' 执行失败: {str(e)}"



# 全局单例
registry = ToolRegistry()
