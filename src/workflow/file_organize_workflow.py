from typing import Any, Dict, Tuple

from langchain_community.chat_models import ChatTongyi
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.prompts import PromptTemplate
from langgraph.graph import StateGraph
from langgraph.constants import END

from agents.file_organize_prompt import PLAN_AGENT_PROMPT, EXECUTE_AGENT_PROMPT, VERIFY_AGENT_PROMPT, \
    PLAN_INPUT_TEMPLATE, EXECUTE_INPUT_TEMPLATE
from config import MODEL
from models.state import FileOrganizeState
from models.task import Task
from tools.file_orgranzie_tools import (list_dir, read_file, create_file, delete_file,
                                        rename_file, modify_file, copy_file, move_file, mkdir,
                                        delete_dir, copy_dir, rename_dir, move_dir)
import src.vfs.operations as ops
from src.utils.common import logger
from src.vfs.context_manager import set_current_task_id
from src.vfs.copy_mapping import get_copy_mapping
from src.vfs.staging_area import get_staging_area


# TODO 不同agent的messages应该不同
# 方法1: 使用独立字段xxxx_messages
# 方法2: 每个阶段后清空messages
# 方法3: 使用子图（checkpoint比较复杂）

# TODO 提示词待完善

# 实际调用的函数
tools_by_name = {
    "list_dir": ops.list_dir,
    "read_file": ops.read_file,
    "create_file": ops.create_file,
    "delete_file": ops.delete_file,
    "rename_file": ops.rename_file,
    "modify_file": ops.modify_file,
    "copy_file": ops.copy_file,
    "move_file": ops.move_file,
    "mkdir": ops.mkdir,
    "delete_dir": ops.delete_dir,
    "rename_dir": ops.rename_dir,
    "copy_dir": ops.copy_dir,
    "move_dir": ops.move_dir,
}



#TODO 最后需要清空当前task_id
def create_file_organize_graph(task: Task) -> Tuple[StateGraph, Dict[str, Any]]:
    # 设置task_id并初始化
    set_current_task_id(task.task_id)
    staging_area = get_staging_area()
    staging_area.load(task.task_id)
    copy_mapping = get_copy_mapping()
    copy_mapping.load(task.task_id)

    async def plan_node(state: FileOrganizeState) -> FileOrganizeState:
        model = ChatTongyi(model=MODEL)
        tools = [list_dir, read_file]  # TODO 添加工具
        model_with_tools = model.bind_tools(tools)

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
            logger.info(f"plan阶段  工具: {tool_call['name']}    参数: {tool_call['args']}")
            tool = tools_by_name[tool_call["name"]]
            observation = tool(**tool_call["args"])
            result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"]))
        return {"messages": state["messages"] + result, "step": state["step"] + 1}

    def should_continue_plan(state: FileOrganizeState):
        if state.get("plan_result"):
            return "execute"

        return "plan_tool_node"

    async def execute_node(state: FileOrganizeState) -> FileOrganizeState:
        model = ChatTongyi(model=MODEL)
        tools = [create_file, delete_file, rename_file, modify_file, copy_file, move_file,
                 mkdir, delete_dir, copy_dir, rename_dir, move_dir,
                 list_dir, read_file]
        model_with_tools = model.bind_tools(tools)

        # 初始化消息列表
        messages = state.get("messages", [])
        if not messages:
            messages = [
                SystemMessage(content=EXECUTE_AGENT_PROMPT),
                HumanMessage(content=PromptTemplate.from_template(EXECUTE_INPUT_TEMPLATE)
                             .format(
                    execute_plan=state["plan_result"] if not state.get("verify_result") else state["verify_result"]))
            ]

        response = await model_with_tools.ainvoke(messages)

        if response.tool_calls:
            return {"messages": messages + [response], "step": state["step"] + 1, "execute_result": None}

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
            logger.info(f"execute阶段  工具: {tool_call['name']}    参数: {tool_call['args']}")
            tool = tools_by_name[tool_call["name"]]
            observation = tool(**tool_call["args"], _task_id=state["task_id"])  # 注入task_id
            # observation = await tool.ainvoke({**tool_call["args"], "_task_id": task.task_id})  # 注入task_id
            result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"]))
        return {"messages": state["messages"] + result, "step": state["step"] + 1}

    def should_continue_execute(state: FileOrganizeState):
        if state.get("execute_result") and state["execute_result"]:
            return "verify"

        return "execute_tool_node"

    async def verify_node(state: FileOrganizeState) -> FileOrganizeState:
        model = ChatTongyi(model=MODEL)
        tools = [list_dir, read_file]
        model_with_tools = model.bind_tools(tools)

        return {"verify_result": "1"}

        # 初始化消息列表
        messages = state.get("messages", [])
        if not messages:
            messages = [
                SystemMessage(content=VERIFY_AGENT_PROMPT),
                HumanMessage(content=f"这是用户输入：{state['query']}\n检查任务是否完成")
            ]

        response = await model_with_tools.ainvoke(messages)

        if response.tool_calls:
            return {"messages": messages + [response], "step": state["step"] + 1}

        # 无需再调用工具时，手动清空 messages，因为下个阶段的agent无需知道本阶段的对话
        return {
            "messages": [],  # 手动清空
            "step": state["step"] + 1,
            "verify_result": response.content
        }

    async def verify_tool_node(state: FileOrganizeState) -> FileOrganizeState:
        result = []
        for tool_call in state["messages"][-1].tool_calls:
            tool = tools_by_name[tool_call["name"]]
            observation = tool(**tool_call["args"])
            result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"]))
        return {"messages": state["messages"] + result, "step": state["step"] + 1}

    def should_continue_verify(state: FileOrganizeState):
        if state.get("verify_result") and state["verify_result"]:
            return "end"
            # # TODO 判断是否通过
            # if pass:
            #     return "end"
            # else:
            #     return "execute"
            pass

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

    return workflow, initial_state

