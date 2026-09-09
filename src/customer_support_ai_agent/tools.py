from typing import Annotated, Any, Dict, List
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from customer_support_ai_agent.db_functions import get_order_history, get_order_with_items


@tool
def get_recent_orders(
    # InjectedState extracts customer_id from graph state automatically.
    # The LLM doesn't even see this argument!
    state: Annotated[dict, InjectedState],
) -> List[Dict[str, Any]]:
    """Fetch recent orders for the current customer to check recent history or list order IDs."""
    customer_id = state.get("user_id", 1)
    orders = get_order_history(customer_id) or []
    return orders[:5]


@tool
def get_order_details(
    order_id: int,
    state: Annotated[dict, InjectedState],
) -> Dict[str, Any]:
    """Fetch status, tracking, delivery date, and items for a specific order.
    Args:
        order_id: The integer ID of the order (e.g. 12 for ORD-12).
    """
    customer_id = state.get("user_id", 1)
    order = get_order_with_items(order_id, customer_id=customer_id)
    if not order:
        return {"error": f"Order ORD-{order_id} not found for your account."}
    return order

