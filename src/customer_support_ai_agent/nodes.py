from functools import lru_cache
from pathlib import Path
from datetime import datetime, date
import re
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

from customer_support_ai_agent.state import CustomerState
from customer_support_ai_agent.db_functions import get_order_with_items, get_order_history
from customer_support_ai_agent.prompts import FAQ_SYSTEM_PROMPT
from customer_support_ai_agent.model import model
from customer_support_ai_agent.intent_router import (
    validate_expected_input,
    detect_intent_switch,
    clear_flow_state,
    classify_confirmation_intent,
    is_abort_intent,
)
from customer_support_ai_agent.schemas import (
    ActionSelectionPayload,
    OrderMutationContext,
)

def reset_to_menu(message: str = "Returned to main menu.") -> dict:
    """Centralized state wipe when customer aborts or returns to the main menu."""
    return {
        "action_type": None,
        "order_id": None,
        "customer_details": None,
        "retry_count": 0,
        "confirmed": None,
        "resume_node": None,
        "context": None,
        "faq_prompt": None,
        "options": [],
        "messages": [AIMessage(content=message)],
    }

RETURN_WINDOW_DAYS = 7

MAIN_MENU_OPTIONS = [
    {"label": "📦 View / Track Orders", "value": "What are my recent orders?"},
    {"label": "❌ Cancel an Order", "value": "I want to cancel an order"},
    {"label": "🔄 Return an Order", "value": "I want to return an order"},
    {"label": "📖 Store Policies", "value": "What is your return and cancellation policy?"},
]

@lru_cache(maxsize=1)
def load_policy_files() -> str:
    policy_path = Path(__file__).resolve().parents[2] / "docs" / "cancellation_and_return_policy.md"
    return policy_path.read_text(encoding="utf-8")


# =====================================================================
# 1. CONVERSATIONAL FRONT DOOR (start_node / open_router_node)
# =====================================================================

def open_router_node(state: CustomerState) -> dict:
    """Unified conversational front door for general inquiries, store policy FAQs, and intent handoffs."""

    user_id = int(state.get("user_id") or 1)
    resume_target = state.get("resume_node")

    # Mid-workflow read-only FAQ interruption vs new question
    if resume_target and state.get("faq_prompt"):
        user_msg = state.get("faq_prompt")
    else:
        has_faq = bool(state.get("faq_prompt"))
        is_post_action = bool(state.get("confirmed"))

        if is_post_action:
            prompt = (
                "**Is there anything else I can help you with today?**\n\n"
                "*(You can view your updated orders, check refund timelines, or return to the main menu)*"
            )
            opts = [
                {"label": "📦 View Remaining Orders", "value": "What are my remaining orders?"},
                {"label": "📖 Refund Policy Info", "value": "When will I receive my refund?"},
                {"label": "🏠 Main Menu", "value": "menu"},
            ]
        elif has_faq:
            prompt = state.get("faq_prompt")
            opts = [
                {"label": "🏠 Main Menu", "value": "menu"},
            ]
        else:
            prompt = (
                "**Hi! How can I help you today?**\n\n*(You can ask about our store policies, track your orders, or request a return/cancellation)*"
            )
            opts = []

        raw_input = interrupt({"prompt": prompt, "options": opts})
        user_msg = str(raw_input or "").strip()

    # Fast Exit Check
    if user_msg.lower() in ("exit", "quit", "bye", "done", "close"):
        return reset_to_menu()

    # Conversational Return to Main Menu
    if is_abort_intent(user_msg) or user_msg.lower() in ("menu", "main menu", "home", "reset", "start over"):
        return reset_to_menu("Understood! Returning to the main menu.")

    # Direct Escalation
    if user_msg.lower() in ("ticket", "human", "agent", "escalate", "support"):
        return {
            "action_type": "human_support",
            "faq_prompt": None,
            "resume_node": None,
            "customer_details": None,
            "order_id": None,
            "retry_count": 0,
            "confirmed": None,
        }

    user_lower = user_msg.lower()

    # Fast Remaining Orders & Order History check (0ms, directly from DB)
    if any(p in user_lower for p in ("remaining order", "remaining orders", "view remaining", "my orders", "check order", "order status", "track order")):
        recent_orders = get_order_history(user_id) or []
        if "remaining" in user_lower:
            active_orders = [o for o in recent_orders if o.get("status") not in ("Cancelled", "Returned")]
            if active_orders:
                orders_list = "\n\n".join([
                    f"• **Order #ORD-{o.get('order_id')}** — Status: **{o.get('status')}**\n"
                    f"  💰 Total: ₹{float(o.get('total_amount', 0)):.2f} | 📅 Ordered: {str(o.get('order_date'))[:10]} | 🚚 Est. Delivery: {str(o.get('delivery_date'))[:10] if o.get('delivery_date') else 'Pending'}"
                    for o in active_orders
                ])
                answer = f"📦 **Here are your remaining active orders:**\n\n{orders_list}\n\nLet me know if you need anything else!"
            else:
                answer = "📦 **You have no remaining active orders.** All previous orders have been completed or cancelled."
        else:
            if recent_orders:
                orders_list = "\n\n".join([
                    f"• **Order #ORD-{o.get('order_id')}** — Status: **{o.get('status')}**\n"
                    f"  💰 Total: ₹{float(o.get('total_amount', 0)):.2f} | 📅 Ordered: {str(o.get('order_date'))[:10]} | 🚚 Est. Delivery: {str(o.get('delivery_date'))[:10] if o.get('delivery_date') else 'Pending'}"
                    for o in recent_orders[:4]
                ])
                answer = f"📦 **Here are your recent orders:**\n\n{orders_list}\n\nLet me know if you need help with cancellations, returns, or tracking!"
            else:
                answer = "📦 You don't have any past orders on record."

        return {
            "action_type": "faq",
            "faq_prompt": answer,
            "resume_node": None,
            "confirmed": None,
        }

    # Fast-path Intent Detection (Direct Commands & Keywords)
    switch = detect_intent_switch(user_msg, current_flow="open")
    if switch and switch["type"] == "workflow_switch":
        return {
            "action_type": switch["action_type"],
            "order_id": switch.get("order_id"),
            "faq_prompt": None,
            "resume_node": None,
            "customer_details": None,
            "retry_count": 0,
            "confirmed": None,
            "messages": [AIMessage(content=switch["transition_message"])],
        }

    # Fetch recent orders to provide prompt context directly without tool round-trips
    recent_orders = get_order_history(user_id) or []
    orders_summary = "\n".join([
        f"- ORD-{o.get('order_id')}: {o.get('status')} | Total: ₹{float(o.get('total_amount', 0)):.2f} | Ordered: {str(o.get('order_date'))[:10]} | Est. Delivery: {str(o.get('delivery_date'))[:10] if o.get('delivery_date') else 'Pending'}"
        for o in recent_orders[:4]
    ]) or "No recent orders found."

    system_prompt = FAQ_SYSTEM_PROMPT.format(
        store_policies=load_policy_files(),
        customer_orders=orders_summary,
    )
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_msg)]

    try:
        answer = model.invoke(messages).content
    except Exception as e:
        print(f"Open Router LLM error: {e}")
        answer = "I can help with store policies, orders, cancellations, and returns. Could you rephrase your query?"

    # Smart Resume: return to interrupted node
    if resume_target:
        return {
            "resume_node": resume_target,
            "faq_prompt": None,
            "confirmed": None,
            "messages": [AIMessage(content=answer)],
        }

    return {"action_type": "faq", "faq_prompt": answer, "resume_node": None, "confirmed": None}


start_node = open_router_node


# =====================================================================
# 2. ORDER LOOKUP NODE (order_lookup_node)
# =====================================================================

def order_lookup_node(state: CustomerState) -> dict:
    """Fetches order. If missing, prompts user with eligible orders. Loops via router if not found."""
    user_id = state["user_id"]
    retries = state.get("retry_count", 0)
    order_id = state.get("order_id")
    action = state.get("action_type", "cancel_order")
    action_verb = "cancel" if action == "cancel_order" else "return"

    if not order_id:
        all_recent = get_order_history(user_id) or []
        if action == "cancel_order":
            eligible = [o for o in all_recent if o.get("status") in ("Placed", "Processing", "Partially_Cancelled")]
        else:
            eligible = [
                o for o in all_recent
                if o.get("status") in ("Delivered", "Partially_Returned")
                and (date.today() - (o["delivery_date"].date() if isinstance(o.get("delivery_date"), datetime) else o.get("delivery_date", date.today()))).days <= RETURN_WINDOW_DAYS
            ]

        displayed = eligible[:4]
        options = [
            {"label": f"📦 ORD-{o['order_id']} — ₹{float(o.get('total_amount', 0)):.2f} — {o.get('status')}", "value": str(o['order_id'])}
            for o in displayed
        ]

        # Prepend FAQ notice if returning from mid-workflow FAQ
        faq_notice = ""
        messages = state.get("messages") or []
        if messages and isinstance(messages[-1], AIMessage) and state.get("resume_node"):
            faq_notice = f"💡 **Policy Info:** {messages[-1].content}\n\n---\n\n"

        if retries >= 3:
            prompt = f"{faq_notice}⚠️ **We couldn't locate that order after {retries} attempts.**\n\nWould you like to connect with a support specialist or return to the main menu?"
            options = [
                {"label": "🎫 Talk to Support Agent", "value": "ticket"},
                {"label": "🏠 Return to Main Menu", "value": "menu"},
            ]
        elif retries >= 1:
            if displayed:
                prompt = f"{faq_notice}⚠️ I couldn't find an order matching that ID in your account.\n\nPlease select one of your eligible orders below, or re-enter your **Order ID** (e.g., `ORD-15`):"
            else:
                prompt = f"{faq_notice}⚠️ I couldn't find an order matching that ID in your account.\n\nPlease double-check your **Order ID** (e.g., `ORD-XX`) or return to the main menu:"
            options = options + [
                {"label": "🔙 Back to Main Menu", "value": "menu"},
                {"label": "🎫 Talk to Support", "value": "ticket"},
            ]
        else:
            if len(displayed) == 1:
                single_o = displayed[0]
                action_name = "cancellation" if action == "cancel_order" else "return"
                prompt = (
                    f"{faq_notice}📦 You have 1 order eligible for {action_name}:\n"
                    f"**ORD-{single_o['order_id']}** ({single_o.get('status', '')}, ₹{float(single_o.get('total_amount', 0)):.2f})\n\n"
                    f"Would you like to {action_verb} items from this order?"
                )
                options = [
                    {"label": f"✅ Yes, {action_verb.title()} ORD-{single_o['order_id']}", "value": str(single_o['order_id'])},
                    {"label": "🔙 Back to Main Menu", "value": "menu"},
                ]
            elif displayed:
                prompt = f"{faq_notice}📦 **Select an order to {action_verb}:**"
                options = options + [{"label": "🔙 Back to Main Menu", "value": "menu"}]
            elif not all_recent:
                prompt = f"{faq_notice}ℹ️ You don't have any past orders on record. If you have an **Order ID** (e.g., `ORD-XX`), enter it below, or return to the main menu:"
                options = [{"label": "🔙 Back to Main Menu", "value": "menu"}]
            else:
                prompt = f"{faq_notice}Please enter your **Order ID** in format `ORD-XX` to {action_verb}:"
                options = [{"label": "🔙 Back to Main Menu", "value": "menu"}]

        raw_input = interrupt({
            "type": "order_selection",
            "prompt": prompt,
            "orders": [{"order_id": str(o["order_id"]), "status": o.get("status", ""), "total": float(o.get("total_amount", 0))} for o in displayed],
            "options": options,
        })

        # Extract selected value
        raw_val = raw_input.get("selected_order_id") or raw_input.get("order_id") or raw_input.get("value") if isinstance(raw_input, dict) else raw_input
        clean_val = str(raw_val or "").strip()
        clean_lower = clean_val.lower()

        if clean_lower in ("ticket", "human", "agent", "escalate", "support"):
            return {"action_type": "human_support", "retry_count": 0, "order_id": None, "customer_details": None}

        if is_abort_intent(clean_val):
            return {
                "action_type": None,
                "retry_count": 0,
                "order_id": None,
                "customer_details": None,
                "messages": [AIMessage(content="Understood! Returning to the main menu.")],
            }

        # Intent switch & FAQ check
        expected_tokens = {"menu", "main menu", "back", "exit", "no", "ticket", "1", "2", "3", "4", "yes", "y", "sure", "proceed", "ok", "__order_id__"}
        if not validate_expected_input(clean_lower, expected_tokens):
            switch = detect_intent_switch(clean_val, current_flow=action)
            if switch:
                if switch["type"] == "workflow_switch":
                    cleared = clear_flow_state(state, switch.get("order_id"))
                    return {**cleared, "action_type": switch["action_type"], "messages": [AIMessage(content=switch["transition_message"])]}
                elif switch["type"] == "faq_query":
                    return {"resume_node": "order_lookup_node", "faq_prompt": switch.get("question")}

        # Determine target order ID
        if len(displayed) == 1 and clean_lower in ("yes", "y", "sure", "proceed", "1", "ok"):
            order_id = str(displayed[0]["order_id"])
        elif clean_val.isdigit() and 1 <= int(clean_val) <= len(displayed):
            order_id = str(displayed[int(clean_val) - 1]["order_id"])
        else:
            match = re.search(r"(?:order|ord)?\s*[-#]?\s*(\d+)", clean_val, re.I)
            order_id = match.group(1) if match else (clean_val if clean_val.isdigit() else None)

    # Query PostgreSQL
    order_details = get_order_with_items(order_id, customer_id=user_id) if order_id else None
    if not order_details:
        return {"retry_count": retries + 1, "order_id": None, "customer_details": None}

    return {"retry_count": 0, "order_id": str(order_id), "customer_details": order_details}


# =====================================================================
# 3. HUMAN ESCALATION NODE (human_escalate_node)
# =====================================================================

def human_escalate_node(state: CustomerState) -> dict:
    """Displays human escalation & ticket confirmation."""
    interrupt({
        "prompt": "💬 **Human Support & Ticket Escalation**\n\nYour request has been routed to our customer care team. A ticket has been created and an agent will follow up shortly.\n\n*(Click below to return to the main menu)*",
        "options": [{"label": "🏠 Return to Main Menu", "value": "menu"}],
    })
    return {"action_type": "exit_to_menu", "messages": [AIMessage(content="Returned from Human Support.")]}


# =====================================================================
# 4. UNIFIED CONFIRMATION NODE (confirm_action_node)
# =====================================================================

def confirm_action_node(state: CustomerState) -> dict:
    """Unified confirmation node for both Cancel and Return.
    Takes item selections from UI / user, calculates authoritative refund, and emits context for DB mutation."""
    order = state.get("customer_details") or {}
    order_id = str(order.get("order_id") or state.get("order_id") or "")
    if (not order or not order.get("items")) and order_id:
        order = get_order_with_items(order_id, customer_id=state.get("user_id")) or {}

    all_items = order.get("items", [])
    action = state.get("action_type", "cancel_order")
    action_verb = "cancel" if action == "cancel_order" else "return"
    action_noun = "Cancellation" if action == "cancel_order" else "Return"
    action_done = "cancelled" if action == "cancel_order" else "returned"

    active_items = [it for it in all_items if it.get("item_status") not in ("Cancelled", "Returned")] or all_items
    items_data = [
        {"item_id": it.get("order_item_id") or it.get("id"), "name": it.get("product_name", "Item"), "quantity": int(it.get("quantity", 1)), "unit_price": float(it.get("unit_price", 0))}
        for it in active_items
    ]

    # Prepend FAQ answer notice if smart-resumed
    faq_notice = ""
    messages = state.get("messages") or []
    if messages and isinstance(messages[-1], AIMessage) and state.get("resume_node"):
        faq_notice = f"💡 **Policy Info:** {messages[-1].content}\n\n---\n\n"

    # Check if returning from a mid-confirmation FAQ inquiry where items were already selected
    if state.get("context") and state.get("context", {}).get("items") and state.get("resume_node"):
        selected_summary = state["context"]["items"]
        authoritative_refund = float(state["context"].get("refund_amount", 0.0))
        is_all = (state["context"].get("action_scope") == "all")
    else:
        # Interrupt with structured item selection
        selection_response = interrupt({
            "type": "item_quantity_selection",
            "title": f"Order #ORD-{order_id}",
            "order_id": order_id,
            "action": action,
            "action_verb": action_verb,
            "action_noun": action_noun,
            "status": order.get("status", ""),
            "order_date": str(order.get("order_date", ""))[:10] if order.get("order_date") else "",
            "order_total": float(order.get("total_amount", 0)),
            "items": items_data,
            "prompt": f"{faq_notice}Please select the items and quantities you wish to {action_verb} for **Order #ORD-{order_id}**:",
            "options": [
                {"label": f"❌ {action_verb.title()} Entire Order", "value": "all"},
                {"label": "🔙 Keep Order / Back", "value": "back"},
            ],
        })

        # Abort checks
        is_all = False
        chosen_items = []

        if isinstance(selection_response, dict):
            if selection_response.get("action") in ("back", "abort", "exit") or is_abort_intent(selection_response):
                return reset_to_menu(f"No problem! Order #ORD-{order_id} remains active with no changes made.")
            
            # Pydantic validation of UI input payload
            try:
                validated_payload = ActionSelectionPayload.model_validate(selection_response)
                if validated_payload.scope == "all" or selection_response.get("value") == "all" or selection_response.get("action") == "all":
                    is_all = True
                else:
                    chosen_items = [{"item_id": it.item_id, "quantity": it.quantity} for it in validated_payload.items]
            except Exception:
                if selection_response.get("scope") == "all" or selection_response.get("value") == "all":
                    is_all = True
                else:
                    chosen_items = selection_response.get("items", [])
        else:
            clean_str = str(selection_response or "").strip().lower()
            if clean_str in ("back", "menu", "keep", "no", "exit", "abort") or is_abort_intent(clean_str):
                
                return reset_to_menu(f"No problem! Order #ORD-{order_id} remains active with no changes made.")
            # Intent switch & Smart Resume FAQ
            if not clean_str.startswith("{") and not validate_expected_input(clean_str, {"all", "all items", "entire", "whole", "cancel whole order", "yes", "1", "2", "3", "4"}):
                switch = detect_intent_switch(clean_str, current_flow=action)
                if switch:
                    if switch["type"] == "workflow_switch":
                        cleared = clear_flow_state(state, switch.get("order_id"))
                        return {**cleared, "action_type": switch["action_type"], "messages": [AIMessage(content=switch["transition_message"])]}
                    elif switch["type"] == "faq_query":
                        return {"resume_node": "confirm_action_node", "faq_prompt": switch.get("question")}

            if clean_str in ("all", "all items", "entire", "whole", "cancel whole order", "yes"):
                is_all = True
            elif clean_str.startswith("{") and clean_str.endswith("}"):
                try:
                    parsed_json = json.loads(clean_str)
                    validated_payload = ActionSelectionPayload.model_validate(parsed_json)
                    if validated_payload.scope == "all":
                        is_all = True
                    else:
                        chosen_items = [{"item_id": it.item_id, "quantity": it.quantity} for it in validated_payload.items]
                except Exception:
                    chosen_items = []

        # If "all" was chosen, select 100% of the active order items
        if is_all:
            chosen_items = [{"item_id": it["item_id"], "quantity": it["quantity"]} for it in items_data]

        # Authoritative server-side refund calculation
        selected_summary = []
        authoritative_refund = 0.0
        for chosen in chosen_items:
            it_id = chosen.get("item_id")
            req_qty = int(chosen.get("quantity", 0))
            matching = next((it for it in items_data if it["item_id"] == it_id), None)
            if matching and req_qty > 0:
                valid_qty = min(req_qty, matching["quantity"])
                subtotal = valid_qty * matching["unit_price"]
                authoritative_refund += subtotal
                selected_summary.append({
                    "item_id": matching["item_id"],
                    "name": matching["name"],
                    "quantity": valid_qty,
                    "unit_price": matching["unit_price"],
                    "subtotal": subtotal,
                })

        if not selected_summary:
            return {
                "confirmed": False,
                "resume_node": None,
                "context": None,
                "action_type": None,
                "order_id": None,
                "customer_details": None,
                "messages": [AIMessage(content=f"No items were selected for {action_noun}. Returning to main menu.")],
            }

    items_list_str = "\n".join([f"• {it['quantity']}× **{it['name']}** (₹{it['subtotal']:.2f})" for it in selected_summary])

    # Explicit Confirmation Interrupt
    confirm_prompt = (
        f"{faq_notice}⚠️ **Confirm {action_noun}**\n\n"
        f"**Selected Items:**\n{items_list_str}\n\n"
        f"💰 **Estimated Refund:** ₹{authoritative_refund:.2f}\n\n"
        f"Are you sure you want to proceed with this {action_verb}?"
    )

    final_reply = interrupt({
        "type": "confirmation",
        "title": f"Confirm {action_noun}",
        "order_id": order_id,
        "items": selected_summary,
        "refund_amount": authoritative_refund,
        "prompt": confirm_prompt,
        "options": [
            {"label": f"✅ Yes, Confirm {action_noun}", "value": "yes"},
            {"label": "🔙 No, Keep Order", "value": "no"},
        ],
    })

    # Check confirmation reply
    is_confirmed = False
    if isinstance(final_reply, dict) and (final_reply.get("confirmed") is True or final_reply.get("value") in ("yes", "1")):
        is_confirmed = True
    elif isinstance(final_reply, dict) and (final_reply.get("value") in ("no", "2", "back", "menu") or is_abort_intent(final_reply)):
        is_confirmed = False
    else:
        # Zero-Ambiguity LLM Confirmation Classifier
        conf_decision = classify_confirmation_intent(
            user_input=final_reply,
            action=action,
            order_id=str(order_id),
            refund_amount=authoritative_refund,
        )

        # STRICT RULE: Must be "confirm" AND confidence >= 0.95 (100% confident)
        if conf_decision.decision == "confirm" and conf_decision.confidence >= 0.95:
            is_confirmed = True
        elif conf_decision.decision == "reject":
            is_confirmed = False
        elif conf_decision.decision == "faq":
            temp_context = {
                "items": selected_summary,
                "refund_amount": authoritative_refund,
                "action_scope": "all" if is_all else "partial",
            }
            return {"resume_node": "confirm_action_node", "faq_prompt": str(final_reply), "context": temp_context}
        elif conf_decision.decision == "workflow_switch":
            switch = detect_intent_switch(final_reply, current_flow=action)
            if switch and switch.get("type") == "workflow_switch":
                cleared = clear_flow_state(state, switch.get("order_id"))
                return {**cleared, "action_type": switch["action_type"], "messages": [AIMessage(content=switch["transition_message"])]}
            is_confirmed = False
        else:
            # "unclear" or confidence < 0.95: Even a 5% ambiguity will NOT confirm!
            raw_text = final_reply.get("value") if isinstance(final_reply, dict) else str(final_reply or "")
            notice = (
                f"⚠️ For your protection, order {action_noun.lower()} requires 100% clear confirmation.\n\n"
                f"Your response *\"{raw_text}\"* could not be verified with 100% certainty. "
                f"No changes were made to Order #ORD-{order_id}.\n\n"
                f"Returning to main menu. If you wish to proceed, please select the action again or click **Yes, Confirm**."
            )
            return {
                "confirmed": False,
                "resume_node": None,
                "context": None,
                "action_type": None,
                "order_id": None,
                "customer_details": None,
                "messages": [AIMessage(content=notice)],
            }

    if not is_confirmed:
        return {
            "action_type": None,
            "order_id": None,
            "customer_details": None,
            "confirmed": False,
            "resume_node": None,
            "context": None,
            "messages": [AIMessage(content=f"Understood! Order #ORD-{order_id} has been kept active with no changes made. Let me know if there's anything else I can help you with!")],
        }

    scope_type = "all" if is_all or len(selected_summary) == len(items_data) else "partial"

    # Pydantic schema validation for database query context
    mutation_context = OrderMutationContext(
        order_id=str(order_id),
        action_type=action,
        action_scope=scope_type,
        items=selected_summary,
        refund_amount=float(authoritative_refund),
    )

    note = (
        f"A refund of ₹{authoritative_refund:.2f} has been initiated to your original payment method (takes 4–7 business days) [SEC-4.0]."
        if action == "cancel_order"
        else f"Our courier partner will pick up the package within 24–48 hours. Once inspected, ₹{authoritative_refund:.2f} will be refunded within 4–7 business days [SEC-4.0]."
    )

    receipt_msg = (
        f"✅ **Order #{order_id} — {action_done.title()} Successfully!**\n\n"
        f"**Items {action_done.title()}:**\n{items_list_str}\n\n"
        f"💰 **Total Refund:** ₹{authoritative_refund:.2f}\n\n"
        f"{note}"
    )

    return {
        "confirmed": True,
        "resume_node": None,
        "context": mutation_context.model_dump(),
    }


# =====================================================================
# 5. DEDICATED EXECUTION NODES (cancel_order_node & return_order_node)
# =====================================================================

def cancel_order_node(state: CustomerState) -> dict:
    """Executes cancellation and returns authoritative receipt message."""
    ctx = state.get("context") or {}
    order_id = ctx.get("order_id") or state.get("order_id")
    refund = float(ctx.get("refund_amount", 0.0))
    items = ctx.get("items", [])
    items_list_str = "\n".join([f"• {it['quantity']}× **{it['name']}** (₹{it['subtotal']:.2f})" for it in items]) or "Whole Order"

    receipt_msg = (
        f"✅ **Order #{order_id} — Cancelled Successfully!**\n\n"
        f"**Items Cancelled:**\n{items_list_str}\n\n"
        f"💰 **Total Refund:** ₹{refund:.2f}\n\n"
        f"A refund of ₹{refund:.2f} has been initiated to your original payment method (takes 4–7 business days) [SEC-4.0]."
    )
    return {
        "messages": [AIMessage(content=receipt_msg)],
        "action_type": None,
        "order_id": None,
        "customer_details": None,
        "confirmed": True,
    }


def return_order_node(state: CustomerState) -> dict:
    """Executes return and returns courier pickup receipt message."""
    ctx = state.get("context") or {}
    order_id = ctx.get("order_id") or state.get("order_id")
    refund = float(ctx.get("refund_amount", 0.0))
    items = ctx.get("items", [])
    items_list_str = "\n".join([f"• {it['quantity']}× **{it['name']}** (₹{it['subtotal']:.2f})" for it in items]) or "Whole Order"

    receipt_msg = (
        f"📦 **Order #{order_id} — Return Initiated Successfully!**\n\n"
        f"**Items for Return:**\n{items_list_str}\n\n"
        f"💰 **Estimated Refund:** ₹{refund:.2f}\n\n"
        f"Our courier partner will pick up the package within 24–48 hours. Once inspected, ₹{refund:.2f} will be refunded within 4–7 business days [SEC-4.0]."
    )
    return {
        "messages": [AIMessage(content=receipt_msg)],
        "action_type": None,
        "order_id": None,
        "customer_details": None,
        "confirmed": True,
    }


# =====================================================================
# 6. POLICY BLOCKED NODE (policy_blocked_node)
# =====================================================================

def get_policy_block_message(order: dict, action: str) -> str:
    """Concise helper returning clear customer-facing policy rejection reason."""
    status = order.get("status", "")
    order_id = order.get("order_id", "")
    deliv = order.get("delivery_date")
    d_date = deliv.date() if isinstance(deliv, datetime) else deliv
    days_ago = (date.today() - d_date).days if d_date else 0

    if action == "cancel_order":
        if status in ("Shipped", "Out for Delivery"):
            return f"🚚 Order #{order_id} has already shipped. You may refuse delivery at your door or request a return once delivered."
        elif status == "Delivered":
            return f"📦 Order #{order_id} has already been delivered. It cannot be cancelled, but you can return it within 7 days."
        elif status == "Cancelled":
            return f"Order #{order_id} was already cancelled. Your refund is processing (5–7 business days)."
        return f"Order #{order_id} is currently '{status}' and cannot be cancelled."
    else:
        if status == "Return_Requested":
            return f"Order #{order_id} already has a return in progress. Pickup is within 24–48 hours."
        elif status == "Returned":
            return f"Order #{order_id} was already returned and refunded."
        elif status == "Delivered" and days_ago > RETURN_WINDOW_DAYS:
            return f"⏳ Order #{order_id} was delivered on {d_date} ({days_ago} days ago). Our return policy only allows returns within {RETURN_WINDOW_DAYS} days of delivery."
        elif status in ("Placed", "Processing"):
            return f"Order #{order_id} hasn't shipped yet! You can cancel it directly from the main menu for a full refund."
        return f"Order #{order_id} is currently '{status}' and cannot be returned."


def policy_blocked_node(state: CustomerState) -> dict:
    """Explains policy rejection and routes customer to support ticket, FAQ answer, or back to main menu."""
    order = state.get("customer_details") or {}
    msg = get_policy_block_message(order, state.get("action_type", ""))

    reply = interrupt({
        "prompt": f"❌ **Policy Notice:**\n{msg}\n\n**How would you like to proceed?**\n\n*(You can raise a ticket, return to the menu, or ask a question about this policy)*",
        "options": [
            {"label": "🎫 Raise Support Ticket / Talk to Agent", "value": "ticket"},
            {"label": "🏠 Return to Main Menu", "value": "menu"},
        ],
    })

    raw_val = reply.get("value") if isinstance(reply, dict) else reply
    cleaned = str(raw_val or "").strip()
    clean_lower = cleaned.lower()

    if any(k in clean_lower for k in ("ticket", "human", "agent", "escalate", "support", "1")):
        return {"action_type": "human_support", "order_id": None, "customer_details": None}

    if is_abort_intent(cleaned) or clean_lower in ("2", "menu", "main menu"):
        return {
            "action_type": None,
            "order_id": None,
            "customer_details": None,
            "messages": [AIMessage(content="Returned to main menu.")],
        }

    # Free-text questions or workflow switch
    switch = detect_intent_switch(cleaned, current_flow="blocked")
    if switch:
        if switch["type"] == "workflow_switch":
            cleared = clear_flow_state(state, switch.get("order_id"))
            return {
                **cleared,
                "action_type": switch["action_type"],
                "order_id": switch.get("order_id"),
                "messages": [AIMessage(content=switch["transition_message"])],
            }
        elif switch["type"] == "faq_query":
            return {
                "action_type": "faq",
                "faq_prompt": switch.get("question"),
                "order_id": None,
                "customer_details": None,
            }

    return {
        "action_type": "faq",
        "faq_prompt": cleaned,
        "order_id": None,
        "customer_details": None,
    }
