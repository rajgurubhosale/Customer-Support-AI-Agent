from  customer_support_ai_agent.state import CustomerState

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
    
    """
    router for the return or cancel flow    
    
    """

    choice = state.get("return_cancel_choice","")

    if choice in {"1", "return", "return order"}:
        return "return_order_node"
    if choice in {"2", "cancel", "cancel order"}:
        return "cancel_order_node"
    if choice in {"3", "main menu", "menu"}:
        return "start"

    return "retry"