"""
policy rules  for cancel and return order 

"""


from typing import Any, Iterable, Optional
from datetime import date, datetime

RETURN_WINDOW_DAYS = 7
CANCEL_ORDER_STATUSES = ("Placed","Partially_Cancelled")
RETURN_ORDER_STATUSES = ("Delivered", "Partially_Returned")


def get_eligible_items(action: str, items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Filter out items that were already cancelled, returned, or requested for return.
    """
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

    if order.get("items") and not get_eligible_items("cancel_order", order["items"]):
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

    if order.get("items") and not get_eligible_items("return_order", order["items"]):
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


def check_order_eligibility(order: dict[str, Any], action: str) -> Optional[str]:
    """Return why an order is blocked, or None when it is eligible."""
    if action == "cancel_order":
        return _check_cancel_eligibility(order)
    if action == "return_order":
        return _check_return_eligibility(order)
    return f"Orders with action {action} are not supported."


