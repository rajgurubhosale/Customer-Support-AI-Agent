from  customer_support_ai_agent.state import CustomerState

MAX_MENU_RETRIES = 3

# UPDATED ROUTESS
def route_menu(state: CustomerState) -> str:
    action = state.get("action_type")
    
    if action == "cancel":
        return "order_lookup"
    elif action == "return":
        return "order_lookup"
    elif action == "escalate":
        return "human_escalate" 
    elif action == "demo":
        return "demo_node"  
    
    return "start"

from datetime import datetime, date

MAX_ORDER_RETRIES = 3
RETURN_WINDOW_DAYS = 7


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








#####################################

def route_return_or_cancel(state: CustomerState) -> str:
    choice = state.get("return_cancel_choice", "")

    if choice in {"1", "return", "return order"}:
        return "return_order"
    if choice in {"2", "cancel", "cancel order"}:
        return "cancel_order"
    if choice in {"3", "main menu", "menu", "back"}:
        return "start"

    return "retry"
from datetime import datetime, date

MAX_ORDER_RETRIES = 3
RETURN_WINDOW_DAYS = 7
CANCELLABLE_STATUSES = {"Placed"}
OUT_FOR_DELIVERY_STATUSES = {"Shipped"}

####################
# RETURN ROUTE
####################

def route_order_lookup_return(state: CustomerState) -> str:
    """Runs right after ask_for_order_id_return — handles retry/escalate,
    then classifies eligibility (Delivered within 7 days) if the order was found."""

    if state.get("retry_count", 0) >= MAX_ORDER_RETRIES:
        return "retry_exhausted"

    if state.get("customer_details") is None:
        return "retry"

    order = state.get("customer_details") or {}
    status = order.get("status")
    delivery_date = order.get("delivery_date")

    # Returns are only eligible for Delivered orders within 7 days
    if status == "Delivered" and delivery_date:
        d_date = delivery_date.date() if isinstance(delivery_date, datetime) else delivery_date
        days_since = (date.today() - d_date).days
        if days_since <= RETURN_WINDOW_DAYS:
            return "ask_for_confirmation_return_node"
        
        # if days have passed for return 7 days has  been more
        if days_since > RETURN_WINDOW_DAYS:
            return "return_blocked_node"  

    # in-transit orders  Shipped — not delivered yet
    if status in OUT_FOR_DELIVERY_STATUSES:
        return "out_for_delivery_node_return" 

    # handle in this ndoe situations   ike if status is placed or Cancelled or Returned    
    return "return_blocked_node"


def route_return_blocked(state: CustomerState) -> str:
    choice = state.get("return_blocked_choice", "")
    if choice in {"1", "ticket", "human", "escalate"}:
        return "human_escalate"
    return "start"
    

def route_return_order(state: CustomerState) -> str:
    
    """Runs after ask_for_confirmation_node — branches to cancel_node if confirmed,
    otherwise loops back to start (and clears relevant state fields)."""
    
    if state.get("return_confirmed"):
        return "return_order"
    else:
        # clear the input field
        return "start"


##################
# CANCEL ROUTE
#####################


def route_order_lookup_cancel(state: CustomerState) -> str:
    """Runs right after ask_for_order_id_cancel — handles retry/escalate,
    then classifies eligibility if the order was found."""

    if state.get("retry_count", 0) >= MAX_ORDER_RETRIES:
        return "retry_exhausted"

    if state.get("customer_details") is None:
        return "retry"

    status = state["customer_details"]["status"]
    
    # DONE
    if status in CANCELLABLE_STATUSES:
        return "ask_for_confirmation_cancel_node"

    if status in OUT_FOR_DELIVERY_STATUSES:
        return "out_for_delivery_node_cancel"
    
    return "cancel_blocked_node"


def route_guided_options(state: CustomerState) -> str:
    """ 
    Handles user input from the guided_return_options_node,
    routing to either human_escalate or back to start (main menu).
    """
    choice = state.get("guided_choice", "").strip().lower()
    
    if choice in {"1", "ticket", "human", "support", "escalate"}:
        return "human_escalate"
    
    # Defaults to main menu for "2", "ok", "okay", "got it", "thanks", "menu", etc.
    return "start"



def route_cancel_blocked(state: CustomerState) -> str:
    choice = state.get("cancel_blocked_choice", "")
    if choice in {"1", "ticket", "human", "escalate"}:
        return "human_escalate"
    return "start"
    

def route_retry_exhausted(state: CustomerState) -> str:
    choice = state.get("retry_exhausted_choice", "")
    if choice in {"1", "ticket", "human", "escalate"}:
        return "human_escalate"
    return "start"


def route_cancel_order(state: CustomerState) -> str:
    
    """Runs after ask_for_confirmation_node — branches to cancel_node if confirmed,
    otherwise loops back to start (and clears relevant state fields)."""
    
    if state.get("cancel_confirmed"):
        return "cancel_order"
    else:
        # clear the input field
        return "start"



