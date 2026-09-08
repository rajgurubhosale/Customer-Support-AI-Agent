from typing import List, Optional, Literal
from langchain_core.tools import tool
from customer_support_ai_agent.db_functions import get_order_history, get_order_with_items


def make_tools(customer_id: int):
    @tool
    def get_recent_orders() -> str:
        """Fetch up to 5 recent orders for this customer (id, date, status, total)."""
        orders = get_order_history(customer_id) or []
        if not orders:
            return "No orders found."
        return "\n".join(
            f"ORD-{o.get('order_id')}: {o.get('status')} | Ordered {o.get('order_date')} | "
            f"Delivery {o.get('delivery_date')} | ₹{o.get('total_amount')}"
            for o in orders
        )

    @tool
    def get_order_details(order_id: str) -> str:
        """Fetch full details for one order: items, status, delivery date."""
        try:
            clean_id = int(str(order_id).replace("ORD-", "").replace("ord-", "").strip())
        except (ValueError, TypeError):
            return f"Invalid order ID format: {order_id}"
        order = get_order_with_items(clean_id, customer_id)
        if not order:
            return f"Order ORD-{clean_id} not found."
        items = ", ".join(
            f"{it.get('product_name')} x{it.get('quantity')} (₹{it.get('unit_price')}, {it.get('item_status')})"
            for it in order.get("items", [])
        )
        return (
            f"ORD-{clean_id}: {order.get('status')} | Delivery {order.get('delivery_date')} | "
            f"₹{order.get('total_amount')} | Items: [{items}]"
        )

    @tool
    def signal_intent(
        intent: Literal["cancel_order", "return_order", "human_support", "menu"],
        order_id: Optional[str] = None,
    ) -> str:
        """Call when the customer clearly wants to take an action right now,
        not just ask about it. Extract order_id (digits only) if mentioned."""
        return "acknowledged"

    return [get_recent_orders, get_order_details, signal_intent]

