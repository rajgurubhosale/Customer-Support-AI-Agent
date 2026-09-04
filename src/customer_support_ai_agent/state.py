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

     # blocked for the delivery is done and its more than  7 days we dont return order ask for the ticket
     cancel_eligible: Optional[Literal["auto", "guided", "blocked"]]
     
     return_blocked_choice: Optional[str]
     guided_choice: Optional[str]

     retry_count: int                          
     customer_details: Optional[Dict[str, Any]]
     retry_exhausted_choice: Optional[str]   
     
     
     cancel_confirmed: Optional[bool]
     return_confirmed: Optional[bool]
     
     order_id: Optional[str]
     context: Optional[Dict[str, Any]]
     messages: Annotated[list[BaseMessage], add_messages]


