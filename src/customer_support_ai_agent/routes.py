from customer_support_ai_agent.state import CustomerState
from datetime import datetime, date

RETURN_WINDOW_DAYS = 7


def route_open_router(state: CustomerState) -> str:
    """Routes from open_router_node (the conversational front door)."""
    action = state.get("action_type")
    if action in ("cancel_order", "return_order"):
        return "order_lookup_node"
    elif action == "human_support":
        return "human_escalate_node"
    elif action == "exit":
        return "end"

    return "start_node"


def route_order_lookup(state: CustomerState) -> str:
    """Routes after order_lookup_node."""
    action = state.get("action_type")
    if action == "human_support":
        return "human_escalate_node"
    if not action or action in ("exit_to_menu", "exit", "faq"):
        return "start_node"

    order = state.get("customer_details")
    if not order:
        return "order_lookup_node"

    status = order.get("status")
    items = order.get("items", [])
    active_cancel_items = [it for it in items if it.get("item_status") not in ("Cancelled", "Returned")]
    active_return_items = [it for it in items if it.get("item_status") not in ("Cancelled", "Returned", "Return_Requested")]

    # Cancel Flow
    if action == "cancel_order":
        if status in ("Placed", "Processing", "Partially_Cancelled"):
            if items and not active_cancel_items:
                return "policy_blocked_node"
            return "select_items_node"
        return "policy_blocked_node"

    # Return Flow
    if action == "return_order":
        if status in ("Delivered", "Partially_Returned"):
            delivery_date = order.get("delivery_date")
            if delivery_date:
                d_date = delivery_date.date() if isinstance(delivery_date, datetime) else delivery_date
                if (date.today() - d_date).days <= RETURN_WINDOW_DAYS:
                    if items and not active_return_items:
                        return "policy_blocked_node"
                    return "select_items_node"
        return "policy_blocked_node"

    return "policy_blocked_node"


def route_select_items(state: CustomerState) -> str:
    """Routes after select_items_node."""
    action = state.get("action_type")
    if not action or action in ("exit_to_menu", "exit"):
        return "start_node"
    if action == "human_support":
        return "human_escalate_node"

    # If items and refund amount have been calculated in context
    if state.get("context") and state.get("context", {}).get("items"):
        return "confirm_action_node"

    return "select_items_node"


def route_confirm_action(state: CustomerState) -> str:
    """Routes after confirm_action_node to dedicated execution nodes or menu."""
    action = state.get("action_type")

    # Confirmed execution routes to dedicated nodes
    if state.get("confirmed") is True:
        if action == "cancel_order":
            return "cancel_order_node"
        elif action == "return_order":
            return "return_order_node"

    if action == "human_support":
        return "human_escalate_node"

    return "start_node"


def route_blocked_choice(state: CustomerState) -> str:
    """Routes from policy_blocked_node (Ticket or Main Menu)."""
    action = state.get("action_type")
    if action == "human_support":
        return "human_escalate_node"
    return "start_node"
