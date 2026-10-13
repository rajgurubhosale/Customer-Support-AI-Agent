from IPython.core import display_functions
from IPython.core import display_functions
import hashlib
import json
import re
from typing import Any, Optional
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.types import interrupt
from pydantic import ValidationError

from customer_support_ai_agent.state import CustomerState
from customer_support_ai_agent.schemas import (
    normalize_user_input,
    PartialItemSelection,
    UserInput,
    UserIntent,
)
from customer_support_ai_agent.db_functions import get_order_with_items, get_order_history, execute_order_action
from customer_support_ai_agent.intent_router import classify_user_intent
from customer_support_ai_agent.issues.case_ids import parse_case_id
from customer_support_ai_agent.ui_payloads import (
    build_welcome_payload,
    build_post_action_payload,
    build_order_list_payload,
    build_item_selection_payload,
    build_confirmation_payload,
    build_receipt_message,
    build_blocked_payload,
    build_escalation_message,
)
from customer_support_ai_agent.policy_rules import get_eligible_items,check_order_eligibility


# HELPER FUNCTIONS

def reset_to_menu(message: Optional[str] = None, action_type:Optional[str]=None) -> dict:
    """
    Performs a full state reset.
    Returns a dictionary suitable for updating the CustomerState.

    """
    cleared_state  = {
        "action_type": action_type,
        "order_id": None,
        "customer_details": None,
        "confirmed": None,
        "context": None,
    }
    if message:
        cleared_state["messages"] = [AIMessage(content=message)]
    return cleared_state 


def _check_for_exit_menu_human_support(user_text: str, message: Optional[str] = None) -> Optional[dict]:
    """
    
    Checks if the user wants to exit, go back to the menu, or talk to support.

    """
    text = user_text.lower().strip()

    # End the entire conversation.
    if text in ("exit", "quit", "bye"):
        return reset_to_menu(
            message="Thank you for contacting us. Goodbye!",
            action_type="exit",
        )

    if text in ("menu", "main menu", "back", "abort"):
        return reset_to_menu(message)

    if text == "ticket":
        return {"action_type": "human_support", "confirmed": None}
    
    return None


def interrupt_and_get_user_response(
    payload: dict,
    cancel_message: Optional[str] = None,
    ) -> tuple[UserInput, Optional[dict]]:
    
    """
    Interrupts graph execution to display the UI payload to the user,
    normalizes the incoming response, and checks for global commands
    (exit, quit, menu, back, abort, ticket).
    """
    
    user_input = normalize_user_input(interrupt(payload))

    cmd = _check_for_exit_menu_human_support(
        user_input.action or user_input.lower_text,
        message=cancel_message,
    )
    return user_input, cmd


def _format_order_card(order: dict) -> str:
    """
    it runs when the customer asks for specific order id details 
    it returns markdown string to show  a detailed order card showing status, 
    total amount, and itemized quantities with prices.
    """
    
    order_id = order.get("order_id")
    status = order.get("status")
    order_date = str(order.get("order_date"))[:10]
    total_amount = float(order.get("total_amount", 0))
    
    item_lines = []

    for item in order.get("items", []):
        name = item.get("product_name", "Item")
        quantity = item.get("quantity", 1)
        price = float(item.get("unit_price", 0))
        item_status = item.get("item_status")
        status_tag = f" — [{item_status}]" if item_status else ""
        item_lines.append(f"- **{name}** — Qty: {quantity} (₹{price:.2f}){status_tag}")
    items_summary = "\n".join(item_lines) or "- No item details found"

    return (
        f"📦 **Order Details: #ORD-{order_id}**\n\n"
        f"- **Status:** **{status}**\n"
        f"- **Order Date:** {order_date}\n"
        f"- **Total Amount:** ₹{total_amount:.2f}\n\n"
        f"🛒 **Items in this order:**\n{items_summary}"
    )


def _format_recent_orders(orders: list[dict],limit:int = 5) -> str:
    """
    user aks genrally show my last orders then it 
    returns a markdown string to show the  summary list of the 5 newest orders 
    (ID, status, date, total) so the customer can pick one.
    """

    if not orders:
        return "📦 You don't have any past orders on record."

    cards = []
    for order in orders[:limit]:
        order_id = order.get("order_id")
        status = order.get("status")
        total = float(order.get("total_amount", 0))
        date = str(order.get("order_date"))[:10]

        cards.append(
            f"📦 **Order #ORD-{order_id}** — Status: **{status}**\n"
            f"  💰 Total: ₹{total:.2f} | 📅 Ordered: {date}"
        )

    return "🧾 **Here are your recent orders:**\n\n" + "\n\n".join(cards)

def _validate_and_fetch_order(val: Any, user_id: int) -> Optional[dict]:
    """
    Extracts an order ID from text (e.g., 'ORD-74') and verifies it belongs
    to the user in the database. Returns the order data if valid, else None.
    """
    if not val:
        return None
    match = re.match(r"^(?:ord-?|#|order\s*)?(\d+)$", str(val), re.IGNORECASE)
    if match:
        order_id = match.group(1)
        order = get_order_with_items(int(order_id), customer_id=user_id)
        if order:
            return {"customer_details": order, "order_id": order_id}
            
    return None


def _handle_tracking_response(
    order_id: Optional[str],
    user_id: int,
    reply: Optional[str] = None,
) -> dict:
    """Single authoritative resolver for order tracking queries."""
    found = _validate_and_fetch_order(order_id, user_id)

    if found:
        card = _format_order_card(found["customer_details"])
        msg = f"{reply}\n\n{card}" if reply else card

    elif order_id:
        msg = f"⚠️ I couldn't find order #{order_id} under your account."

    elif reply:
        msg = reply

    else:
        msg = _format_recent_orders(get_order_history(user_id) or [])

    return reset_to_menu(msg)

def _handle_midflow_redirect(
    decision: UserIntent,
    user_id: int,
    current_action: Optional[str] = None,
    abort_msg: Optional[str] = None,
    raw_text: Optional[str] = None,
    fallback_order_id: Optional[str] = None,
) -> Optional[dict]:
    """Handle a change of intent while clearing the previous workflow state."""
    if decision.intent == "abort":
        return reset_to_menu(abort_msg)

    if decision.intent == "human_support":
        return {"action_type": "human_support", "confirmed": None}

    if decision.intent == "track_order":
        target_order = decision.order_id or fallback_order_id
        return _handle_tracking_response(target_order, user_id, reply=decision.reply)

    if (
        decision.intent in ("cancel_order", "return_order", "report_issue")
        and decision.intent != current_action
    ):
        messages = ([RemoveMessage(id=REMOVE_ALL_MESSAGES), HumanMessage(content=raw_text.strip())]
                    if decision.intent == "report_issue" and raw_text and raw_text.strip()
                    else [AIMessage(content=decision.reply)] if decision.reply else [])
        return {
            "action_type": decision.intent,
            "order_id": None if decision.intent == "report_issue" else decision.order_id,
            "customer_details": None,
            "context": None,
            "confirmed": None,
            "messages": messages,
            "draft": None,
            "guard_retries": 0,
        }

    if decision.intent == "track_case":
        return {
            "action_type": "track_case",
            "case_id": parse_case_id(raw_text or ""),
            "customer_details": None,
            "context": None,
            "confirmed": None,
        }

    return None


def _normalize_order_item (db_item: dict, qty: Optional[int] = None) -> dict:
    """
    Normalizes a database order item row into a standard schema 
    (item_id, name, quantity, unit_price)
    """
    return {
        "item_id": db_item["order_item_id"],
        "name": db_item["product_name"],
        "quantity": int(qty or db_item["quantity"]),
        "unit_price": float(db_item["unit_price"]),
    }


def _validate_item_selection(payload: Any, items_by_id: dict[str, dict]) -> tuple[list[dict], Optional[str]]:
    """Audits partial selection against order inventory and returns normalized items."""
    try:
        data = PartialItemSelection.model_validate(payload)
    except ValidationError:
        return [], "Please select at least one item using whole-number quantities."

    selected = []
    seen = set()
    for entry in data.items:
        item_id = str(entry.item_id)
        db_item = items_by_id.get(item_id)

        # Reject unknown items or duplicate submissions
        if not db_item or item_id in seen:
            return [], "One of the selected items is invalid. Please try again."

        # Reject quantities exceeding what was ordered
        if entry.quantity > db_item["quantity"]:
            return [], f"Quantity for item #{item_id} must be between 1 and {db_item['quantity']}."

        seen.add(item_id)
        selected.append(_normalize_order_item(db_item, entry.quantity))

    return selected, None


# MAIN NODES

def start_node(state: CustomerState) -> dict:
    """
    Conversational front door for inquiries,
    FAQs, and intent routing.
    """
    
    user_id = state.get("user_id")

    if not user_id:
        return reset_to_menu(message="⚠️ User session expired. Please restart.")


    # show post action menu if order was just processed otherwise show welcome menu
    is_post_action = bool(state.get("confirmed"))

    if is_post_action:
        payload = build_post_action_payload()
    else:
        payload = build_welcome_payload(is_followup=bool(state.get("messages")))
    
    
    user_input, cmd = interrupt_and_get_user_response(payload)
    
    # check if user wants to exit or menu or talk to human
    if cmd:
        return cmd

    # Fast-path for direct UI button clicks (0 LLM latency)
    if user_input.action == "report_issue":
        return {
        "action_type": "report_issue",
        "confirmed": None,
        "order_id": None,
        "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
        "draft": {"issues": [{"next_step": "ask_customer", "question": "Please describe what happened with your order or item."}]},
        "guard_retries": 0,
    }


    if user_input.action == "track_case":
        return {"action_type": "track_case",
                "case_id": parse_case_id(str(user_input.data.get("case_id") or "")),
                "confirmed": None}

    if case_id := parse_case_id(user_input.text):
        return {"action_type": "track_case", "case_id": case_id, "confirmed": None}

    # Routes customer to cancel, return, tracking, human support, or abort
    decision = classify_user_intent(user_input.text)

    fallback_order_id = state.get("order_id")
    if not fallback_order_id and state.get("messages"):
        for m in reversed(state.get("messages", [])):
            content = getattr(m, "content", "")
            m_match = re.search(r"\bORD-(\d+)\b", content, re.IGNORECASE)
            if m_match:
                fallback_order_id = m_match.group(1)
                break

    redirect = _handle_midflow_redirect(
        decision,
        int(user_id),
        abort_msg="No problem! Have a wonderful day! 👋",
        raw_text=user_input.text,
        fallback_order_id=fallback_order_id,
    )
    if redirect is not None:
        return redirect

    # Policy FAQs & Conversational chat (AI generated reply)
    answer = decision.reply or "How can I help you with your order today?"

    return {"messages": [AIMessage(content=answer)], "confirmed": None, "action_type": None}


def order_lookup_node(state: CustomerState) -> dict:
    """
    Finds and validates the customer's order for cancellation or return.
    Resolves orders from prior state, instant button clicks, or chat messages.
    """

    user_id = int(state.get("user_id"))
    action = state.get("action_type") or "cancel_order"

    # If order_id was already provided by user
    found_order = _validate_and_fetch_order(state.get("order_id"), user_id)
    if found_order:
        return found_order


    # Fetch orders of the user to show on UI
    all_orders = get_order_history(user_id,limit=5) or []
    eligible_orders = []
    for summary in all_orders:
        order = summary if summary.get("items") else get_order_with_items(summary["order_id"], customer_id=user_id)
        if order and check_order_eligibility(order, action) is None:
            eligible_orders.append(order)
    payload = build_order_list_payload(action,eligible_orders)
    user_input, cmd = interrupt_and_get_user_response(payload)


    if user_input.action == "track_order":
        return _handle_tracking_response(None, user_id)   

    if cmd:
        return cmd

    # section A: Fast order ID check by button click
    found_order = _validate_and_fetch_order(user_input.text, user_id)
    if found_order:
        return found_order

    # section B : for conversational queries handled by AI
    decision = classify_user_intent(user_input.text)
    redirect = _handle_midflow_redirect(
        decision,
        user_id,
        current_action=action,
        raw_text=user_input.text,
    )
    if redirect is not None:
        return redirect

    found_order = _validate_and_fetch_order(decision.order_id, user_id)
    if found_order:
        return found_order

    # SECTION C: user asked an FAQ or policy question, show the AI answer
    if decision.reply:
        return {"messages": [AIMessage(content=f"ℹ️ {decision.reply}")]}


    if not eligible_orders:
        return {"messages": [AIMessage(content="ℹ️ You don't have any orders eligible for this action.")]}


    return {
        "messages": [AIMessage(content="⚠️ I couldn't find an order matching that ID in your account. Please select one of your eligible orders below:")],
    }


def select_items_node(state: CustomerState) -> dict:
    """
    Presents item selection form.
    100% deterministic for button clicks and checkboxes

    """

    user_id = int(state.get("user_id"))
    action = state.get("action_type")
    order = state.get("customer_details")
    order_id = str(state.get("order_id"))

    
    if not order or not order.get("items"):
        order = get_order_with_items(int(order_id), customer_id=user_id) 

    items = order.get("items")
    active_items = get_eligible_items(action, items)

    items_map = {}
    for item in active_items:
        item_id = str(item["order_item_id"])
        items_map[item_id] = item

    payload = build_item_selection_payload(order_id, action, active_items)

    user_input, cmd = interrupt_and_get_user_response(
        payload,
        cancel_message="Cancelled item selection. Returning to main menu.",
    )
    if cmd:
        return cmd

    # Case A: Whole order button click
    if user_input.data.get("scope") == "all" or user_input.text.lower() == "all":
        selected_items = []
        for item in active_items:
            normalized = _normalize_order_item(item)
            selected_items.append(normalized)
        scope = "all"


    # Case B: Partial item selection via UI steppers
    elif user_input.data.get("scope") == "partial":

        selected_items, error = _validate_item_selection(user_input.data, items_map)

        if error:
            return {"context": None, "messages": [AIMessage(content=f"⚠️ {error} No changes were made.")]}

        scope = "partial"

    # Case C: Free-form chat text (FAQs or action switch)

    else:
        
        decision = classify_user_intent(user_input.text)
        redirect = _handle_midflow_redirect(
            decision,
            user_id,
            current_action=action,
            abort_msg="Understood! Returning to main menu.",
            raw_text=user_input.text,
        )
        if redirect is not None:
            return redirect

        if decision.reply:
            return {"messages": [AIMessage(content=f"💡 **Policy Info:** {decision.reply}")]}

        return {
            "context": None,
            "messages": [AIMessage(content="⚠️ Please use the quantity selectors or choose the whole-order option. No changes were made.")],
        }


    if not selected_items:
        return {"context": None, "messages": [AIMessage(content="⚠️ No eligible items were selected. No changes were made.")]}

    refund = sum(it["quantity"] * it["unit_price"] for it in selected_items)
    return {
        "context": {
            "order_id": order_id,
            "items": selected_items,
            "refund_amount": float(refund),
            "scope": scope,
        }
    }

def confirm_action_node(state: CustomerState) -> dict:
    """
    Deterministic confirmation gate with intent handling for questions and escalation.
    """
    
    action = state.get("action_type")
    ctx = state.get("context") or {}
    order_id = ctx.get("order_id") or ""
    selected_items = ctx.get("items", [])
    refund = ctx.get("refund_amount", 0.0)

    if action not in ("cancel_order", "return_order") or not (order_id and selected_items):
        return reset_to_menu("⚠️ Transaction session expired or invalid. Please select an option from the menu.")
        
    if action == "cancel_order":
        noun = "cancellation"
    else:
        noun = "return"

    payload = build_confirmation_payload(order_id, action, selected_items, refund)

    abort_msg = f"No problem! Order #ORD-{order_id} remains active with no changes made."
    user_input, cmd = interrupt_and_get_user_response(payload, cancel_message=abort_msg)

    if cmd:
        return cmd

    # Section A: Explicit UI action or exact typed command.
    if user_input.action == "confirm":
        return {"confirmed": True}

    # Section B: Interpret every other free-text response without authorizing the action.
    decision = classify_user_intent(user_input.text)

    if decision.intent == "abort":
        return reset_to_menu(abort_msg)

    if decision.intent == "human_support":
        return {"action_type": "human_support"}

    if action == "cancel_order":
        opposite_action, opposite_verb = "return_order", "return"
    else:
        opposite_action, opposite_verb = "cancel_order", "cancel"
    
    if decision.intent == opposite_action:
        return reset_to_menu(
            f"Got it, I've stopped the {noun}! If you'd like to {opposite_verb} an item instead, "
            f"please choose **{opposite_verb.title()} Order** from the menu below."
            )


    if decision.intent == "faq" or decision.reply:
        reply_content = decision.reply or "Please let me know if you have questions regarding our store policies."
        return {
            "messages": [   
                AIMessage(
                    content=f"💡 {reply_content}\n\n"
                            f"Whenever you're ready **Confirm {noun.title()}** or type **“confirm”**."
                )
            ]
        }

    return {
        "messages": [
            AIMessage(
                content=f"Just to make sure I don't make a mistake: please click **Confirm {noun.title()}** "
                       f"(or type **confirm**) to proceed, or click **Keep Order** to leave everything as is."
            )
        ]
    }


def _execute_action_node(state: CustomerState, action: str) -> dict:
    """Write the confirmed action before showing a receipt."""
    ctx = state.get("context") or {}
    try:
        if not state.get("session_id") or not state.get("user_id"):
            raise ValueError("Your session expired. Please start again.")
        order_id = int(ctx["order_id"])
        items = ctx["items"]
        key_data = [state["session_id"], state["user_id"], action, order_id, items]
        key = hashlib.sha256(json.dumps(key_data, sort_keys=True).encode()).hexdigest()
        result = execute_order_action(
            int(state["user_id"]), order_id, action, items, ctx["refund_amount"], key,
        )
        receipt = build_receipt_message(str(order_id), action, result["items"],
                                        result["refund_amount"], result["action_id"])
    except (KeyError, TypeError, ValueError) as error:
        return reset_to_menu(f"⚠️ No changes were made. {error}")
    except Exception:
        return reset_to_menu("⚠️ We couldn't confirm the result. Please check your order before trying again.")
    return {**reset_to_menu(receipt), "confirmed": True}


def cancel_order_node(state: CustomerState) -> dict:
    return _execute_action_node(state, "cancel_order")


def return_order_node(state: CustomerState) -> dict:
    return _execute_action_node(state, "return_order")



def policy_blocked_node(state: CustomerState) -> dict:
    """Informs user when an order is ineligible under store policy."""
    action = state.get("action_type") or "cancel_order"
    order = state.get("customer_details") or {}
    order_id = str(order.get("order_id") or state.get("order_id") or "")
    reason = check_order_eligibility (order, action) or "This order is not eligible for this action."
    payload = build_blocked_payload(action, order_id, reason)
    user_input, cmd = interrupt_and_get_user_response(payload, cancel_message="Returned to main menu.")
    if cmd:
        return cmd
    return reset_to_menu("Returned to main menu.")


def human_escalate_node(state: CustomerState) -> dict:
    """Creates a support ticket and returns confirmation."""
    user_id = int(state.get("user_id") or 1)
    return reset_to_menu(build_escalation_message(user_id))
