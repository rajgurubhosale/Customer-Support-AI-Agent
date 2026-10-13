"""Database operations for the local admin demo."""

from customer_support_ai_agent.db_functions import db_pool


def list_cases() -> list[dict]:
    with db_pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT c.case_id, c.customer_id, c.status, c.resolution_source,
                      c.priority, c.summary, c.created_at, c.updated_at,
                      (SELECT COUNT(*) FROM support_issues i WHERE i.case_id = c.case_id) AS issue_count,
                      (SELECT string_agg(DISTINCT 'ORD-' || i.order_id::text, ', ') FROM support_issues i WHERE i.case_id = c.case_id) AS order_refs
               FROM support_cases c ORDER BY c.updated_at DESC"""
        )
        return cur.fetchall() or []


def get_case(case_id: int) -> dict | None:
    with db_pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM support_cases WHERE case_id = %s", (case_id,))
        case = cur.fetchone()
        if not case:
            return None
        cur.execute(
            """SELECT i.*, o.status AS order_status, o.total_amount,
                      o.expected_delivery_date, o.delivery_date,
                      oi.product_name, oi.variant, oi.quantity AS item_quantity,
                      oi.unit_price, oi.item_status
               FROM support_issues i
               LEFT JOIN orders o ON o.order_id = i.order_id
               LEFT JOIN order_items oi ON oi.order_item_id = i.order_item_id
               WHERE i.case_id = %s ORDER BY i.issue_id""",
            (case_id,),
        )
        case["issues"] = cur.fetchall() or []
        return case


def list_order_actions() -> list[dict]:
    with db_pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT a.action_id, a.order_id, a.action_type, a.scope,
                      a.selected_items, a.refund_amount, a.status AS action_status,
                      a.confirmed_at, a.completed_at, o.customer_id, o.status AS order_status,
                      r.status AS refund_status
               FROM order_actions a
               JOIN orders o ON o.order_id = a.order_id
               LEFT JOIN refunds r ON r.action_id = a.action_id
               ORDER BY a.confirmed_at DESC"""
        )
        return cur.fetchall() or []


def start_review(case_id: int) -> None:
    with db_pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "UPDATE support_cases SET status = 'in_progress' "
            "WHERE case_id = %s AND status = 'open' RETURNING case_id",
            (case_id,),
        )
        if not cur.fetchone():
            raise ValueError("This case is no longer waiting for review.")


def reopen_case(case_id: int) -> None:
    with db_pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "UPDATE support_cases SET status = 'open', resolution_source = NULL "
            "WHERE case_id = %s AND status = 'resolved' AND resolution_source = 'assistant' "
            "RETURNING case_id",
            (case_id,),
        )
        if not cur.fetchone():
            raise ValueError("Only assistant-resolved cases can be reopened here.")
        cur.execute(
            "UPDATE support_issues SET status = 'escalated' WHERE case_id = %s",
            (case_id,),
        )


def resolve_issue(case_id: int, issue_id: int, note: str) -> None:
    note = note.strip()
    if not note:
        raise ValueError("Please enter a resolution note.")
    with db_pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT status FROM support_cases WHERE case_id = %s FOR UPDATE", (case_id,))
        case = cur.fetchone()
        if not case or case["status"] == "resolved":
            raise ValueError("This case is not open for review.")
        cur.execute(
            "UPDATE support_issues SET status = 'resolved', resolution_summary = %s "
            "WHERE case_id = %s AND issue_id = %s AND status <> 'resolved' RETURNING issue_id",
            (note, case_id, issue_id),
        )
        if not cur.fetchone():
            raise ValueError("This issue is already resolved or does not belong to the case.")
        cur.execute(
            "SELECT COUNT(*) AS remaining FROM support_issues "
            "WHERE case_id = %s AND status <> 'resolved'",
            (case_id,),
        )
        if cur.fetchone()["remaining"] == 0:
            cur.execute(
                "UPDATE support_cases SET status = 'resolved', resolution_source = 'admin' "
                "WHERE case_id = %s",
                (case_id,),
            )
        else:
            cur.execute(
                "UPDATE support_cases SET status = 'in_progress' WHERE case_id = %s",
                (case_id,),
            )


def escalate_issue(case_id: int, issue_id: int, note: str = "") -> None:
    with db_pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "UPDATE support_issues SET status = 'escalated', resolution_summary = %s "
            "WHERE case_id = %s AND issue_id = %s RETURNING issue_id",
            (note.strip() or "Escalated for senior review", case_id, issue_id),
        )
        if not cur.fetchone():
            raise ValueError("Issue not found or could not be escalated.")
        cur.execute(
            "UPDATE support_cases SET priority = 'high', status = 'in_progress' WHERE case_id = %s",
            (case_id,),
        )


def get_order_details(order_id: int) -> dict | None:
    with db_pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT o.*, c.name AS customer_name, c.email AS customer_email, c.phone AS customer_phone
               FROM orders o
               JOIN customers c ON c.customer_id = o.customer_id
               WHERE o.order_id = %s""",
            (order_id,),
        )
        order = cur.fetchone()
        if not order:
            return None
        cur.execute(
            "SELECT * FROM order_items WHERE order_id = %s ORDER BY order_item_id",
            (order_id,),
        )
        order["items"] = cur.fetchall() or []
        cur.execute(
            "SELECT * FROM order_actions WHERE order_id = %s ORDER BY created_at DESC",
            (order_id,),
        )
        order["actions"] = cur.fetchall() or []
        cur.execute(
            "SELECT * FROM support_issues WHERE order_id = %s ORDER BY issue_id DESC",
            (order_id,),
        )
        order["issues"] = cur.fetchall() or []
        return order


def get_customer_details(customer_id: int) -> dict | None:
    with db_pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM customers WHERE customer_id = %s", (customer_id,))
        cust = cur.fetchone()
        if not cust:
            return None
        cur.execute(
            "SELECT * FROM orders WHERE customer_id = %s ORDER BY order_date DESC",
            (customer_id,),
        )
        cust["orders"] = cur.fetchall() or []
        cur.execute(
            "SELECT * FROM support_cases WHERE customer_id = %s ORDER BY created_at DESC",
            (customer_id,),
        )
        cust["cases"] = cur.fetchall() or []
        return cust

