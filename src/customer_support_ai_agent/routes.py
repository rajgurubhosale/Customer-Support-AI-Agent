from langchain_core.utils.function_calling import ToolDescription
from datetime import date, datetime
from typing import Any, Iterable, Optional

from langgraph.graph import END

from customer_support_ai_agent.state import CustomerState

RETURN_WINDOW_DAYS = 7
CANCEL_ORDER_STATUSES = ("Placed","Partially_Cancelled")
RETURN_ORDER_STATUSES = ("Delivered", "Partially_Returned")

# HELPER FUNCTIONS

def _check_global_route(action: Optional[str]) -> Optional[str]:
    """
    Handles universal graph exits and escalations.
    """
    if action == "exit":
        return END
    if action == "human_support":
        return "human_escalate_node"
    return None


def route_open_router(state: CustomerState) -> str:
    """
    Routes from open_router_node (the conversational front door).
    """
    action = state.get("action_type")
    target = _check_global_route(action)
    
    if target:
        return target

    if action in ("cancel_order", "return_order"):
        return "order_lookup_node"
    
    return "start_node"



def active_items_for(action: str, items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter out items that were already cancelled, returned, or requested for return."""
    blocked = {"Cancelled", "Returned"}

    if action == "return_order":
        blocked.add("Return_Requested")

    active = []
    for item in items:
        if item.get("item_status") not in blocked:
            active.append(item)

    return active


def _check_cancel_eligibility(order: dict[str, Any]) -> Optional[str]:
    """Validate cancellation eligibility rules."""
    status = order.get("status", "Unknown")

    if status not in CANCEL_ORDER_STATUSES:
        if status in ("Shipped", "Delivered"):
            return f"This order is {status.lower()} and can no longer be cancelled [SEC-1.2]."
        return f"This order has already been {status.lower()} and cannot be cancelled."

    if order.get("items") and not active_items_for("cancel_order", order["items"]):
        return "All items in this order have already been cancelled."

    return None



def _check_return_eligibility(order: dict[str, Any]) -> Optional[str]:
    """ 
    Verify if an order qualifies for a return under store policy.
    Returns None if eligible, or an explanatory error message if blocked.
    """
    
    status = order.get("status", "Unknown")

    if status not in RETURN_ORDER_STATUSES:
        return f"This order is {status.lower()}; only delivered orders can be returned [SEC-2.5]."


    if order.get("items") and not active_items_for("return_order", order["items"]):
        return "All items have already been returned or have an active return request."

    delivery_date = order.get("delivery_date")
    if not delivery_date and status in CANCEL_ORDER_STATUSES:

        return "the order is in the placed and didnt start for the delivery, so if u wnat to cancel then type exit and start the proper from first the cancellation first"

    delivered_on = delivery_date.date() if isinstance(delivery_date, datetime) else delivery_date
    days_since_delivery = (date.today() - delivered_on).days
    if days_since_delivery < 0:
        return "We couldn't verify the return window. Please contact a support specialist."
    if days_since_delivery > RETURN_WINDOW_DAYS:
        return "This order was delivered, but its 7-day return window has expired [SEC-2.5]."
    return None


def get_ineligibility_reason(order: dict[str, Any], action: str) -> Optional[str]:
    """Return why an order is blocked, or None when it is eligible."""
    if action == "cancel_order":
        return _check_cancel_eligibility(order)
    if action == "return_order":
        return _check_return_eligibility(order)
    return f"Orders with action {action} are not supported."


def order_is_eligible(order: dict[str, Any], action: str) -> bool:
    """Apply the current deterministic status and return-window rules."""
    return get_ineligibility_reason(order, action) is None




def route_order_lookup(state: CustomerState) -> str:
    """Routes after order_lookup_node."""
    action = state.get("action_type")
    if target := _check_global_route(action):
        return target
    if not action:
        return "start_node"

    order = state.get("customer_details")
    if not order:
        return "order_lookup_node"

    return "select_items_node" if order_is_eligible(order, action) else "policy_blocked_node"


def route_select_items(state: CustomerState) -> str:
    """Routes after select_items_node."""
    action = state.get("action_type")
    if target := _check_global_route(action):
        return target
    # In routes.py:
    if not action:
        return "start_node"


    if state.get("context") and state.get("context", {}).get("items"):
        return "confirm_action_node"
    return "select_items_node"


def route_confirm_action(state: CustomerState) -> str:
    """Routes after confirm_action_node."""
    action = state.get("action_type")
    if target := _check_global_route(action):
        return target

    if state.get("confirmed") is True:
        return "cancel_order_node" if action == "cancel_order" else "return_order_node"

    # Stay on confirmation if transaction is still pending (e.g. FAQ was answered)
    if (
        action in ("cancel_order", "return_order")
        and state.get("context")
        and state.get("confirmed") is None
    ):
        return "confirm_action_node"

    return "start_node"

def route_blocked_choice(state: CustomerState) -> str:
    """Routes from policy_blocked_node (Ticket or Main Menu)."""
    return _check_global_route(state.get("action_type")) or "start_node"

