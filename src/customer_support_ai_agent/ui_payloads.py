from typing import Dict, Any, List, Optional

def build_welcome_payload() -> Dict[str, Any]:
    return {
        "prompt": "**Hi! How can I help you today?**\n\n*(You can ask about our store policies, track your orders, or request a return/cancellation)*",
        "options": [],
    }

def build_post_action_payload() -> Dict[str, Any]:
    return {
        "prompt": (
            "**Is there anything else I can help you with today?**\n\n"
            "*(You can view your updated orders, check refund timelines, or return to the main menu)*"
        ),
        "options": [
            {"label": "📦 View Remaining Orders", "value": "remaining orders"},
            {"label": "📖 Refund Policy Info", "value": "When will I receive my refund?"},
            {"label": "🏠 Main Menu", "value": "menu"},
        ],
    }

def build_faq_payload(answer: str) -> Dict[str, Any]:
    return {
        "prompt": answer,
        "options": [{"label": "🏠 Main Menu", "value": "menu"}],
    }

def build_order_list_payload(
    action: str,
    orders: List[Dict[str, Any]],
    retry_count: int = 0,
) -> Dict[str, Any]:
    action_verb = "cancel" if action == "cancel_order" else "return"
    action_noun = "Cancellation" if action == "cancel_order" else "Return"

    if retry_count >= 3:
        prompt = (
            f"📦 **Automated {action_noun.lower()} is unavailable.**\n\n"
            "Would you like a support specialist to review your request, or return to the main menu?"
            if not orders else
            "⚠️ **We couldn't locate that order after 3 attempts.**\n\nWould you like to connect with a support specialist or return to the main menu?"
        )
        return {
            "prompt": prompt,
            "options": [
                {"label": "💬 Talk to Specialist", "value": "ticket"},
                {"label": "🏠 Main Menu", "value": "menu"},
            ],
        }

    if not orders:
        return {
            "prompt": f"📦 **You don't have any orders eligible for {action_noun.lower()}.**\n\nOnly orders in *Placed* or *Processing* status can be cancelled, and delivered orders within 7 days can be returned.",
            "options": [{"label": "🏠 Main Menu", "value": "menu"}],
        }

    # Auto-prompt when customer has exactly 1 eligible order
    if len(orders) == 1:
        o = orders[0]
        oid = o.get("order_id")
        return {
            "prompt": (
                f"📦 **You have 1 order eligible for {action_noun.lower()}: ORD-{oid}** ({o.get('status')}, ₹{float(o.get('total_amount', 0)):.2f})\n\n"
                f"Would you like to {action_verb} items from this order?"
            ),
            "options": [
                {"label": f"✅ Yes, {action_verb.title()} ORD-{oid}", "value": f"ORD-{oid}"},
                {"label": "🔙 Back to Main Menu", "value": "menu"},
            ],
        }

    # Multiple orders
    cards = "\n\n".join([
        f"• **Order #ORD-{o.get('order_id')}** — Status: **{o.get('status')}**\n"
        f"  💰 Total: ₹{float(o.get('total_amount', 0)):.2f} | 📅 Ordered: {str(o.get('order_date'))[:10]}"
        for o in orders
    ])
    prompt = f"📦 **Select an order to {action_verb}:**\n\n{cards}"
    options = [
        {"label": f"📦 ORD-{o.get('order_id')}", "value": f"ORD-{o.get('order_id')}"}
        for o in orders
    ]
    options.append({"label": "🔙 Back to Main Menu", "value": "menu"})
    return {"prompt": prompt, "options": options}

def build_item_selection_payload(
    order_id: str,
    action: str,
    active_items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    action_verb = "cancel" if action == "cancel_order" else "return"
    action_noun = "Cancellation" if action == "cancel_order" else "Return"

    items_data = [
        {
            "item_id": it.get("order_item_id") or it.get("id"),
            "name": it.get("product_name", "Item"),
            "quantity": int(it.get("quantity", 1)),
            "unit_price": float(it.get("unit_price", 0)),
        }
        for it in active_items
    ]

    return {
        "type": "item_quantity_selection",
        "title": f"Order #ORD-{order_id}",
        "order_id": order_id,
        "action": action,
        "action_verb": action_verb,
        "action_noun": action_noun,
        "items": items_data,
        "prompt": f"Please select the items and quantities you wish to {action_verb} for Order #ORD-{order_id}:",
        "options": [
            {"label": f"❌ {action_verb.title()} Whole Order", "value": "all"},
            {"label": "🔙 Back to Main Menu", "value": "menu"},
        ],
    }

def build_confirmation_payload(
    order_id: str,
    action: str,
    selected_items: List[Dict[str, Any]],
    refund_amount: float,
) -> Dict[str, Any]:
    action_verb = "cancel" if action == "cancel_order" else "return"
    action_noun = "Cancellation" if action == "cancel_order" else "Return"

    items_summary = "\n".join([
        f"• {it.get('quantity', 1)}× {it.get('name', 'Item')} (₹{float(it.get('unit_price', 0)) * int(it.get('quantity', 1)):.2f})"
        for it in selected_items
    ])

    prompt = (
        f"⚠️ **Confirm {action_noun}**\n\n"
        f"**Selected Items:**\n{items_summary}\n\n"
        f"💰 **Estimated Refund:** ₹{refund_amount:.2f}\n\n"
        f"Are you sure you want to proceed with this {action_verb}?"
    )
    options = [
        {"label": f"✅ Yes, Confirm {action_noun}", "value": "confirm"},
        {"label": f"❌ Keep Order (Don't {action_verb.title()})", "value": "abort"},
        {"label": "🔙 Back to Main Menu", "value": "menu"},
    ]
    return {"prompt": prompt, "options": options}

def build_receipt_message(
    order_id: str,
    action: str,
    selected_items: List[Dict[str, Any]],
    refund_amount: float,
) -> str:
    action_done = "cancelled" if action == "cancel_order" else "returned"
    sec_tag = "[SEC-4.0]" if action == "cancel_order" else "[SEC-3.1]"

    items_summary = "\n".join([
        f"• {it.get('quantity', 1)}× {it.get('name', 'Item')} (₹{float(it.get('unit_price', 0)) * int(it.get('quantity', 1)):.2f})"
        for it in selected_items
    ])

    return (
        f"✅ **Order #{order_id} — {action_done.title()} Successfully!**\n\n"
        f"**Items {action_done.title()}:**\n{items_summary}\n\n"
        f"💰 **Total Refund:** ₹{refund_amount:.2f}\n\n"
        f"A refund of ₹{refund_amount:.2f} has been initiated to your original payment method (takes 4–7 business days) {sec_tag}."
    )

def build_blocked_payload(
    action: str,
    order_id: str,
    status: str,
    reason: str = "",
) -> Dict[str, Any]:
    action_done = "cancelled" if action == "cancel_order" else "returned"
    prompt = (
        f"⚠️ **Order #ORD-{order_id} cannot be {action_done}.**\n\n"
        f"Current Status: **{status}**\n"
        f"{reason}\n\n"
        f"Would you like to connect with a support specialist or return to the main menu?"
    )
    options = [
        {"label": "💬 Talk to Specialist", "value": "ticket"},
        {"label": "🏠 Main Menu", "value": "menu"},
    ]
    return {"prompt": prompt, "options": options}

def build_escalation_message(user_id: int) -> str:
    return (
        f"🎫 **Support Ticket Created: #TCK-{user_id}-8891**\n\n"
        f"A senior support specialist has been assigned to your request and will follow up with you shortly.\n\n"
        f"Thank you for your patience! 🙏"
    )
