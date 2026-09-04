from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from typing import Optional
import os

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



            

def get_order_history(customer_id: int) -> Optional[list[dict]]:
    ''' return customer order history'''
    with db_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM orders WHERE customer_id = %s", (customer_id,))
            return cur.fetchall()

