import re
from typing import Any, Optional
from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from customer_support_ai_agent.state import CustomerState
from customer_support_ai_agent.schemas import normalize_user_input
from customer_support_ai_agent.db_functions import get_order_with_items, get_order_history
from customer_support_ai_agent.intent_router import (
    classify_user_intent,
    classify_confirmation,
)
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
from customer_support_ai_agent.routes import active_items_for, order_statuses_for
from customer_support_ai_agent.routes import (
    active_items_for,
    order_is_eligible,
)

# =====================================================================
# HELPER FUNCTIONS
# =====================================================================

def _resolve_order(val: Any, user_id: int) -> Optional[dict]:
    """Extracts order digits and verifies against DB. Returns state update if found."""
    match = re.match(r"^(?:ord-?|#|order\s*)?(\d+)$", str(val or "").strip(), re.IGNORECASE)
    if match:
        order_id = match.group(1)
        order = get_order_with_items(int(order_id), customer_id=user_id)
        if order:
            return {"customer_details": order, "order_id": order_id}
    return None


def reset_to_menu(message: Optional[str] = None) -> dict:
    """Centralized state wipe when customer aborts or returns to the main menu."""
    out = {
        "action_type": None,
        "order_id": None,
        "customer_details": None,
        "confirmed": None,
        "context": None,
    }
    if message:
        out["messages"] = [AIMessage(content=message)]
    return out


def _check_global_commands(user_text: str, message: Optional[str] = None) -> Optional[dict]:
    """Universal navigation interceptor for menu and human support."""
    text = user_text.lower().strip()
    if text in ("menu", "main menu", "back", "abort"):
        return reset_to_menu(message)
    if text in ("ticket", "human", "specialist", "agent"):
        return {"action_type": "human_support", "confirmed": None}
    return None


def _get_order_details_message(order_id: int, user_id: int) -> str:
    """Fetch order with items and return a clean markdown card or not-found notice."""
    order = get_order_with_items(order_id, customer_id=user_id)
    if not order:
        return f"⚠️ I couldn't find order #ORD-{order_id} under your account."

    items = order.get("items", [])
    items_summary = "\n".join([
        f"  • {it.get('product_name', 'Item')} — Qty: {it.get('quantity', 1)} (₹{float(it.get('unit_price', 0)):.2f})"
        for it in items
    ]) or "  • (No item details found)"

    return (
        f"📦 **Order Details: #ORD-{order['order_id']}**\n"
        f"• **Status:** **{order.get('status')}**\n"
        f"• **Order Date:** {str(order.get('order_date'))[:10]}\n"
        f"• **Total Amount:** ₹{float(order.get('total_amount', 0)):.2f}\n\n"
        f"🛒 **Items in this order:**\n{items_summary}"
    )


def _to_item_dict(it: dict, qty: Optional[int] = None) -> dict:
    """Standardize an active order item into a clean dictionary."""
    return {
        "item_id": it.get("order_item_id") or it.get("id"),
        "name": it.get("product_name", "Item"),
        "quantity": int(qty if qty is not None else it.get("quantity", 1)),
        "unit_price": float(it.get("unit_price", 0)),
    }


def _validate_item_selection(
    selections: Any,
    items_by_id: dict[str, dict],
) -> tuple[list[dict], Optional[str]]:
    """Validate a partial selection against the current order."""
    if not isinstance(selections, list) or not selections:
        return [], "Please select at least one item and quantity."

    selected_items = []
    seen_ids = set()
    for selection in selections:
        if not isinstance(selection, dict):
            return [], "One of the selected items is invalid. Please try again."

        item_id = str(selection.get("item_id") or "")
        item = items_by_id.get(item_id)
        if not item or item_id in seen_ids:
            return [], "One of the selected items is invalid. Please try again."

        raw_quantity = selection.get("quantity")
        if isinstance(raw_quantity, bool):
            return [], "Every selected quantity must be a whole number."
        try:
            quantity = int(raw_quantity)
        except (TypeError, ValueError):
            return [], "Every selected quantity must be a whole number."

        if isinstance(raw_quantity, float) and not raw_quantity.is_integer():
            return [], "Every selected quantity must be a whole number."

        maximum = int(item.get("quantity", 1))
        if quantity < 1 or quantity > maximum:
            return [], f"Quantity for item #{item_id} must be between 1 and {maximum}."

        seen_ids.add(item_id)
        selected_items.append(_to_item_dict(item, quantity))

    return selected_items, None


# =====================================================================
# 1. CONVERSATIONAL FRONT DOOR (start_node)
# =====================================================================

def start_node(state: CustomerState) -> dict:
    """Conversational front door for inquiries, FAQs, and intent routing."""
    
    user_id = int(state.get("user_id") or 1)

    # its for starting the welcome or if the action is confirmed like return or cancel
    # then show the exit nothing else

    is_post_action = bool(state.get("confirmed"))

    if is_post_action:
        payload = build_post_action_payload()
    else:
        payload = build_welcome_payload()
    
    
    user_input = normalize_user_input(interrupt(payload))

    lower_text = user_input.text.lower()

    cmd = _check_global_commands(user_input.action or lower_text)
    if cmd:
        return cmd

    # Unified AI Call (Classifies intent AND answers FAQs in 1 shot)
    decision = classify_user_intent(user_input.text)

    if decision.intent == "abort":
        return reset_to_menu("No problem! Have a wonderful day! 👋")

    if decision.intent in ("cancel_order", "return_order"):
        verb = "cancel" if decision.intent == "cancel_order" else "return"

        messages = []

        # Keep the policy answer when the message contains both
        # a question and an action request.
        if decision.reply:
            messages.append(AIMessage(content=decision.reply))

        messages.append(
            AIMessage(content=f"ℹ️ Sure, I can help you {verb} your order.")
        )

        return {
            "action_type": decision.intent,
            "order_id": decision.order_id,
            "confirmed": None,
            "messages": messages,
        }

    if decision.intent == "track_order":
        # 1. Specific order inquiry (e.g. "details of ORD-74")
        if decision.order_id:
            msg = _get_order_details_message(int(decision.order_id), user_id)
            return {"messages": [AIMessage(content=msg)], "confirmed": None, "action_type": None}

        # 2. General tracking inquiry (show recent orders list)
        orders = get_order_history(user_id) or []
        if orders:
            cards = "\n\n".join([
                f"• **Order #ORD-{o.get('order_id')}** — Status: **{o.get('status')}**\n"
                f"  💰 Total: ₹{float(o.get('total_amount', 0)):.2f} | 📅 Ordered: {str(o.get('order_date'))[:10]}"
                for o in orders[:4]
            ])
            msg = f"📦 **Here are your recent orders:**\n\n{cards}"
        else:
            msg = "📦 You don't have any past orders on record."
        return {"messages": [AIMessage(content=msg)], "confirmed": None, "action_type": None}

    if decision.intent == "human_support":
        return {"action_type": "human_support", "confirmed": None}

    # Policy FAQs & Conversational chat (AI generated reply)
    answer = decision.reply or "How can I help you with your order today?"
    return {"messages": [AIMessage(content=answer)], "confirmed": None, "action_type": None}


# =====================================================================
# 2. ORDER LOOKUP NODE (order_lookup_node)
# =====================================================================

def order_lookup_node(state: CustomerState) -> dict:
    """Finds customer order. Fully deterministic for button clicks and order IDs."""
    user_id = int(state.get("user_id") or 1)
    action = state.get("action_type") or "cancel_order"

    # If order_id was already extracted in previous step
    found_order = _resolve_order(state.get("order_id"), user_id)
    if found_order:
        return found_order

    # Fetch orders for this customer
    all_orders = get_order_history(user_id, limit=None) or []
    eligible = [
        order
        for order in all_orders
        if order_is_eligible(order, action)
    ][:5]
    
    payload = build_order_list_payload(action, eligible)
    user_input = normalize_user_input(interrupt(payload))
    lower_text = user_input.text.lower()

    # 1. Direct button signals / global commands
    cmd = _check_global_commands(user_input.action or lower_text)
    if cmd:
        return cmd

    # 2. Fast order ID check (Button click or clean ID, with single-order shortcut)
    candidate = eligible[0]["order_id"] if (len(eligible) == 1 and lower_text in ("yes", "y", "sure", "ok", "proceed", "1")) else user_input.text
    found_order = _resolve_order(candidate, user_id)
    if found_order:
        return found_order

    # 3. Conversational queries handled by AI
    decision = classify_user_intent(user_input.text)
    if decision.intent == "abort":
        return reset_to_menu()
        
    if decision.intent == "human_support":
        return {"action_type": "human_support"}
    if decision.intent in ("cancel_order", "return_order") and decision.intent != action:
        return {"action_type": decision.intent, "order_id": decision.order_id}
    found_order = _resolve_order(decision.order_id, user_id)
    if found_order:
        return found_order

    # If user asked an FAQ or policy question, show the AI answer
    if decision.reply:
        return {"messages": [AIMessage(content=f"ℹ️ {decision.reply}")]}

    # If no eligible orders, prevent false "order not found" error
    if not eligible:
        return {"messages": [AIMessage(content="ℹ️ You don't have any orders eligible for this action.")]}

    # Order ID not recognized from eligible list
    return {
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
    active_items = active_items_for(action, items)
    items_map = {str(it.get("order_item_id") or it.get("id")): it for it in active_items}

    payload = build_item_selection_payload(order_id, action, active_items)
    user_input = normalize_user_input(interrupt(payload))
    lower_text = user_input.text.lower()

    # 1. Deterministic Back / Menu signal
    cmd = _check_global_commands(user_input.action or lower_text, message="Cancelled item selection. Returning to main menu.")
    if cmd:
        return cmd

    # 2. Deterministic partial item selection payload (from UI steppers/checkboxes)
    is_partial_submission = user_input.data.get("scope") == "partial" or "items" in user_input.data
    if is_partial_submission:
        scope = "partial"
        selected_items, error = _validate_item_selection(
            user_input.data.get("items"),
            items_map,
        )
        if error:
            return {
                "context": None,
                "messages": [AIMessage(content=f"⚠️ {error} No changes were made.")],
            }
    else:
        # 3. Conversational queries / FAQs (only when not explicitly selecting all)
        is_explicit_all = (
            user_input.data.get("scope") == "all"
            or user_input.action == "all"
            or lower_text in ("all", "all items", "entire", "whole", "cancel whole order", "return whole order")
        )
        if not is_explicit_all:
            decision = classify_user_intent(user_input.text)
            if decision.intent == "abort":
                return reset_to_menu("Understood! Returning to main menu.")
            if decision.intent == "human_support":
                return {"action_type": "human_support", "context": None}
            if decision.intent == "faq":
                faq_ans = decision.reply or "Please let me know if you have questions regarding our store policies."
                return {"messages": [AIMessage(content=f"💡 **Policy Info:** {faq_ans}")]}
            return {
                "context": None,
                "messages": [AIMessage(
                    content="⚠️ Please use the quantity selectors or choose the whole-order option. No changes were made."
                )],
            }

        # 4. Default / Whole Order: select all active items
        scope = "all"
        selected_items = [_to_item_dict(it) for it in active_items]

    if not selected_items:
        return {
            "context": None,
            "messages": [AIMessage(content="⚠️ No eligible items were selected. No changes were made.")],
        }

    # Single exit point for refund calculation and context packaging
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

def confirm_action_node(state: CustomerState) -> dict:
    """Strict confirmation gate. Deterministic for buttons, isolated 0.95 floor for text."""
    action = state.get("action_type") or "cancel_order"
    action_noun = "Cancellation" if action == "cancel_order" else "Return"
    ctx = state.get("context") or {}
    order_id = str(ctx.get("order_id") or state.get("order_id") or "")
    selected_items = ctx.get("items", [])
    refund = float(ctx.get("refund_amount", 0.0))

    payload = build_confirmation_payload(order_id, action, selected_items, refund)
    user_input = normalize_user_input(interrupt(payload))
    lower_text = user_input.text.lower()

    # 1. Simple button signals or affirmative text
    if user_input.action == "confirm" or lower_text in ("confirm", "yes", "proceed"):
        return {"confirmed": True}

    cmd = _check_global_commands(user_input.action or lower_text, message=f"No problem! Order #ORD-{order_id} remains active with no changes made.")
    if cmd:
        return cmd

    if user_input.action in ("keep", "abort") or lower_text in ("keep", "no"):
        return reset_to_menu(f"No problem! Order #ORD-{order_id} remains active with no changes made.")

    # 2. If user typed free text, use isolated confirmation validator
    is_confirmed = classify_confirmation(
        reply=user_input.text,
        action_noun=action_noun,
        order_id=order_id,
        refund_amount=refund,
    )

    if is_confirmed is True:
        return {"confirmed": True}

    if is_confirmed is False:
        return reset_to_menu(f"No problem! Order #ORD-{order_id} remains active with no changes made.")

    # 3. Check if user asked an inline policy question
    decision = classify_user_intent(user_input.text)
    if decision.intent == "faq":
        faq_ans = decision.reply or "Please let me know if you have questions regarding our store policies."
        return {"messages": [AIMessage(content=f"💡 **Policy Info:** {faq_ans}")]}

    # Ambiguous -> Safe non-execution
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
    user_input = normalize_user_input(interrupt(payload))

    btn_text = user_input.action or user_input.text.lower()
    cmd = _check_global_commands(btn_text, message="Returned to main menu.")
    if cmd:
        return cmd
    return reset_to_menu("Returned to main menu.")


# =====================================================================
# 7. HUMAN ESCALATION NODE (human_escalate_node)
# =====================================================================

def human_escalate_node(state: CustomerState) -> dict:
    """Creates a support ticket and returns confirmation."""
    user_id = int(state.get("user_id") or 1)
    return reset_to_menu(build_escalation_message(user_id))
