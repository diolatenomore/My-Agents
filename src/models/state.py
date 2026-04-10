import operator
from typing import TypedDict, Annotated, Sequence, Optional

from langchain_core.messages import AnyMessage, BaseMessage


# 定义默认的State类型
class DefaultState(TypedDict):
    """
    默认的State类型
    """
    messages: Annotated[list[AnyMessage], operator.add]
    step: int
    current_node: str

class ChatState(TypedDict):
    """
    聊天State类型
    """
    messages: Annotated[list[AnyMessage], operator.add]
    step: int
    current_node: str

class ResearchWriteState(TypedDict):
    """
    研究-写作工作流的State类型
    """
    task: str
    messages: Annotated[Sequence[BaseMessage], operator.add]
    research_file: Optional[str]
    write_file: Optional[str]
    next: Optional[str]
    result: Optional[str]