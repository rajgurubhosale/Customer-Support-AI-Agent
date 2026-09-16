import re
from typing import Any, Optional
from langchain_core.messages import AIMessage
from langgraph.types import interrupt
from pydantic import ValidationError

from customer_support_ai_agent.state import CustomerState
from customer_support_ai_agent.schemas import (
    normalize_user_input,
    PartialItemSelection,
    UserInput,
    UserIntent,
)
from customer_support_ai_agent.db_functions import get_order_with_items, get_order_history
from customer_support_ai_agent.intent_router import classify_user_intent
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
from customer_support_ai_agent.routes import (
    active_items_for,
    get_ineligibility_reason,
    order_is_eligible,
)

# =====================================================================
# HELPER FUNCTIONS
# =====================================================================

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
        item_lines.append(f"  • {name} — Qty: {quantity} (₹{price:.2f})")
    items_summary = "\n".join(item_lines) or "  • No item details found"


    return (
        f"📦 **Order Details: #ORD-{order_id}**\n"
        f"• **Status:** **{status}**\n"
        f"• **Order Date:** {order_date}\n"
        f"• **Total Amount:** ₹{total_amount:.2f}\n\n"
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


def _handle_tracking_response(order_id: Optional[str], user_id: int) -> dict:
    """Single authoritative resolver for order tracking queries."""
    found = _validate_and_fetch_order(order_id, user_id)

    if found:
        msg = _format_order_card(found["customer_details"])

    elif order_id:
        msg = f"⚠️ I couldn't find order #{order_id} under your account."

    else:
        msg = _format_recent_orders(get_order_history(user_id) or [])

    return reset_to_menu(msg)


def _handle_midflow_redirect(
    decision: UserIntent,
    user_id: int,
    current_action: Optional[str] = None,
    abort_msg: Optional[str] = None,
) -> Optional[dict]:
    """Redirects the user if they change their intent mid-workflow with dual-intent reply support."""
    if decision.intent == "abort":
        return reset_to_menu(abort_msg)

    if decision.intent == "human_support":
        return {"action_type": "human_support", "confirmed": None}

    if decision.intent == "track_order":
        return _handle_tracking_response(decision.order_id, user_id)

    # Action switch or start: preserves any policy answer attached to the request
    if decision.intent in ("cancel_order", "return_order") and decision.intent != current_action:
        messages = [AIMessage(content=decision.reply)] if decision.reply else []
        return {
            "action_type": decision.intent,
            "order_id": decision.order_id,
            "confirmed": None,
            "messages": messages,
        }

    return None


def _normalize_order_item (db_item: dict, qty: Optional[int] = None) -> dict:
    """
    
    Normalizes a database order item row into a standard schema 
    (item_id, name, quantity, unit_price), 

    """
    return {
        "item_id": db_item.get("order_item_id"),
        "name": db_item.get("product_name", "Item"),
        "quantity": int(qty or db_item.get("quantity", 1)),
        "unit_price": float(db_item.get("unit_price", 0)),
    }


def _validate_item_selection(
    payload: Any,
    items_by_id: dict[str, dict],
) -> tuple[list[dict], Optional[str]]:
    """Validate a partial selection against the current order."""

    try:
        selection_payload = PartialItemSelection.model_validate(payload)
    except ValidationError:
        return [], "Please select at least one item using whole-number quantities."

    selected_items = []
    seen_ids = set()
    for selection in selection_payload.items:
        item_id = str(selection.item_id)
        item = items_by_id.get(item_id)
        if not item or item_id in seen_ids:
            return [], "One of the selected items is invalid. Please try again."

        maximum = int(item.get("quantity", 1))
        if selection.quantity > maximum:
            return [], f"Quantity for item #{item_id} must be between 1 and {maximum}."

        seen_ids.add(item_id)
        selected_items.append(_normalize_order_item(item, selection.quantity))

    return selected_items, None


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
    
    
    # freeze and get the user response.
    user_input, cmd = interrupt_and_get_user_response(payload)
    
    # check if user wants to exit or menu or talk to human
    if cmd:
        return cmd

    # Routes customer to cancel, return, tracking, human support, or abort
    decision = classify_user_intent(user_input.text)

    redirect = _handle_midflow_redirect(
        decision,
        user_id,
        abort_msg="No problem! Have a wonderful day! 👋",
    )
    if redirect is not None:
        return redirect

    # Policy FAQs & Conversational chat (AI generated reply)
    answer = decision.reply or "How can I help you with your order today?"

    return {"messages": [AIMessage(content=answer)], "confirmed": None, "action_type": None}



def order_lookup_node(state: CustomerState) -> dict:
    """
    Finds customer order. Fully deterministic for button clicks and order IDs.
    """
    user_id = int(state.get("user_id"))
    action = state.get("action_type") or "cancel_order"

    # If order_id was already extracted in previous step
    found_order = _validate_and_fetch_order(state.get("order_id"), user_id)
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
    user_input, cmd = interrupt_and_get_user_response(payload)


    if user_input.action == "track_order":
        return _handle_tracking_response(None, user_id)


    if cmd:
        return cmd

    # Fast order ID check by button click
    found_order = _validate_and_fetch_order(user_input.text, user_id)
    if found_order:
        return found_order

    # for conversational queries handled by AI
    decision = classify_user_intent(user_input.text)
    redirect = _handle_midflow_redirect(decision, user_id, current_action=action)
    if redirect is not None:
        return redirect

    found_order = _validate_and_fetch_order(decision.order_id, user_id)
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

def select_items_node(state: CustomerState) -> dict:
    """
    Presents item selection form.
    100% deterministic for button clicks and checkboxes

    """
    user_id = int(state.get("user_id"))
    action = state.get("action_type")
    order = state.get("customer_details") or {}
    
    order_id = str(order.get("order_id") or state.get("order_id") or "")
    
    if not order or not order.get("items"):
        order = get_order_with_items(int(order_id), customer_id=user_id) or {}

    items = order.get("items", [])
    active_items = active_items_for(action, items)
    items_map = {str(it.get("order_item_id") or it.get("id")): it for it in active_items}

    payload = build_item_selection_payload(order_id, action, active_items)
    user_input, cmd = interrupt_and_get_user_response(
        payload,
        cancel_message="Cancelled item selection. Returning to main menu.",
    )
    if cmd:
        return cmd

    #  Deterministic partial item selection payload (from UI steppers/checkboxes)
    is_partial_submission = user_input.data.get("scope") == "partial" or "items" in user_input.data
    if is_partial_submission:
        scope = "partial"
        selected_items, error = _validate_item_selection(
            user_input.data,
            items_map,
        )
        if error:
            return {
                "context": None,
                "messages": [AIMessage(content=f"⚠️ {error} No changes were made.")],
            }
    else:
        # Conversational queries / FAQs (only when not explicitly selecting all)
        is_explicit_all = (
            user_input.data.get("scope") == "all"
            or user_input.action == "all"
            or user_input.lower_text in ("all", "all items", "entire", "whole", "cancel whole order", "return whole order")
        )
        if not is_explicit_all:
            decision = classify_user_intent(user_input.text)
            redirect = _handle_midflow_redirect(
                decision,
                user_id,
                current_action=action,
                abort_msg="Understood! Returning to main menu.",
            )
            if redirect is not None:
                return redirect

            if decision.intent == "faq":
                faq_ans = decision.reply or "Please let me know if you have questions regarding our store policies."
                return {"messages": [AIMessage(content=f"💡 **Policy Info:** {faq_ans}")]}
            return {
                "context": None,
                "messages": [AIMessage(
                    content="⚠️ Please use the quantity selectors or choose the whole-order option. No changes were made."
                )],
            }

        # Default / Whole Order: select all active items
        scope = "all"
        selected_items = [_normalize_order_item (it) for it in active_items]

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


def confirm_action_node(state: CustomerState) -> dict:
    """Deterministic confirmation gate with intent handling for questions and escalation."""
    action = state.get("action_type")
    ctx = state.get("context") or {}
    order_id = str(ctx.get("order_id") or "")
    selected_items = ctx.get("items", [])
    refund = float(ctx.get("refund_amount", 0.0))

    # Pre-validation: require valid action, context, order_id, and non-empty items
    if action not in ("cancel_order", "return_order") or not ctx or not order_id or not selected_items:
        return reset_to_menu("⚠️ Transaction session expired or invalid. Please select an option from the menu.")

    noun = "cancellation" if action == "cancel_order" else "return"

    payload = build_confirmation_payload(order_id, action, selected_items, refund)
    abort_msg = f"No problem! Order #ORD-{order_id} remains active with no changes made."
    user_input, cmd = interrupt_and_get_user_response(payload, cancel_message=abort_msg)

    # Explicit UI action or exact typed command.
    if user_input.action == "confirm":
        return {"confirmed": True}

    if user_input.action == "keep":
        return reset_to_menu(abort_msg)

    if cmd:
        return cmd

    # Interpret every other free-text response without authorizing the action.
    decision = classify_user_intent(user_input.text)

    if decision.intent == "abort":
        return reset_to_menu(abort_msg)

    if decision.intent == "human_support":
        return {"action_type": "human_support"}

    opposite_action = "return_order" if action == "cancel_order" else "cancel_order"
    opposite_verb = "return" if action == "cancel_order" else "cancel"
    if decision.intent == opposite_action:
        return reset_to_menu(
            f"I have stopped the {noun}. To {opposite_verb} an order, please select '{opposite_verb.title()} Order' from the menu."
        )

    if decision.intent == "faq" or decision.reply:
        reply_content = decision.reply or "Please let me know if you have questions regarding our store policies."
        return {
            "messages": [
                AIMessage(
                    content=f"💡 {reply_content}\n\n"
                            f"To proceed, please click **Confirm {noun.title()}** or type **“confirm”**."
                )
            ]
        }

    return {
        "messages": [
            AIMessage(
                content=f"I didn't quite catch that. Please click **Confirm {noun.title()}** or type **“confirm”** to proceed, "
                        f"or click **Keep Order** to return to the main menu."
            )
        ]
    }



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


def policy_blocked_node(state: CustomerState) -> dict:
    """Informs user when an order is ineligible under store policy."""
    action = state.get("action_type") or "cancel_order"
    order = state.get("customer_details") or {}
    order_id = str(order.get("order_id") or state.get("order_id") or "")
    reason = get_ineligibility_reason(order, action) or "This order is not eligible for this action."
    payload = build_blocked_payload(action, order_id, reason)
    user_input, cmd = interrupt_and_get_user_response(payload, cancel_message="Returned to main menu.")
    if cmd:
        return cmd
    return reset_to_menu("Returned to main menu.")


def human_escalate_node(state: CustomerState) -> dict:
    """Creates a support ticket and returns confirmation."""
    user_id = int(state.get("user_id") or 1)
    return reset_to_menu(build_escalation_message(user_id))
