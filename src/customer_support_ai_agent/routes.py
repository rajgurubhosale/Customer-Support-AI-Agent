from  customer_support_ai_agent.state import CustomerState

MAX_MENU_RETRIES = 3

def route_menu(state: CustomerState) -> str:
    """Deterministic routing off the menu choice. Falls back to re-asking
    on unrecognized input, capped to avoid an infinite loop."""

    choice = state.get("menu_choice", "").strip().lower()
    retries = state.get("menu_retry_count", 0)

    if choice in {"new chat", "restart", "reset"}:
        return "reset_state"

    if choice in {"1", "general", "general chat", "faq"}:
        return "general_inquiry"

    if choice in {"2", "cancel", "return", "cancel order", "return order"}:
        return "return_cancel_flow"

    if choice in {"3", "product", "product enquiry", "product inquiry"}:
        return "product_enquiry"

    # unrecognized input — retry or escalate
    if retries + 1 >= MAX_MENU_RETRIES:
        return "human_escalate"

    return "start"  # loop back and re-show the menu
    

def route_return_or_cancel(state: CustomerState) -> str:
    choice = state.get("return_cancel_choice", "")

    if choice in {"1", "return", "return order"}:
        return "return_order_node"
    if choice in {"2", "cancel", "cancel order"}:
        return "cancel_order_node"
    if choice in {"3", "main menu", "menu", "back"}:
        return "start"

    return "retry"


MAX_ORDER_RETRIES = 3
CANCELLABLE_STATUSES = {"Placed"}
GUIDED_STATUSES = {"Processing", "Shipped"}

def route_order_lookup_cancel(state: CustomerState) -> str:
    """Runs right after ask_for_order_id_cancel — handles retry/escalate,
    then classifies eligibility if the order was found."""

    if state.get("retry_count", 0) >= MAX_ORDER_RETRIES:
        return "retry_exhausted"

    if state.get("order_id") is None:
        return "retry"

    status = state["customer_details"]["status"]
    
    # DONE
    if status in CANCELLABLE_STATUSES:
        return "ask_for_confirmation_node"

    # REMAINMING
    
    # if in delivered status #  with the actual date is like something this if
    #  todays date is +7 then delivered data
    # then just print the info  that it cannot be cancelled 
    # 2 options that is the create ticket or back to main menu  


    if status in GUIDED_STATUSES:
        return "guided_return_options_node"
    # blocked node that means if order cannot be cancelled ? if the order if the days have 
    # been more than the 7 days? in that case 

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
    
    if state.get("confirmed"):
        return "cancel_order"
    else:
        # clear the input field
        return "start"



