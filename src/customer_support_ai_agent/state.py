from typing import TypedDict, Optional, Annotated, Literal, Any, Dict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class CustomerState(TypedDict, total=False):
    user_id: Optional[int]
    session_id: Optional[str]
    action_type: Optional[Literal["cancel_order", "return_order", "faq", "human_support", "exit"]]

    order_id: Optional[str]
    
    # asve the order and item data read from database
    customer_details: Optional[Dict[str, Any]]
    confirmed: Optional[bool]

    context: Optional[Dict[str, Any]]
    messages: Annotated[list[BaseMessage], add_messages]

