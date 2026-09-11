from datetime import date, datetime
from typing import Any, Iterable

from langgraph.graph import END

from customer_support_ai_agent.state import CustomerState

RETURN_WINDOW_DAYS = 7
CANCEL_ORDER_STATUSES = ("Placed", "Processing", "Partially_Cancelled")
RETURN_ORDER_STATUSES = ("Delivered", "Partially_Returned")


def order_statuses_for(action: str) -> tuple[str, ...]:
    """Return the order statuses shown for an action."""
    if action == "cancel_order":
        return CANCEL_ORDER_STATUSES
    if action == "return_order":
        return RETURN_ORDER_STATUSES
    return ()


def active_items_for(
    action: str,
    items: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return items that can still take part in the requested action."""
    blocked_statuses = {"Cancelled", "Returned"}
    if action == "return_order":
        blocked_statuses.add("Return_Requested")
    return [item for item in items if item.get("item_status") not in blocked_statuses]


def order_is_eligible(order: dict[str, Any], action: str) -> bool:
    """Apply the current deterministic status and return-window rules."""
    items = order.get("items", [])
    if order.get("status") not in order_statuses_for(action):
        return False
    if items and not active_items_for(action, items):
        return False
    if action == "cancel_order":
        return True

    delivery_date = order.get("delivery_date")
    if not delivery_date:
        return False
    delivered_on = delivery_date.date() if isinstance(delivery_date, datetime) else delivery_date
    days_since_delivery = (date.today() - delivered_on).days
    return 0 <= days_since_delivery <= RETURN_WINDOW_DAYS


def route_open_router(state: CustomerState) -> str:
    """Routes from open_router_node (the conversational front door)."""
    action = state.get("action_type")
    if action in ("cancel_order", "return_order"):
        return "order_lookup_node"
    if action == "human_support":
        return "human_escalate_node"
    if action == "exit":
        return END

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

    return "select_items_node" if order_is_eligible(order, action) else "policy_blocked_node"


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
        if action == "return_order":
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
