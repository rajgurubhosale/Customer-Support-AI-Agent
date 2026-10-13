import json
import re
from datetime import date

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command, interrupt
from customer_support_ai_agent.db_functions import get_order_history, get_order_with_items
from customer_support_ai_agent.model import model
from customer_support_ai_agent.schemas import normalize_user_input, UserInput
from customer_support_ai_agent.issues.issue_schemas import CaseInvestigation
from customer_support_ai_agent.issues.case_ids import parse_case_id
from customer_support_ai_agent.issues.issues_db import get_case_for_customer, create_case_with_issues
from customer_support_ai_agent.issues.prompts import INVESTIGATOR_SYSTEM_PROMPT, ORDER_TOOL_PROMPT
from customer_support_ai_agent.issues.ui_payloads import (
    build_clarification_payload, build_review_payload, build_track_case_payload,
    build_track_case_card, build_answer_payload,
)

adjudicator_llm = model.with_structured_output(CaseInvestigation)
REVIEW_FINDING = "The order record does not resolve this concern. A support specialist needs to review it."


def _finish(message: str, case_id: int | None = None) -> Command:
    """Reset issue state, append a final message, and route back to the start node."""
    update = {"action_type": None, "draft": None, "guard_retries": 0,
              "case_id": str(case_id) if case_id is not None else None,
              "messages": [AIMessage(content=message)]}
    return Command(update=update, goto="start_node")


def order_view(order: dict) -> dict:
    """Extract and format key order facts (status, schedule flags, and items) for tools and guards."""
    expected = order.get("expected_delivery_date")
    try:
        expected_day = date.fromisoformat(str(expected)[:10]) if expected else None
    except ValueError:
        expected_day = None
    today = date.today()
    active = order.get("status") in {"Placed", "Processing", "Shipped"}

    return {
        "order_id": order["order_id"],
        "status": order.get("status"),
        "expected_day": str(expected_day) if expected_day else None,
        "overdue": bool(active and expected_day and expected_day < today),
        "on_schedule": bool(active and expected_day and expected_day >= today),
        "date_conflict": bool(active and order.get("delivery_date")),
        "items": [
            {
                "order_item_id": i["order_item_id"],
                "product_name": i["product_name"],
                "variant": i.get("variant") or {},
                "quantity": i.get("quantity", 1),
            }
            for i in order.get("items") or []
        ],
    }


def make_order_tools(customer_id: int):
    """Create order lookup tools bound to a specific customer's account."""
    @tool
    def list_my_orders() -> list[dict]:
        """Fetch the customer's recent orders when the target order is not specified."""
        return get_order_history(customer_id, limit=5) or []

    @tool
    def get_my_order(order_id: int | str) -> dict:
        """Fetch details, items, and delivery facts for an order owned by this customer."""
        tokens = re.findall(r"\d+", str(order_id))
        if len(tokens) != 1:
            return {"error": "Ambiguous or invalid order ID. Please provide a single order number like ORD-15 or 15."}
        digits = tokens[0]
        order = get_order_with_items(int(digits), customer_id)
        return order_view(order) if order else {"error": f"Order #{digits} not found under this account."}

    return [list_my_orders, get_my_order]


MAX_TOOL_ROUNDS = 4

def issue_agent_node(state) -> Command:
    """Let the agent call customer-bound, read-only order tools (bounded loop), then hand off to finalize."""
    tool_list = make_order_tools(int(state["user_id"]))
    tools = {tool.name: tool for tool in tool_list}
    llm = model.bind_tools(tool_list)

    history = [SystemMessage(content=ORDER_TOOL_PROMPT), *state.get("messages", [])]
    new_messages = []

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            reply = llm.invoke(history + new_messages)
        except Exception:
            return _finish("I couldn't check your order right now. Type 'ticket' to talk to a specialist, or try again later.")

        new_messages.append(reply)
        if not reply.tool_calls:
            break

        for call in reply.tool_calls:
            tool = tools.get(call["name"])
            try:
                result = tool.invoke(call.get("args") or {}) if tool else {"error": "Unknown tool."}
            except Exception:
                result = {"error": "Order lookup failed. Please try again."}
            new_messages.append(ToolMessage(content=json.dumps(result, default=str),
                                            tool_call_id=call["id"], name=call["name"]))


    return Command(update={"messages": new_messages}, goto="issue_finalize_node")




def guard(draft: dict, customer_id: int) -> list[str]:
    """Validate that the case draft references a customer-owned order, valid items, and allowed auto-answers."""
    issues = draft.get("issues") or []
    
    order_ids = {issue.get("order_id") for issue in issues}

    if len(order_ids) != 1 or None in order_ids:
        return ["Please identify one order for this case and keep other orders separate."]

    order_id = next(iter(order_ids))
    order = get_order_with_items(order_id, customer_id)
    if not order:
        return [f"ORD-{order_id} was not found under this account."]

    facts = order_view({**order, "order_id": order_id})

    item_ids = {item["order_item_id"] for item in facts["items"]}

    problems = []
    for issue in issues:
        item_id = issue.get("order_item_id")
        if issue.get("issue_type") == "item_issue" and item_id is None:
            problems.append("Ask which purchased item has the issue.")
        elif item_id is not None and item_id not in item_ids:
            problems.append(f"Item #{item_id} is not in ORD-{order_id}.")
        if issue.get("next_step") == "answer":
            allowed = (issue.get("issue_type") == "delivery_issue" and issue.get("kind") == "delayed"
                       and facts["on_schedule"] and not facts["date_conflict"])
            if allowed:
                issue["explanation"] = (f"ORD-{order_id} is recorded as {facts['status']}. "
                                        f"Its expected delivery date is {facts['expected_day']}, which has not passed.")
            else:
                issue.update(next_step="open_case", explanation=REVIEW_FINDING)
    if problems:
        choices = ", ".join(f"#{item['order_item_id']} {item['product_name']}" for item in facts["items"])
        return [*problems, f"Verified items in ORD-{order_id}: {choices or 'none'}. Do not guess an item ID."]
    return []



def issue_finalize_node(state) -> Command:
    """
    Generate a structured case investigation draft and validate it before user review.
    It transforms raw tool outputs into a validated case proposal before the customer sees it.
    """
    try:
        draft = adjudicator_llm.invoke([
            SystemMessage(content=INVESTIGATOR_SYSTEM_PROMPT),
            *state.get("messages", []),
        ]).model_dump()

    except Exception:
        draft = None
    
    if draft and any(issue.get("next_step") == "ask_customer" for issue in draft["issues"]):
        return Command(update={"draft": draft}, goto="issue_wait_node")


    problems = guard(draft, int(state["user_id"])) if draft else ["The issue details could not be verified."]

    if problems:
        retries = state.get("guard_retries", 0) + 1
        if retries >= 2:
            return _finish("I couldn't verify the issue details. No case was created. Type 'ticket' to talk to a specialist.")
        return Command(update={"guard_retries": retries,
                               "messages": [SystemMessage(content="Verification feedback: " + " ".join(problems))]},
                       goto="issue_agent_node")
    return Command(update={"draft": draft, "guard_retries": 0}, goto="issue_review_node")



def _choices(customer_id: int, issue: dict) -> list[dict]:
    """
    Return quick-reply buttons for customer clarification:
    - Recent orders when order_id is missing.
    - Purchased items when clarifying which item has an issue.
    - Empty list when free-text input is required.
    """
    if issue.get("order_id") is None and issue.get("issue_type") in {"delivery_issue", "item_issue"}:
        orders = get_order_history(customer_id, limit=5) or []
        buttons = []
        for order in orders:
            name = f"ORD-{order['order_id']}"
            buttons.append({"label": name, "value": name})
        return buttons

    if issue.get("issue_type") == "item_issue" and issue.get("order_item_id") is None:
        order = get_order_with_items(issue["order_id"], customer_id) or {}
        buttons = []
        for item in order.get("items", []):
            buttons.append({"label": item["product_name"], "value": f"Item #{item['order_item_id']}"})
        return buttons

    return []


def ask_user(payload: dict) -> tuple[UserInput, str | None]:
    """Interrupt the graph with a UI payload and return normalized (choice, button_action)."""
    raw = interrupt(payload)
    choice = normalize_user_input(raw)
    button = choice.data.get("value") if choice.data.get("action") == choice.data.get("value") else None
    return choice, button


def issue_wait_node(state) -> Command:
    """Interrupt execution to ask the customer a clarification question and resume with their answer."""
    draft = state.get("draft") or {}
    issues = draft.get("issues") or []

    issue = {}
    for item in issues:
        if item.get("next_step") == "ask_customer":
            issue = item
            break

    choices = _choices(int(state["user_id"]), issue)

    payload = build_clarification_payload(issue.get("question"), choices)

    answer, button = ask_user(payload)

    if button == "cancel" or answer.lower_text in {"cancel", "abort", "exit"}:
        return _finish("No case was created.")

    answer_text = button or answer.text.strip()
    if not answer_text:
        return Command(goto="issue_wait_node")

    return Command(update={"messages": [HumanMessage(content=answer_text)],
                           "draft": None, "guard_retries": 0}, goto="issue_agent_node")


def issue_review_node(state) -> Command:
    """Present the case draft or resolution to the customer for approval, edits, or cancellation."""
    draft = state.get("draft") or {}
    issues = draft.get("issues") or []
    if not issues:
        return _finish("I couldn't verify the issue details. No case was created.")

    answered = all(issue["next_step"] == "answer" for issue in issues)
    payload = build_answer_payload(issues) if answered else build_review_payload(issues)
    choice, button = ask_user(payload)

    if button == ("solved" if answered else "confirm"):
        return Command(goto="issue_submit_node")

    if button == "cancel":
        return _finish("No case was created.")

    if answered and button == "need_help":
        changed = [{**issue, "next_step": "open_case", "explanation": REVIEW_FINDING} for issue in issues]
        return Command(update={"draft": {**draft, "issues": changed}}, goto="issue_review_node")

    if button == "edit":
        question = {"issues": [{"next_step": "ask_customer", "question": "What would you like to change?"}]}
        return Command(update={"draft": question}, goto="issue_wait_node")

    label = "That solved it" if answered else "Submit Case"
    return Command(
        update={"messages": [AIMessage(content=f"Please click **{label}**, **Edit**, or **Cancel** to proceed.")]},
        goto="issue_review_node"
    )


def issue_submit_node(state) -> Command:
    """Re-validate the approved case draft and save it to the database."""
    draft = state.get("draft") or {}
    issues = draft.get("issues") or []

    approved_answer = bool(issues) and all(issue.get("next_step") == "answer" for issue in issues)

    fresh = {**draft, "issues": [dict(issue) for issue in issues]}

    problems = guard(fresh, int(state["user_id"])) if issues else ["No issues to submit."]

    if problems:
        return _finish("I couldn't verify the issue details. No case was created. Type 'ticket' to talk to a specialist.")
    if fresh["issues"] != issues:
        return Command(update={"draft": fresh}, goto="issue_review_node")

    complaint = "\n".join(msg.content for msg in state.get("messages", []) if isinstance(msg, HumanMessage))
    
    rows = []
    for issue in fresh["issues"]:
        is_answer = issue.get("next_step") == "answer"
        rows.append({
            "issue_type": issue["issue_type"],
            "kind": issue.get("kind"),
            "order_id": issue["order_id"],
            "order_item_id": issue.get("order_item_id"),
            "description": issue.get("description") or complaint,
            "item_reference": issue.get("item_reference"),
            "reported": issue.get("reported") or {},
            "status": "resolved" if is_answer else "escalated",
            "resolution_summary": issue.get("explanation") if is_answer else None,
        })
    try:
        case_id = create_case_with_issues(
            customer_id=int(state["user_id"]), thread_id=state.get("session_id") or "web",
            raw_message=complaint, summary=draft.get("summary") or "Support case",
            priority=draft.get("overall_priority") or "medium", issues=rows,
            resolution_source="assistant" if approved_answer else None,
        )
    except ValueError as error:
        return _finish(f"Order verification failed: {error}. No case was created.")
    receipt = f"✅ Case #CASE-{case_id} was saved as resolved." if approved_answer else f"✅ Support Case #CASE-{case_id} was created for review."
    return _finish(f"{receipt} You can track it with CASE-{case_id}.", case_id)

def track_case_node(state) -> Command:
    """Prompt for a Case ID, verify customer ownership, and return the case tracking status."""
    case_id = state.get("case_id")

    if not case_id:
        user_input, button = ask_user(build_track_case_payload())
        if button == "cancel" or user_input.lower_text in {"cancel", "abort", "exit"}:
            return _finish("Returned to main menu.")
        
        case_id = parse_case_id(user_input.text)
        if not case_id:
            return Command(
                update={"case_id": None, "messages": [AIMessage(content="⚠️ Please enter a Case ID like CASE-1")]},
                goto="track_case_node"
            )

    case = get_case_for_customer(int(case_id), int(state["user_id"]))

    if not case:
        return Command(
            update={"case_id": None, "messages": [AIMessage(content=f"⚠️ CASE-{case_id} was not found under your account.")]},
            goto="track_case_node",
        )
        
    return Command(
        update={"action_type": None, "case_id": None, "messages": [AIMessage(content=build_track_case_card(case))]},
        goto="start_node"
    )
