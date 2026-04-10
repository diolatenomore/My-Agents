from typing import Any, Dict, Tuple

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_community.chat_models import ChatTongyi
from langgraph.graph import StateGraph
from langgraph.constants import END

from agents.research_write import RESEARCH_PROMPT, WRITE_PROMPT
from config import AGENT_WORKSPACE_PATH, MODEL
from models.state import ResearchWriteState
from tools.research_write_tools import tavily_search, write_file, read_file
from utils.common import extract_content


def create_research_write_graph(query: str) -> Tuple[StateGraph, Dict[str, Any]]:
    """创建研究-写作工作流图和初始状态"""
    backend = FilesystemBackend(root_dir=AGENT_WORKSPACE_PATH, virtual_mode=True)

    # 创建代理
    research_agent = create_deep_agent(
        model=ChatTongyi(model=MODEL),
        backend=backend,
        tools=[tavily_search, write_file],
        skills=["web-research"],
        system_prompt=RESEARCH_PROMPT
    )
    write_agent = create_deep_agent(
        model=ChatTongyi(model=MODEL),
        backend=backend,
        tools=[read_file, write_file],
        system_prompt=WRITE_PROMPT
    )
    tool_names = ["research", "write"]

    # 创建监督节点
    async def supervisor_node(state: ResearchWriteState) -> ResearchWriteState:
        model = ChatTongyi(model=MODEL)
        state_str = f"当前状态：\n- 研究结果：{'None' if not state.get('research_file') else '已完成'}\n- 写作结果：{'None' if not state.get('write_file') else '已完成'}"
        print(state_str)

        # 构建消息
        system_prompt = f"""你是任务调度 Supervisor，必须严格执行以下决策规则：

【当前任务状态】
- 研究阶段：{'未完成' if not state.get('research_file') else '已完成'}
- 写作阶段：{'未完成' if not state.get('write_file') else '已完成'}

【决策规则 - 必须严格遵守】
1. IF 研究阶段未完成 THEN 输出："research"
2. IF 研究阶段已完成 AND 写作阶段未完成 THEN 输出："write"  
3. IF 研究阶段已完成 AND 写作阶段已完成 THEN 输出："任务完成"

【可用工具】
- research：收集信息（仅在研究阶段未完成时使用）
- write：撰写文章（仅在研究阶段已完成、写作阶段未完成时使用）

【重要限制】
- 每个工具只能调用一次
- 禁止重复调用已完成的阶段
- 只输出单个词：research / write / 任务完成
- 不要解释，不要有多余内容

【输出示例】
状态：研究未完成 → 输出：research
状态：研究完成，写作未完成 → 输出：write
状态：都完成 → 输出：任务完成

请根据当前状态，直接输出决策结果："""

        messages = [{"role": "system", "content": system_prompt}]

        # 添加用户任务
        if state.get("task"):
            messages.append({"role": "user", "content": f"任务：{state['task']}"})
        # 调用模型
        result = await model.ainvoke(messages)
        print(f"模型返回：{extract_content(result)}")

        # 检查是否有工具调用请求
        if hasattr(result, "tool_calls") and result.tool_calls:
            tool_call = result.tool_calls[0]
            # 处理 tool_call 是字典的情况
            if isinstance(tool_call, dict):
                tool_name = tool_call.get("name")
            else:
                tool_name = tool_call.name
            print(f"模型要求调用工具：{tool_name}")
            return {"next": tool_name}

        # 检查模型返回的内容是否是工具名称
        content = extract_content(result)
        if content in tool_names:
            print(f"模型要求调用工具：{content}")
            return {"next": content}

        # 否则返回结束信号
        return {"messages": [result], "next": "end", "result": state.get("write_file")}

    # 研究节点
    async def research_node(state: ResearchWriteState) -> ResearchWriteState:
        """调用研究工具收集信息"""
        task = state["task"]
        # 模拟研究过程
        research_result = await research_agent.ainvoke({
            "messages": [
                {"role": "user", "content": f"这是用户的输入：'{task}'\n请搜集相关信息"}
            ]
        })
        # 使用 extract_content 函数提取纯文本内容
        content = extract_content(research_result)
        print(f"研究保存路径：{content}")
        return {"research_file": content}

    # 写作节点
    async def write_node(state: ResearchWriteState) -> ResearchWriteState:
        """调用写作工具生成文章"""
        task = state["task"]
        research_file = state["research_file"]
        # 模拟写作过程
        write_result = await write_agent.ainvoke({
            "messages": [
                {"role": "user", "content": f'这是用户的输入："{task}"\n请根据用户输入写一篇文章，以下为研究结果的文件路径：""{research_file}""'}
            ]
        })
        # 使用 extract_content 函数提取纯文本内容
        content = extract_content(write_result)
        print(f"写作保存路径：{content}...")
        return {"write_file": content}

    # 条件边：根据 supervisor 的决定选择下一个节点
    def should_continue(state: ResearchWriteState) -> str:
        return state.get("next", "end")

    # 构建工作流
    workflow = StateGraph(ResearchWriteState)
    # 添加节点
    workflow.add_node("agent", supervisor_node)
    workflow.add_node("research", research_node)
    workflow.add_node("write", write_node)

    # 添加边
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "research": "research",
            "write": "write",
            "end": END
        }
    )
    # 研究和写作完成后返回 supervisor 节点
    workflow.add_edge("research", "agent")
    workflow.add_edge("write", "agent")

    # 初始状态
    initial_state = {
        "task": query,
        "research_file": None,
        "write_file": None,
        "messages": [],
        "next": "agent",
        "result": None
    }

    return workflow, initial_state
