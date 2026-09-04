from  customer_support_ai_agent.state import CustomerState

MAX_MENU_RETRIES = 3

from datetime import datetime, date
from datetime import datetime, date

MAX_ORDER_RETRIES = 3
RETURN_WINDOW_DAYS = 7

# UPDATED ROUTESS
def route_menu(state: CustomerState) -> str:
    action = state.get("action_type")
    
    if action == "cancel_order":
        return "order_lookup"
    elif action == "return_order":
        return "order_lookup"
    elif action == "human_support":
        return "human_escalate" 
    elif action == "demo":
        return "demo_node"  
    elif action == "unclear":
        return "start"
    
    return "start"


def route_order_lookup(state: CustomerState) -> str:
    """Routes directly to action-specific confirmation or blocked nodes."""
    if state.get("retry_count", 0) >= MAX_ORDER_RETRIES:
        return "retry_exhausted"

    order = state.get("customer_details")
    if not order:
        return "retry"

    status = order.get("status")
    action = state.get("action_type")   

    # Cancel Flow
    if action == "cancel":
        if status == "Placed":
            return "eligible"
        return "blocked"

    # Return Flow
    if action == "return":
        delivery_date = order.get("delivery_date")
        if status == "Delivered" and delivery_date:
            d_date = delivery_date.date() if isinstance(delivery_date, datetime) else delivery_date
            if (date.today() - d_date).days <= RETURN_WINDOW_DAYS:
                return "eligible"
        return "blocked"

    return "blocked"


def route_blocked_choice(state: CustomerState) -> str:
    """Routes the user choice from policy_blocked_node."""
    if state.get("blocked_choice") == "ticket":
        return "human_escalate"
    return "start"




def route_retry_exhausted(state: CustomerState) -> str:
    choice = state.get("retry_exhausted_choice", "")
    if choice in {"1", "ticket", "human", "escalate"}:
        return "human_escalate"
    return "start"


