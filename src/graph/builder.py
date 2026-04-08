from langgraph.graph import StateGraph
from langgraph.constants import START, END
from langchain_core.messages import HumanMessage
from typing import Dict, Any, Optional

class GraphBuilder:
    """工作流构建器"""
    
    @staticmethod
    def create_default_graph(worker=None) -> StateGraph:
        """创建默认工作流图"""
        # 定义状态结构
        def state_schema():
            return {
                "messages": list,
                "step": int,
                "current_node": str
            }
        
        # 创建状态图
        graph = StateGraph(state_schema)
        
        # 定义节点
        def start_node(state):
            print("开始节点")
            return {
                "messages": state.get("messages", []),
                "step": 0,
                "current_node": "start"
            }
        
        def process_node(state):
            print("处理节点")
            # 这里可以添加具体的处理逻辑
            return {
                "messages": state.get("messages", []) + ["处理完成"],
                "step": state.get("step", 0) + 1,
                "current_node": "process"
            }
        
        def end_node(state):
            print("结束节点")
            return {
                "messages": state.get("messages", []) + ["任务完成"],
                "step": state.get("step", 0) + 1,
                "current_node": "end"
            }
        
        # 添加节点
        graph.add_node("start", start_node)
        graph.add_node("process", process_node)
        graph.add_node("end", end_node)
        
        # 添加边
        graph.add_edge(START, "start")
        graph.add_edge("start", "process")
        graph.add_edge("process", "end")
        
        return graph
    
    @staticmethod
    def create_chat_graph(worker=None) -> StateGraph:
        """创建聊天工作流图"""
        # 定义状态结构
        def state_schema():
            return {
                "messages": list,
                "step": int,
                "current_node": str
            }
        
        # 创建状态图
        graph = StateGraph(state_schema)
        
        # 定义节点
        def chat_node(state):
            print("聊天节点")
            # 这里可以添加具体的聊天处理逻辑
            return {
                "messages": state.get("messages", []) + ["聊天响应"],
                "step": state.get("step", 0) + 1,
                "current_node": "chat"
            }
        
        # 添加节点
        graph.add_node("chat", chat_node)
        
        # 添加边
        graph.add_edge(START, "chat")
        graph.add_edge("chat", END)
        
        return graph
    
    @staticmethod
    def create_research_writing_graph(worker=None) -> StateGraph:
        """创建研究-写作工作流图"""
        # 定义状态结构
        def state_schema():
            return {
                "task": str,
                "research_file": Optional[str],
                "writing_file": Optional[str],
                "messages": list,
                "next": Optional[str],
                "result": Optional[str]
            }
        
        # 创建状态图
        graph = StateGraph(state_schema)
        
        # 定义节点
        def research_node(state):
            print("研究节点")
            # 这里可以添加具体的研究逻辑
            return {
                "task": state.get("task"),
                "research_file": "research_result.txt",
                "writing_file": state.get("writing_file"),
                "messages": state.get("messages", []) + ["研究完成"],
                "next": "write",
                "result": state.get("result")
            }
        
        def write_node(state):
            print("写作节点")
            # 这里可以添加具体的写作逻辑
            return {
                "task": state.get("task"),
                "research_file": state.get("research_file"),
                "writing_file": "writing_result.txt",
                "messages": state.get("messages", []) + ["写作完成"],
                "next": "end",
                "result": "任务完成"
            }
        
        def end_node(state):
            print("结束节点")
            return {
                "task": state.get("task"),
                "research_file": state.get("research_file"),
                "writing_file": state.get("writing_file"),
                "messages": state.get("messages", []) + ["任务完成"],
                "next": None,
                "result": state.get("result")
            }
        
        # 添加节点
        graph.add_node("research", research_node)
        graph.add_node("write", write_node)
        graph.add_node("end", end_node)
        
        # 添加边
        graph.add_edge(START, "research")
        graph.add_edge("research", "write")
        graph.add_edge("write", "end")
        
        return graph