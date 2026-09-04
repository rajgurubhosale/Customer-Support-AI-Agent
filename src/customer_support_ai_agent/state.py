from typing import TypedDict, Optional, Annotated, Literal, Any, Dict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class CustomerState(TypedDict, total=False):
    user_id: Optional[str]
    session_id: Optional[str]
    menu_choice: Optional[str]
    action_type: Optional[Literal["cancel_order", "return_order", "faq", "human_support", "demo", "unclear", "exit"]]

    order_id: Optional[str]
    customer_details: Optional[Dict[str, Any]]
    retry_count: int
    confirmed: Optional[bool]
    policy_block_reason: Optional[str]

    retry_exhausted_choice: Optional[str]
    context: Optional[Dict[str, Any]]
    messages: Annotated[list[BaseMessage], add_messages]

