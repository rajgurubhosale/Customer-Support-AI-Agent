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

def get_order(order_id: int, customer_id: int) -> Optional[dict]:
    """Grab the order for this customer. Returns None if not found or on error."""

    with db_pool.connection() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM orders WHERE order_id = %s AND customer_id = %s",
                    (order_id, customer_id),
                )
                row = cur.fetchone()

                if row is None:
                    print(f"No order found for order_id={order_id}")
                    return None

                return row   # ← just the row, no tuple

        except Exception as e:
            print(f"Error fetching order: {e}")
            return None

            

def get_order_history(customer_id: int) -> Optional[list[dict]]:
    ''' return customer order history'''
    with db_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM orders WHERE customer_id = %s", (customer_id,))
            return cur.fetchall()

