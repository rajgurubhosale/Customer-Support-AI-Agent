from typing import TypedDict, Optional, Annotated, Literal, Any, Dict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class CustomerState(TypedDict, total=False):
     #session identity
    user_id: Optional[str]
    session_id: Optional[str]

    #top-level menu routing
    menu_choice: Optional[str]
    
    return_cancel_choice: Optional[str]

    order_id: Optional[str]
    context: Optional[Dict[str, Any]]
    messages: Annotated[list[BaseMessage], add_messages]


