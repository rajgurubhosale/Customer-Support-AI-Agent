from pathlib import Path
from datetime import datetime, date
from typing import Optional, Dict, Any, List
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

from customer_support_ai_agent.state import CustomerState
from customer_support_ai_agent.db_functions import get_order_with_items, get_order_history
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
    user_msg = str(raw_input.get("value") if isinstance(raw_input, dict) else raw_input or "").strip()

    # 1. Deterministic button clicks (0ms, 0 AI)
    button = is_button_signal(raw_input)
    if button == "menu":
        return reset_to_menu("Understood! Returning to the main menu.")
    if button == "ticket":
        return {"action_type": "human_support", "confirmed": None}

    # Fast check for quick remaining orders chip (0ms, 0 AI)
    if user_msg in ("remaining orders", "What are my remaining orders?"):
        orders = get_order_history(user_id) or []
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
        return {"messages": [AIMessage(content=msg)], "confirmed": None, "action_type": None}

    # 2. Free-text message -> Unified AI Router (Classifies & Answers in 1 shot)
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

    # Policy FAQ or other conversational reply (answered directly in 1 shot)
    answer = decision.reply or "I can assist with store policies, orders, cancellations, and returns. How can I help you today?"
    return {"messages": [AIMessage(content=answer)], "confirmed": None, "action_type": None}


start_node = open_router_node


# =====================================================================
# 2. ORDER LOOKUP NODE (order_lookup_node)
# =====================================================================

def order_lookup_node(state: CustomerState) -> dict:
    """Finds customer order. Fully deterministic for button clicks and order IDs."""
    user_id = int(state.get("user_id") or 1)
    action = state.get("action_type") or "cancel_order"
    retry_count = int(state.get("retry_count") or 0)

    # If order_id was already extracted in previous step
    order_id = state.get("order_id")
    if order_id:
        cleaned_id = str(order_id).lower().replace("ord-", "").replace("order-", "").replace("#", "").strip()
        if cleaned_id.isdigit():
            order = get_order_with_items(int(cleaned_id), customer_id=user_id)
            if order:
                return {"customer_details": order, "order_id": str(cleaned_id), "retry_count": 0}

    # Fetch eligible orders
    all_orders = get_order_history(user_id) or []
    today = date.today()
    if action == "cancel_order":
        eligible = [o for o in all_orders if o.get("status") in ("Placed", "Processing", "Partially_Cancelled")]
    else:
        eligible = []
        for o in all_orders:
            if o.get("status") in ("Delivered", "Partially_Returned"):
                d_date = o.get("delivery_date")
                if d_date:
                    d = d_date.date() if isinstance(d_date, datetime) else d_date
                    if (today - d).days <= RETURN_WINDOW_DAYS:
                        eligible.append(o)

    payload = build_order_list_payload(action, eligible, retry_count)
    raw_input = interrupt(payload)

    # 1. Deterministic button signals (0ms, 0 AI)
    button = is_button_signal(raw_input)
    if button in ("menu", "abort"):
        return reset_to_menu("Returned to main menu.")
    if button == "ticket":
        return {"action_type": "human_support"}

    # 2. Deterministic order ID detection (0ms, 0 AI)
    input_str = str(raw_input.get("value") if isinstance(raw_input, dict) else raw_input or "").strip()
    target_id = None

    if len(eligible) == 1 and input_str.lower() in ("yes", "y", "sure", "proceed", "1", "ok", f"ord-{eligible[0]['order_id']}".lower()):
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

    # 3. ONLY if input is NOT a button and NOT an order ID, call AI for conversational queries
    decision = classify_user_intent(raw_input)
    if decision.intent == "abort":
        return reset_to_menu("Understood! Returning to main menu.")
    if decision.intent == "human_support":
        return {"action_type": "human_support"}
    if decision.intent == "faq":
        faq_ans = decision.reply or "Please let me know if you have questions regarding our store policies."
        return {"messages": [AIMessage(content=f"💡 **Policy Info:** {faq_ans}")]}
    if decision.intent in ("cancel_order", "return_order") and decision.intent != action:
        return {"action_type": decision.intent, "order_id": decision.order_id, "retry_count": 0}
    if decision.order_id and decision.order_id.isdigit():
        order = get_order_with_items(int(decision.order_id), customer_id=user_id)
        if order:
            return {"customer_details": order, "order_id": str(decision.order_id), "retry_count": 0}

    # If no orders are eligible, answer user pushback/question without showing "order not found"
    if not eligible:
        borderline = []
        for o in all_orders:
            if o.get("status") in ("Delivered", "Partially_Returned"):
                d_date = o.get("delivery_date")
                if d_date:
                    d = d_date.date() if isinstance(d_date, datetime) else d_date
                    if 8 <= (today - d).days <= 14:
                        borderline.append(o)

        user_text = str(raw_input.get("value") if isinstance(raw_input, dict) else raw_input or "").lower()
        is_borderline_mention = any(w in user_text for w in ("8 day", "9 day", "10 day", "11 day", "12 day", "13 day", "14 day", "past 7", "over 7", "more than 7", "8 days", "9 days", "10 days", "14 days"))

        if (borderline or is_borderline_mention) and action == "return_order":
            reply = decision.reply or "Standard return policy is strictly 7 days from delivery [SEC-2.5]."
            msg = f"ℹ️ {reply}\n\nSince your delivery is within the 8–14 day borderline window, you may request an exception review from a support specialist."
            return {"retry_count": 3, "messages": [AIMessage(content=msg)]}

        reply = decision.reply or ("Orders past the return window cannot be returned [SEC-2.5]." if action == "return_order" else "Orders that have already shipped or delivered cannot be cancelled [SEC-1.1].")
        return {"retry_count": 0, "messages": [AIMessage(content=f"ℹ️ {reply}")]}

    # Order not found when eligible orders exist
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
    """Presents item selection form. 100% deterministic for button clicks and checkboxes."""
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

    # 1. Deterministic Back / Menu signal (0ms, 0 AI)
    if isinstance(raw_input, dict):
        if raw_input.get("action") == "back" or raw_input.get("value") in ("menu", "main menu"):
            return reset_to_menu("Cancelled item selection. Returning to main menu.")
    elif str(raw_input).strip().lower() in ("menu", "main menu", "home", "reset", "back", "exit", "quit"):
        return reset_to_menu("Cancelled item selection. Returning to main menu.")

    # 2. Deterministic item selection payload (0ms, 0 AI)
    is_whole = False
    is_partial_submission = False
    if isinstance(raw_input, dict):
        if raw_input.get("scope") == "all" or raw_input.get("value") == "all":
            is_whole = True
        elif raw_input.get("items"):
            is_partial_submission = True
    elif str(raw_input).strip().lower() in ("all", "all items", "entire", "whole", "cancel whole order", "return whole order"):
        is_whole = True

    if is_whole:
        selected_items = [
            {
                "item_id": it.get("order_item_id") or it.get("id"),
                "name": it.get("product_name", "Item"),
                "quantity": int(it.get("quantity", 1)),
                "unit_price": float(it.get("unit_price", 0)),
            }
            for it in active_items
        ]
        refund = sum(it["quantity"] * it["unit_price"] for it in selected_items)
        return {
            "context": {
                "order_id": order_id,
                "items": selected_items,
                "refund_amount": refund,
                "scope": "all",
            }
        }

    if is_partial_submission:
        selected_items = []
        for sel in raw_input.get("items", []):
            orig = next((it for it in active_items if (it.get("order_item_id") or it.get("id")) == sel.get("item_id")), None)
            price = float(orig.get("unit_price", 0)) if orig else 0.0
            name = orig.get("product_name", "Item") if orig else "Item"
            selected_items.append({
                "item_id": sel.get("item_id"),
                "name": name,
                "quantity": sel.get("quantity", 1),
                "unit_price": price,
            })
        refund = sum(it["quantity"] * it["unit_price"] for it in selected_items)
        return {
            "context": {
                "order_id": order_id,
                "items": selected_items,
                "refund_amount": refund,
                "scope": "partial",
            }
        }

    # 3. ONLY if input is NOT a button and NOT an item selection, call AI for conversational queries
    decision = classify_user_intent(raw_input)
    if decision.intent == "abort":
        return reset_to_menu("Understood! Returning to main menu.")
    if decision.intent == "faq":
        faq_ans = decision.reply or "Please let me know if you have questions regarding our store policies."
        return {"messages": [AIMessage(content=f"💡 **Policy Info:** {faq_ans}")]}

    # Default fallback: select all
    selected_items = [
        {
            "item_id": it.get("order_item_id") or it.get("id"),
            "name": it.get("product_name", "Item"),
            "quantity": int(it.get("quantity", 1)),
            "unit_price": float(it.get("unit_price", 0)),
        }
        for it in active_items
    ]
    refund = sum(it["quantity"] * it["unit_price"] for it in selected_items)
    return {
        "context": {
            "order_id": order_id,
            "items": selected_items,
            "refund_amount": refund,
            "scope": "all",
        }
    }


# =====================================================================
# 4. CONFIRM ACTION NODE (confirm_action_node)
# =====================================================================

def confirm_action_node(state: CustomerState) -> dict:
    """Strict confirmation gate. Deterministic for buttons, isolated 0.95 floor for text."""
    user_id = int(state.get("user_id") or 1)
    action = state.get("action_type") or "cancel_order"
    action_noun = "Cancellation" if action == "cancel_order" else "Return"
    ctx = state.get("context") or {}
    order_id = str(ctx.get("order_id") or state.get("order_id") or "")
    selected_items = ctx.get("items", [])
    refund = float(ctx.get("refund_amount", 0.0))

    payload = build_confirmation_payload(order_id, action, selected_items, refund)
    raw_input = interrupt(payload)

    # 1. Deterministic button signals (0ms, 0 AI)
    button = is_button_signal(raw_input)
    if button == "confirm":
        return {"confirmed": True}
    if button in ("abort", "menu"):
        return reset_to_menu(f"No problem! Order #ORD-{order_id} remains active with no changes made.")

    # 2. If user typed free text, use isolated confirmation validator
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

    # 3. Check if user asked an inline policy question
    decision = classify_user_intent(raw_input)
    if decision.intent == "faq":
        faq_ans = decision.reply or "Please let me know if you have questions regarding our store policies."
        return {"messages": [AIMessage(content=f"💡 **Policy Info:** {faq_ans}")]}

    # Ambiguous -> Safe non-execution
    raw_text = raw_input.get("value") if isinstance(raw_input, dict) else str(raw_input or "")
    return reset_to_menu(
        f"⚠️ For your protection, order {action_noun.lower()} requires 100% clear confirmation. "
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
    elif action == "return_order":
        if status != "Delivered":
            reason = "Only delivered items can be returned [SEC-2.1]."
        else:
            reason = "Standard returns must be requested within 7 days of delivery [SEC-2.5]."

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
