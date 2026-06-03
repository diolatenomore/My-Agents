import asyncio
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath('.'))

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from src.agents.file_organize_prompt import PLAN_AGENT_PROMPT, PLAN_INPUT_TEMPLATE
from src.config import MODEL, DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY
from src.vfs.operations import list_dir, read_file


# 创建工具
@tool
async def list_dir_tool(path: str) -> str:
    """列出指定目录下的所有文件和子目录"""
    result = list_dir(path)
    return str(result)

@tool
async def read_file_tool(path: str) -> str:
    """读取指定文件的内容"""
    result = read_file(path)
    return result


async def test_plan_agent():
    """测试文件整理规划agent"""
    print("=== 测试文件整理规划agent ===")
    
    # 测试查询
    test_query = "整理 /Users/tinklingowl/PycharmProjects/AI-Agents/workspace 目录的文件，按类型分类"
    
    # 初始化模型和工具
    model = ChatOpenAI(model=MODEL, base_url=DEEPSEEK_BASE_URL, api_key=DEEPSEEK_API_KEY)
    tools = [list_dir_tool, read_file_tool]
    model_with_tools = model.bind_tools(tools)
    
    # 构建消息
    system_message = SystemMessage(content=PLAN_AGENT_PROMPT)
    user_message = HumanMessage(content=PLAN_INPUT_TEMPLATE.format(query=test_query))
    messages = [system_message, user_message]
    
    # 执行模型
    response = await model_with_tools.ainvoke(messages)
    
    # 处理工具调用
    while response.tool_calls:
        print("=== 工具调用 ===")
        for tool_call in response.tool_calls:
            print(f"工具: {tool_call['name']}")
            print(f"参数: {tool_call['args']}")
            
            # 模拟工具执行
            if tool_call['name'] == "list_dir_tool":
                # 直接调用底层函数，避免异步工具调用问题
                result = list_dir(tool_call['args']['path'])
            elif tool_call['name'] == "read_file_tool":
                result = read_file(tool_call['args']['path'])
            else:
                result = "未知工具"
            
            print(f"结果: {result}")
            print()
            
            # 添加工具响应
            messages.append(ToolMessage(content=str(result), tool_call_id=tool_call['id']))
        
        # 再次执行模型获取最终结果
        response = await model_with_tools.ainvoke(messages)

    print("=== 规划结果 ===")
    print(response.content)


if __name__ == "__main__":
    # 在任务上下文中运行
    with task_scope("test_plan_agent"):
        asyncio.run(test_plan_agent())
