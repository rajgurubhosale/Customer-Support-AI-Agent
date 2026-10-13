import json
import hashlib
from typing import Any, Dict, List, Optional
from customer_support_ai_agent.db_functions import db_pool


def get_cases_for_customer(customer_id: int, limit: int = 5) -> list[dict]:
    """List this customer's recent support cases for the sidebar."""
    with db_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT c.case_id, c.status, c.priority, c.summary,
                          GREATEST(c.updated_at, COALESCE(
                              (SELECT MAX(i.updated_at) FROM support_issues i WHERE i.case_id = c.case_id),
                              c.updated_at
                          )) AS updated_at
                   FROM support_cases c WHERE c.customer_id = %s
                   ORDER BY updated_at DESC LIMIT %s""",
                (int(customer_id), limit),
            )
            return cur.fetchall() or []


def get_case_for_customer(case_id: int, customer_id: int) -> Optional[dict]:
    """Safely fetch a support case and its child issues for a verified customer.
    expected_output:
    {
    "case_id": 12,
    "customer_id": 3,
    "status": "open",
    "priority": "high",
    "summary": "Order 15 delayed package and damaged keyboard",
    "issues": [
        {"issue_id": 1, "issue_type": "delivery_issue", "status": "escalated", ...},
        {"issue_id": 2, "issue_type": "item_issue", "status": "escalated", ...}
    ]
}


    
    """
    try:
        clean_case_id = int(case_id)
        clean_customer_id = int(customer_id)
    except (ValueError, TypeError):
        print(f"Invalid input: case_id={case_id}, customer_id={customer_id}")
        return None

    try:
        with db_pool.connection() as conn:
            with conn.cursor() as cur:
                #  Fetch parent case with customer ownership check
                cur.execute(
                    """
                    SELECT * 
                    FROM support_cases 
                    WHERE case_id = %s AND customer_id = %s
                    """,
                    (clean_case_id, clean_customer_id),
                )
                case = cur.fetchone()
                if not case:
                    return None

                # Fetch child issues linked to this case
                cur.execute(
                    """
                    SELECT * 
                    FROM support_issues 
                    WHERE case_id = %s 
                    ORDER BY issue_id ASC
                    """,
                    (clean_case_id,),
                )
                case["issues"] = cur.fetchall() or []
                return case
    except Exception as e:
        print(f"Error fetching case #{case_id}: {e}")
        return None



# WE SHOULD CONFIRM BEFORE THE ISSUE , CASE GETS CREATED I MEAN The submit button
# AUTO HANDLED ISSUES ALSO GETS SAVED DIRECTLY
def create_case_with_issues(
    customer_id: int,
    thread_id: str,
    raw_message: str,
    summary: str,
    priority: str,
    issues: List[Dict[str, Any]],
    resolution_source: Optional[str] = None,
) -> int:
    """Validate links, then create one case and all issues atomically."""
    if not issues:
        raise ValueError("At least one issue is required.")
    if len({issue.get("order_id") for issue in issues}) != 1:
        raise ValueError("Please create a separate case for each order.")
    if resolution_source not in (None, "assistant"):
        raise ValueError("Unsupported resolution source.")

    target_order_id = next(iter({issue.get("order_id") for issue in issues}))
    submission_key = hashlib.sha256(
        f"{customer_id}:{thread_id}:{target_order_id}:{raw_message}".encode("utf-8")
    ).hexdigest()

    with db_pool.connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                # Validate every issue before inserting the parent case.
                for issue in issues:
                    issue_type = issue.get("issue_type")
                    if issue_type not in {"delivery_issue", "item_issue"}:
                        raise ValueError("Unsupported issue type for this V1 flow.")

                    order_id = issue.get("order_id")
                    if order_id is None:
                        raise ValueError("An order is required.")

                    cur.execute(
                        "SELECT 1 FROM orders WHERE order_id = %s AND customer_id = %s",
                        (int(order_id), int(customer_id)),
                    )
                    if not cur.fetchone():
                        raise ValueError("Order does not belong to this customer.")

                    item_id = issue.get("order_item_id")
                    if issue_type == "item_issue" and item_id is None:
                        raise ValueError("An item is required for item issues.")

                    if item_id is not None:
                        cur.execute(
                            "SELECT 1 FROM order_items "
                            "WHERE order_item_id = %s AND order_id = %s",
                            (int(item_id), int(order_id)),
                        )
                        if not cur.fetchone():
                            raise ValueError("Item does not belong to the verified order.")

                cur.execute(
                    """
                    INSERT INTO support_cases (
                        customer_id, thread_id, raw_message,
                        summary, priority, status, resolution_source,
                        submission_key, resolved_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                              CASE WHEN %s = 'assistant' THEN CURRENT_TIMESTAMP ELSE NULL END)
                    ON CONFLICT (submission_key) DO NOTHING
                    RETURNING case_id
                    """,
                    (
                        int(customer_id), thread_id, raw_message, summary, priority,
                        "resolved" if resolution_source == "assistant" else "open",
                        resolution_source, submission_key, resolution_source,
                    ),
                )
                created = cur.fetchone()
                if not created:
                    cur.execute(
                        "SELECT case_id FROM support_cases WHERE submission_key = %s AND customer_id = %s",
                        (submission_key, int(customer_id)),
                    )
                    return cur.fetchone()["case_id"]
                case_id = created["case_id"]

                for issue in issues:
                    details = {
                        "kind": issue.get("kind"),
                        "reported": issue.get("reported", {}),
                        "item_reference": issue.get("item_reference"),
                    }
                    cur.execute(
                        """
                        INSERT INTO support_issues (
                            case_id, order_id, order_item_id, issue_type,
                            description, details, status, resolution_summary, resolved_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                                  CASE WHEN %s = 'resolved' THEN CURRENT_TIMESTAMP ELSE NULL END)
                        """,
                        (
                            case_id,
                            issue["order_id"],
                            issue.get("order_item_id"),
                            issue["issue_type"],
                            issue["description"],
                            json.dumps(details),
                            issue.get("status", "open"),
                            issue.get("resolution_summary"),
                            issue.get("status", "open"),
                        ),
                    )

                return case_id
