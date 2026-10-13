from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from typing import Optional
from decimal import Decimal
import json
import os

from customer_support_ai_agent.policy_rules import check_order_eligibility, get_eligible_items

db_pool = ConnectionPool(
    conninfo=os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:2025@localhost:5432/customer_support_db",
    ),
    min_size=2,
    max_size=10,
    kwargs={"row_factory": dict_row},
    open=True,
)


def get_order_with_items(order_id: int, customer_id: int) -> Optional[dict]:
    """Safely fetch an order and its items. Returns None on not found or error."""
    try:
        clean_order_id = int(order_id)
        clean_customer_id = int(customer_id)
    except (ValueError, TypeError):
        print(f"Invalid input: order_id={order_id}, customer_id={customer_id}")
        return None

    try: 
        with db_pool.connection() as conn:
            with conn.cursor() as cur:
                # Fetch Order 
                cur.execute(
                    "SELECT * FROM orders WHERE order_id = %s AND customer_id = %s",
                    (clean_order_id, clean_customer_id),
                )
                order = cur.fetchone()
                if not order:
                    return None

                # fetch order items
                cur.execute(
                    "SELECT * FROM order_items WHERE order_id = %s",
                    (clean_order_id,),
                )
                order["items"] = cur.fetchall() or []
                return order

    except Exception as e:
        print(f"Error fetching order with items: {e}")
        return None


def get_order_history(customer_id: int,limit: Optional[int] = 5,) -> Optional[list[dict]]:
    """Return the customer's newest orders."""

    query = """
        SELECT *
        FROM orders
        WHERE customer_id = %s
        ORDER BY order_date DESC
        LIMIT %s
    """

    params = [customer_id, limit]

    with db_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
            return cur.fetchall()


def execute_order_action(
    customer_id: int,
    order_id: int,
    action: str,
    selections: list[dict],
    expected_amount: float,
    idempotency_key: str,
) -> dict:
    """Apply one confirmed cancellation or record one return request atomically."""
    if action not in ("cancel_order", "return_order") or not idempotency_key:
        raise ValueError("Invalid order action.")

    with db_pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM orders WHERE order_id = %s AND customer_id = %s FOR UPDATE",
            (order_id, customer_id),
        )
        order = cur.fetchone()
        if not order:
            raise ValueError("Order not found under your account.")

        cur.execute(
            "SELECT action_id, refund_amount, status, selected_items FROM order_actions "
            "WHERE idempotency_key = %s AND order_id = %s AND action_type = %s",
            (idempotency_key, order_id, action),
        )
        previous = cur.fetchone()
        if previous:
            return {"action_id": previous["action_id"], "refund_amount": previous["refund_amount"],
                    "status": previous["status"], "items": previous["selected_items"]}

        cur.execute("SELECT * FROM order_items WHERE order_id = %s ORDER BY order_item_id FOR UPDATE", (order_id,))
        items = cur.fetchall()
        reason = check_order_eligibility({**order, "items": items}, action)
        if reason:
            raise ValueError(reason)

        eligible = {item["order_item_id"]: item for item in get_eligible_items(action, items)}
        if not selections:
            raise ValueError("Please select at least one item.")
        selected = []
        seen = set()
        for selection in selections:
            try:
                item_id = int(selection["item_id"])
                quantity = selection["quantity"]
            except (KeyError, TypeError, ValueError):
                raise ValueError("Invalid item selection.") from None
            item = eligible.get(item_id)
            if (item_id in seen or not item or type(quantity) is not int
                    or not 1 <= quantity <= item["quantity"]):
                raise ValueError("Selected items or quantities are no longer available.")
            seen.add(item_id)
            selected.append((item, quantity))

        amount = sum((Decimal(str(item["unit_price"])) * qty for item, qty in selected), Decimal(0))
        amount = amount.quantize(Decimal("0.01"))
        if amount <= 0 or amount != Decimal(str(expected_amount)).quantize(Decimal("0.01")):
            raise ValueError("The amount changed. Please select the items again before confirming.")
        if action == "cancel_order":
            active_total = sum(
                (Decimal(str(item["unit_price"])) * item["quantity"]
                 for item in items if item["item_status"] != "Cancelled"), Decimal(0)
            )
            if active_total != Decimal(str(order["total_amount"])):
                raise ValueError("The order total needs support review before cancellation.")

        new_status = "Cancelled" if action == "cancel_order" else "Return_Requested"
        result_items = []
        for item, quantity in selected:
            result_id = item["order_item_id"]
            if quantity == item["quantity"]:
                cur.execute("UPDATE order_items SET item_status = %s WHERE order_item_id = %s",
                            (new_status, result_id))
            else:
                cur.execute("UPDATE order_items SET quantity = quantity - %s WHERE order_item_id = %s",
                            (quantity, result_id))
                cur.execute(
                    """INSERT INTO order_items
                       (order_id, product_name, quantity, unit_price, item_status, variant)
                       VALUES (%s, %s, %s, %s, %s, %s::jsonb) RETURNING order_item_id""",
                    (order_id, item["product_name"], quantity, item["unit_price"],
                     new_status, json.dumps(item.get("variant") or {})),
                )
                result_id = cur.fetchone()["order_item_id"]
            result_items.append({"item_id": result_id, "source_item_id": item["order_item_id"],
                                 "name": item["product_name"], "quantity": quantity,
                                 "unit_price": str(item["unit_price"])})

        remaining_filter = "item_status <> 'Cancelled'" if action == "cancel_order" else "item_status = 'Delivered'"
        cur.execute("SELECT EXISTS(SELECT 1 FROM order_items WHERE order_id = %s "
                    f"AND {remaining_filter}) AS has_active", (order_id,))
        has_active = cur.fetchone()["has_active"]
        parent_status = ("Partially_Cancelled" if has_active else "Cancelled") if action == "cancel_order" else (
            order["status"] if has_active else "Return_Requested"
        )
        if action == "cancel_order":
            cur.execute("UPDATE orders SET status = %s, total_amount = total_amount - %s, "
                        "updated_at = CURRENT_TIMESTAMP WHERE order_id = %s",
                        (parent_status, amount, order_id))
        else:
            cur.execute("UPDATE orders SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE order_id = %s",
                        (parent_status, order_id))

        scope = "all" if len(selected) == len(eligible) and all(
            qty == item["quantity"] for item, qty in selected) else "partial"
        status = "completed" if action == "cancel_order" else "pending"
        cur.execute(
            """INSERT INTO order_actions
               (order_id, action_type, scope, selected_items, refund_amount, status,
                idempotency_key, confirmed_at, completed_at)
               VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, CURRENT_TIMESTAMP,
                       CASE WHEN %s = 'completed' THEN CURRENT_TIMESTAMP ELSE NULL END)
               RETURNING action_id""",
            (order_id, action, scope, json.dumps(result_items), amount, status, idempotency_key, status),
        )
        action_id = cur.fetchone()["action_id"]
        if action == "cancel_order":
            cur.execute(
                "INSERT INTO refunds (order_id, action_id, amount, status) "
                "VALUES (%s, %s, %s, 'initiated')",
                (order_id, action_id, amount),
            )
        return {"action_id": action_id, "refund_amount": amount,
                "status": status, "items": result_items}
