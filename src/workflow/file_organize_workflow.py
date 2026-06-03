from typing import Any, Callable, Dict, Tuple, Optional

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph
from langgraph.constants import END

from src.agents.file_organize_prompt import PLAN_AGENT_PROMPT, EXECUTE_AGENT_PROMPT, VERIFY_AGENT_PROMPT, \
    PLAN_INPUT_TEMPLATE, EXECUTE_INPUT_TEMPLATE, VERIFY_INPUT_PROMPT
from src.config import MODEL, DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY
from src.models.state import FileOrganizeState
from src.models.task import Task
from src.tools.registry import registry
from src.utils.common import logger
from src.vfs.task_context import set_current_task_id, clean_current_task_id
from src.vfs.copy_mapping import CopyMapping
from src.vfs.staging_area import StagingArea
from src.vfs.task_context import get_task_id_with_no_error


PLAN_TOOLS = ["list_dir", "read_file"]
EXECUTE_TOOLS = [
    "create_file", "delete_file", "rename_file", "modify_file",
    "copy_file", "move_file", "mkdir", "delete_dir", "copy_dir",
    "rename_dir", "move_dir", "list_dir", "read_file",
]
VERIFY_TOOLS = ["list_dir", "read_file"]


def create_file_organize_graph(task: Task) -> Tuple[StateGraph, Dict[str, Any], Optional[Callable], Optional[Callable]]:
    def _init():
        """初始化函数"""
        set_current_task_id(task.task_id)
        StagingArea.load(task.task_id)
        CopyMapping.load(task.task_id)

    def _cleanup():
        """资源清理函数"""
        current_task_id = get_task_id_with_no_error()
        # 只有运行时task_id等于当前task_id才清理，避免错删
        if current_task_id == task.task_id:
            StagingArea.clear()
            CopyMapping.clear()
            clean_current_task_id()

    async def plan_node(state: FileOrganizeState) -> FileOrganizeState:
        model = ChatOpenAI(model=MODEL, base_url=DEEPSEEK_BASE_URL, api_key=DEEPSEEK_API_KEY)
        model_with_tools = model.bind_tools(registry.get_schemas(PLAN_TOOLS))

        # 初始化消息列表
        messages = state.get("messages", [])
        if not messages:
            messages = [
                SystemMessage(content=PLAN_AGENT_PROMPT),
                HumanMessage(content=PromptTemplate.from_template(PLAN_INPUT_TEMPLATE).format(query=state["query"]))
            ]

        response = await model_with_tools.ainvoke(messages)

        if response.tool_calls:
            return {"messages": messages + [response], "step": state["step"] + 1}

        # 无需再调用工具时，手动清空 messages，因为下个阶段的agent无需知道本阶段的对话
        logger.info(f"plan输出:{response.content}")
        return {
            "messages": [],  # 手动清空
            "step": state["step"] + 1,
            "plan_result": response.content
        }

    async def plan_tool_node(state: FileOrganizeState) -> FileOrganizeState:
        result = []
        for tool_call in state["messages"][-1].tool_calls:
            observation = registry.dispatch(tool_call["name"], tool_call["args"])
            result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"]))
            logger.info(f"plan阶段  工具: {tool_call['name']}    参数: {tool_call['args']}")
            logger.info(f"工具返回：{observation}")
        return {"messages": state["messages"] + result, "step": state["step"] + 1}

    def should_continue_plan(state: FileOrganizeState):
        if state.get("plan_result"):
            return "execute"
        return "plan_tool_node"

    async def execute_node(state: FileOrganizeState) -> FileOrganizeState:
        model = ChatOpenAI(model=MODEL, base_url=DEEPSEEK_BASE_URL, api_key=DEEPSEEK_API_KEY)
        model_with_tools = model.bind_tools(registry.get_schemas(EXECUTE_TOOLS))

        # 初始化消息列表
        messages = state.get("messages", [])
        if not messages:
            messages = [
                SystemMessage(content=EXECUTE_AGENT_PROMPT),
                HumanMessage(content=PromptTemplate.from_template(EXECUTE_INPUT_TEMPLATE).format(
                    execute_plan=state["plan_result"] if not state.get("verify_result") else state["verify_result"]))
            ]

        response = await model_with_tools.ainvoke(messages)

        if response.tool_calls:
            return {"messages": messages + [response], "step": state["step"] + 1, "execute_result": None, "verify_result": None}

        # 无需再调用工具时，手动清空 messages，因为下个阶段的agent无需知道本阶段的对话
        logger.info(f"execute输出:{response.content}")
        return {
            "messages": [],  # 手动清空
            "step": state["step"] + 1,
            "execute_result": response.content
        }

    async def execute_tool_node(state: FileOrganizeState) -> FileOrganizeState:
        result = []
        for tool_call in state["messages"][-1].tool_calls:
            observation = registry.dispatch(tool_call["name"], tool_call["args"])
            result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"]))
            logger.info(f"execute阶段  工具: {tool_call['name']}    参数: {tool_call['args']}")
            logger.info(f"工具返回{observation}")
        return {"messages": state["messages"] + result, "step": state["step"] + 1}

    def should_continue_execute(state: FileOrganizeState):
        if state.get("execute_result") and state["execute_result"]:
            return "verify"
        return "execute_tool_node"

    async def verify_node(state: FileOrganizeState) -> FileOrganizeState:
        model = ChatOpenAI(model=MODEL, base_url=DEEPSEEK_BASE_URL, api_key=DEEPSEEK_API_KEY)
        model_with_tools = model.bind_tools(registry.get_schemas(VERIFY_TOOLS))

        # 初始化消息列表
        messages = state.get("messages", [])
        if not messages:
            messages = [
                SystemMessage(content=VERIFY_AGENT_PROMPT),
                HumanMessage(content=PromptTemplate.from_template(VERIFY_INPUT_PROMPT)
                             .format(query=state["query"], execute_result=state["execute_result"]))
            ]

        response = await model_with_tools.ainvoke(messages)

        if response.tool_calls:
            return {"messages": messages + [response], "step": state["step"] + 1}

        # 无需再调用工具时，手动清空 messages，因为下个阶段的agent无需知道本阶段的对话
        logger.info(f"verify输出:{response.content}")
        return {
            "messages": [],  # 手动清空
            "step": state["step"] + 1,
            "verify_result": response.content
        }

    async def verify_tool_node(state: FileOrganizeState) -> FileOrganizeState:
        result = []
        for tool_call in state["messages"][-1].tool_calls:
            observation = registry.dispatch(tool_call["name"], tool_call["args"])
            result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"]))
            logger.info(f"verify阶段  工具: {tool_call['name']}    参数: {tool_call['args']}")
            logger.info(f"工具返回：{observation}")
        return {"messages": state["messages"] + result, "step": state["step"] + 1}

    def should_continue_verify(state: FileOrganizeState):
        if state.get("verify_result") and state["verify_result"]:
            # 简单判断验证结果
            if "banana" in str(state["verify_result"]) or "Banana" in str(state["verify_result"]):
                return "end"
            else:
                return "execute"

        return "verify_tool_node"

    workflow = StateGraph(FileOrganizeState)
    workflow.add_node("plan", plan_node)
    workflow.add_node("plan_tool_node", plan_tool_node)
    workflow.add_node("execute", execute_node)
    workflow.add_node("execute_tool_node", execute_tool_node)
    workflow.add_node("verify", verify_node)
    workflow.add_node("verify_tool_node", verify_tool_node)

    workflow.set_entry_point("plan")
    workflow.add_conditional_edges(
        "plan",
        should_continue_plan,
        {
            "plan_tool_node": "plan_tool_node",
            "execute": "execute"
        }
    )
    workflow.add_edge("plan_tool_node", "plan")
    workflow.add_conditional_edges(
        "execute",
        should_continue_execute,
        {
            "execute_tool_node": "execute_tool_node",
            "verify": "verify"
        }
    )
    workflow.add_edge("execute_tool_node", "execute")
    workflow.add_conditional_edges(
        "verify",
        should_continue_verify,
        {
            "verify_tool_node": "verify_tool_node",
            "execute": "execute",
            "end": END
        }
    )
    workflow.add_edge("verify_tool_node", "verify")

    initial_state = {
        "task_id": task.task_id,
        "messages": [],
        "query": task.query,
        "step": 0,
        "plan_result": None,
        "execute_completed": False,
        "verify_result": None,
    }

    return workflow, initial_state, _init, _cleanup
