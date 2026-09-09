from functools import lru_cache
from pathlib import Path
from datetime import datetime, date
from typing import Optional, Dict, Any, List
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

from customer_support_ai_agent.state import CustomerState
from customer_support_ai_agent.db_functions import get_order_with_items, get_order_history
from customer_support_ai_agent.prompts import FAQ_SYSTEM_PROMPT
from customer_support_ai_agent.model import model
from customer_support_ai_agent.intent_router import (
    is_button_signal,
    classify_user_intent,
    classify_confirmation,
    load_policy_files,
)
from customer_support_ai_agent.schemas import ActionSelectionPayload
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

RETURN_WINDOW_DAYS = 7


@lru_cache(maxsize=1)
def load_policy_files() -> str:
    policy_path = Path(__file__).resolve().parents[2] / "docs" / "cancellation_and_return_policy.md"
    return policy_path.read_text(encoding="utf-8")


def answer_policy_faq(query: str, user_id: int) -> str:
    """Answers store policy or order questions using FAQ_SYSTEM_PROMPT."""
    recent_orders = get_order_history(user_id) or []
    orders_summary = "\n".join([
        f"- ORD-{o.get('order_id')}: {o.get('status')} | Total: ₹{float(o.get('total_amount', 0)):.2f} | Ordered: {str(o.get('order_date'))[:10]} | Est. Delivery: {str(o.get('delivery_date'))[:10] if o.get('delivery_date') else 'Pending'}"
        for o in recent_orders[:4]
    ]) or "No recent orders found."

    system_prompt = FAQ_SYSTEM_PROMPT.format(
        store_policies=load_policy_files(),
        customer_orders=orders_summary,
    )
    try:
        ans = model.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=query),
        ]).content
        return str(ans)
    except Exception as e:
        print(f"Policy FAQ error: {e}")
        return "I can assist with store policies, orders, cancellations, and returns. Could you please rephrase?"


def reset_to_menu(message: Optional[str] = None) -> dict:
    """Centralized state wipe when customer aborts or returns to the main menu."""
    out = {
        "action_type": None,
        "order_id": None,
        "customer_details": None,
        "retry_count": 0,
        "confirmed": None,
        "context": None,
    }
    if message:
        out["messages"] = [AIMessage(content=message)]
    return out


# =====================================================================
# 1. CONVERSATIONAL FRONT DOOR (open_router_node / start_node)
# =====================================================================

def open_router_node(state: CustomerState) -> dict:
    """Conversational front door for general inquiries, policy FAQs, and intent handoffs."""
    user_id = int(state.get("user_id") or 1)
    is_post_action = bool(state.get("confirmed"))

    payload = build_post_action_payload() if is_post_action else build_welcome_payload()
    raw_input = interrupt(payload)
    user_msg = str(raw_input or "").strip()

    # Fast deterministic check
    button = is_button_signal(raw_input)
    if button == "menu":
        return reset_to_menu("Understood! Returning to the main menu.")
    if button == "ticket":
        return {"action_type": "human_support", "confirmed": None}

    # Structured AI Intent Classification
    decision = classify_user_intent(raw_input)

    if decision.intent == "abort":
        return reset_to_menu("No problem! Have a wonderful day! 👋")

    if decision.intent in ("cancel_order", "return_order"):
        verb = "cancel" if decision.intent == "cancel_order" else "return"
        return {
            "action_type": decision.intent,
            "order_id": decision.order_id,
            "confirmed": None,
            "retry_count": 0,
            "messages": [AIMessage(content=f"ℹ️ Sure, I can help you {verb} your order.")],
        }

    if decision.intent == "track_order":
        orders = get_order_history(user_id) or []
        user_lower = user_msg.lower()
        if "remaining" in user_lower:
            active = [o for o in orders if o.get("status") not in ("Cancelled", "Returned")]
            if active:
                cards = "\n\n".join([
                    f"• **Order #ORD-{o.get('order_id')}** — Status: **{o.get('status')}**\n"
                    f"  💰 Total: ₹{float(o.get('total_amount', 0)):.2f} | 📅 Ordered: {str(o.get('order_date'))[:10]} | 🚚 Est. Delivery: {str(o.get('delivery_date'))[:10] if o.get('delivery_date') else 'Pending'}"
                    for o in active
                ])
                msg = f"📦 **Here are your remaining active orders:**\n\n{cards}\n\nLet me know if you need anything else!"
            else:
                msg = "📦 **You have no remaining active orders.** All previous orders have been completed or cancelled."
        else:
            if orders:
                cards = "\n\n".join([
                    f"• **Order #ORD-{o.get('order_id')}** — Status: **{o.get('status')}**\n"
                    f"  💰 Total: ₹{float(o.get('total_amount', 0)):.2f} | 📅 Ordered: {str(o.get('order_date'))[:10]} | 🚚 Est. Delivery: {str(o.get('delivery_date'))[:10] if o.get('delivery_date') else 'Pending'}"
                    for o in orders[:4]
                ])
                msg = f"📦 **Here are your recent orders:**\n\n{cards}\n\nLet me know if you need help with cancellations, returns, or tracking!"
            else:
                msg = "📦 You don't have any past orders on record."
        return {"messages": [AIMessage(content=msg)], "confirmed": None, "action_type": None}

    if decision.intent == "human_support":
        return {"action_type": "human_support", "confirmed": None}

    # Policy FAQ
    answer = answer_policy_faq(user_msg, user_id)
    return {"messages": [AIMessage(content=answer)], "confirmed": None, "action_type": None}


start_node = open_router_node


# =====================================================================
# 2. ORDER LOOKUP NODE (order_lookup_node)
# =====================================================================

def order_lookup_node(state: CustomerState) -> dict:
    """Finds the customer's order and validates policy eligibility. Handles FAQs inline."""
    user_id = int(state.get("user_id") or 1)
    action = state.get("action_type") or "cancel_order"
    retry_count = int(state.get("retry_count") or 0)

    # Check if order was already provided by user in previous step
    order_id = state.get("order_id")
    if order_id:
        # Strip prefixes
        cleaned_id = str(order_id).lower().replace("ord-", "").replace("order-", "").replace("#", "").strip()
        if cleaned_id.isdigit():
            order = get_order_with_items(int(cleaned_id), customer_id=user_id)
            if order:
                return {"customer_details": order, "order_id": str(cleaned_id), "retry_count": 0}

    # Fetch eligible orders for this customer
    all_orders = get_order_history(user_id) or []
    if action == "cancel_order":
        eligible = [o for o in all_orders if o.get("status") in ("Placed", "Processing", "Partially_Cancelled")]
    else:
        eligible = [o for o in all_orders if o.get("status") in ("Delivered", "Partially_Returned")]

    payload = build_order_list_payload(action, eligible, retry_count)
    raw_input = interrupt(payload)

    # 1. Deterministic button signal
    button = is_button_signal(raw_input)
    if button in ("menu", "abort"):
        return reset_to_menu("Returned to main menu.")
    if button == "ticket":
        return {"action_type": "human_support"}

    # 2. AI Intent check (handles inline FAQs and workflow switches without bouncing)
    decision = classify_user_intent(raw_input)
    if decision.intent == "abort":
        return reset_to_menu("Understood! Returning to main menu.")
    if decision.intent == "human_support":
        return {"action_type": "human_support"}
    if decision.intent == "faq":
        faq_ans = answer_policy_faq(str(raw_input), user_id)
        # Inline FAQ: stays in order_lookup_node!
        return {"messages": [AIMessage(content=f"💡 **Policy Info:** {faq_ans}")]}
    if decision.intent in ("cancel_order", "return_order") and decision.intent != action:
        return {"action_type": decision.intent, "order_id": decision.order_id, "retry_count": 0}

    # 3. Determine target order ID
    input_str = str(raw_input.get("value") if isinstance(raw_input, dict) else raw_input).strip()
    target_id = decision.order_id

    if not target_id:
        # Check single eligible auto-confirmation
        if len(eligible) == 1 and input_str.lower() in ("yes", "y", "sure", "proceed", "1", "ok"):
            target_id = str(eligible[0]["order_id"])
        elif input_str.isdigit() and 1 <= int(input_str) <= len(eligible):
            target_id = str(eligible[int(input_str) - 1]["order_id"])
        else:
            cleaned = input_str.lower().replace("ord-", "").replace("order-", "").replace("#", "").strip()
            if cleaned.isdigit():
                target_id = cleaned

    if target_id and target_id.isdigit():
        order = get_order_with_items(int(target_id), customer_id=user_id)
        if order:
            return {"customer_details": order, "order_id": str(target_id), "retry_count": 0}

    # Order not found
    new_retry = retry_count + 1
    if new_retry >= 3:
        return {"retry_count": new_retry}
    return {
        "retry_count": new_retry,
        "messages": [AIMessage(content="⚠️ I couldn't find an order matching that ID in your account. Please select one of your eligible orders below:")],
    }


# =====================================================================
# 3. SELECT ITEMS NODE (select_items_node)
# =====================================================================

def select_items_node(state: CustomerState) -> dict:
    """Presents item selection form (checkboxes/quantities). Handles inline FAQs."""
    user_id = int(state.get("user_id") or 1)
    action = state.get("action_type") or "cancel_order"
    order = state.get("customer_details") or {}
    order_id = str(order.get("order_id") or state.get("order_id") or "")
    if not order or not order.get("items"):
        order = get_order_with_items(int(order_id), customer_id=user_id) or {}

    items = order.get("items", [])
    active_items = [it for it in items if it.get("item_status") not in ("Cancelled", "Returned")] or items

    payload = build_item_selection_payload(order_id, action, active_items)
    raw_input = interrupt(payload)

    # 1. Deterministic button signal
    button = is_button_signal(raw_input)
    if button in ("menu", "abort"):
        return reset_to_menu("Cancelled item selection. Returning to main menu.")

    # 2. AI Intent check (handles inline FAQs)
    decision = classify_user_intent(raw_input)
    if decision.intent == "abort":
        return reset_to_menu("Understood! Returning to main menu.")
    if decision.intent == "faq":
        faq_ans = answer_policy_faq(str(raw_input), user_id)
        return {"messages": [AIMessage(content=f"💡 **Policy Info:** {faq_ans}")]}

    # 3. Parse selected items
    selected_items: List[Dict[str, Any]] = []
    scope = "partial"

    if button == "all" or (isinstance(raw_input, str) and raw_input.strip().lower() in ("all", "entire", "whole")):
        scope = "all"
        for it in active_items:
            selected_items.append({
                "item_id": it.get("order_item_id") or it.get("id"),
                "name": it.get("product_name", "Item"),
                "quantity": int(it.get("quantity", 1)),
                "unit_price": float(it.get("unit_price", 0)),
            })
    elif isinstance(raw_input, dict) and raw_input.get("items"):
        try:
            validated = ActionSelectionPayload.model_validate(raw_input)
            scope = validated.scope
            if scope == "all":
                for it in active_items:
                    selected_items.append({
                        "item_id": it.get("order_item_id") or it.get("id"),
                        "name": it.get("product_name", "Item"),
                        "quantity": int(it.get("quantity", 1)),
                        "unit_price": float(it.get("unit_price", 0)),
                    })
            else:
                for sel in validated.items:
                    # Match to active_items
                    orig = next((it for it in active_items if (it.get("order_item_id") or it.get("id")) == sel.item_id), None)
                    price = float(orig.get("unit_price", 0)) if orig else 0.0
                    name = orig.get("product_name", "Item") if orig else "Item"
                    selected_items.append({
                        "item_id": sel.item_id,
                        "name": name,
                        "quantity": sel.quantity,
                        "unit_price": price,
                    })
        except Exception as e:
            print(f"Selection validation error: {e}")

    if not selected_items:
        # Default to all active items
        scope = "all"
        for it in active_items:
            selected_items.append({
                "item_id": it.get("order_item_id") or it.get("id"),
                "name": it.get("product_name", "Item"),
                "quantity": int(it.get("quantity", 1)),
                "unit_price": float(it.get("unit_price", 0)),
            })

    refund = sum(it["quantity"] * it["unit_price"] for it in selected_items)
    return {
        "context": {
            "order_id": order_id,
            "items": selected_items,
            "refund_amount": refund,
            "scope": scope,
        }
    }


# =====================================================================
# 4. CONFIRM ACTION NODE (confirm_action_node)
# =====================================================================
# RULE: confirm_action_node NEVER calls classify_user_intent.
# It only calls is_button_signal first, and classify_confirmation second.

def confirm_action_node(state: CustomerState) -> dict:
    """Strict confirmation gate. Zero ambiguous execution."""
    user_id = int(state.get("user_id") or 1)
    action = state.get("action_type") or "cancel_order"
    action_noun = "Cancellation" if action == "cancel_order" else "Return"
    ctx = state.get("context") or {}
    order_id = str(ctx.get("order_id") or state.get("order_id") or "")
    selected_items = ctx.get("items", [])
    refund = float(ctx.get("refund_amount", 0.0))

    payload = build_confirmation_payload(order_id, action, selected_items, refund)
    raw_input = interrupt(payload)

    # ISOLATED CONFIRMATION GATE
    is_confirmed = classify_confirmation(
        reply=raw_input,
        action_noun=action_noun,
        order_id=order_id,
        refund_amount=refund,
    )

    if is_confirmed is True:
        return {"confirmed": True}

    if is_confirmed is False:
        return reset_to_menu(f"No problem! Order #ORD-{order_id} remains active with no changes made.")

    # Unclear or policy question
    decision = classify_user_intent(raw_input)
    if decision.intent == "faq":
        faq_ans = answer_policy_faq(str(raw_input), user_id)
        # Inline FAQ: stays in confirm_action_node!
        return {"messages": [AIMessage(content=f"💡 **Policy Info:** {faq_ans}")]}

    # Ambiguous -> Safe non-execution
    raw_text = raw_input.get("value") if isinstance(raw_input, dict) else str(raw_input or "")
    return reset_to_menu(
        f"⚠️ For your protection, order {action_noun.lower()} requires 100% clear confirmation.\n\n"
        f"Your response *\"{raw_text}\"* could not be verified with 100% certainty. "
        f"No changes were made to Order #ORD-{order_id}."
    )


# =====================================================================
# 5. DEDICATED EXECUTION NODES (cancel_order_node & return_order_node)
# =====================================================================

def cancel_order_node(state: CustomerState) -> dict:
    """Executes cancellation and returns authoritative receipt message."""
    ctx = state.get("context") or {}
    order_id = str(ctx.get("order_id") or state.get("order_id") or "")
    refund = float(ctx.get("refund_amount", 0.0))
    items = ctx.get("items", [])

    receipt = build_receipt_message(order_id, "cancel_order", items, refund)
    return {
        "messages": [AIMessage(content=receipt)],
        "action_type": None,
        "order_id": None,
        "customer_details": None,
        "confirmed": True,
        "context": None,
    }


def return_order_node(state: CustomerState) -> dict:
    """Executes return and returns courier pickup receipt message."""
    ctx = state.get("context") or {}
    order_id = str(ctx.get("order_id") or state.get("order_id") or "")
    refund = float(ctx.get("refund_amount", 0.0))
    items = ctx.get("items", [])

    receipt = build_receipt_message(order_id, "return_order", items, refund)
    return {
        "messages": [AIMessage(content=receipt)],
        "action_type": None,
        "order_id": None,
        "customer_details": None,
        "confirmed": True,
        "context": None,
    }


# =====================================================================
# 6. POLICY BLOCKED NODE (policy_blocked_node)
# =====================================================================

def policy_blocked_node(state: CustomerState) -> dict:
    """Informs user when an order is ineligible under store policy."""
    action = state.get("action_type") or "cancel_order"
    order = state.get("customer_details") or {}
    order_id = str(order.get("order_id") or state.get("order_id") or "")
    status = order.get("status", "Unknown")

    reason = ""
    if action == "cancel_order" and status in ("Shipped", "Delivered"):
        reason = "Orders that have already been shipped or delivered cannot be cancelled [SEC-1.1]. You can request a return after delivery."
    elif action == "return_order" and status != "Delivered":
        reason = "Only delivered items can be returned [SEC-2.1]."

    payload = build_blocked_payload(action, order_id, status, reason)
    raw_input = interrupt(payload)

    button = is_button_signal(raw_input)
    if button == "ticket":
        return {"action_type": "human_support"}
    return reset_to_menu("Returned to main menu.")


# =====================================================================
# 7. HUMAN ESCALATION NODE (human_escalate_node)
# =====================================================================

def human_escalate_node(state: CustomerState) -> dict:
    """Creates a support ticket and returns confirmation."""
    user_id = int(state.get("user_id") or 1)
    msg = build_escalation_message(user_id)
    return {
        "messages": [AIMessage(content=msg)],
        "action_type": None,
        "order_id": None,
        "customer_details": None,
        "confirmed": None,
        "context": None,
    }
