from typing import Any, Dict, List

# Reusable Standard Buttons
BTN_MENU = {"label": "🔙 Back to Main Menu", "value": "menu"}
BTN_SPECIALIST = {"label": "💬 Talk to Specialist", "value": "ticket"}
BTN_TRACK = {"label": "📦 View Recent Orders", "value": "track_order"}
BTN_EXIT = {"label": "👋 I'm All Done (Exit)", "value": "exit"}

ACTION_CONFIG = {
    "cancel_order": {"verb": "cancel", "noun": "Cancellation", "done": "cancelled"},
    "return_order": {"verb": "return", "noun": "Return", "done": "returned"},
}


# SHOW MENU PAYLOADS INTERRUPT
def build_welcome_payload(is_followup: bool = False) -> Dict[str, Any]:
    """
    Constructs the initial greeting prompt for new chats, or a shorter 
    follow-up prompt when continuing an existing conversation.
    """
    if is_followup:
        return {
            "prompt": "**Tell me what you'd like to do next.**",
            "options": [],
        }

    return {
        "prompt": "**Hi! How can I help you today?**\n\n*(You can ask about our store policies, track your orders, or request a return/cancellation)*",
        "options": [],
    }


def build_post_action_payload() -> Dict[str, Any]:
    return {
        "prompt": "",
        "options": [
            BTN_TRACK,
            BTN_EXIT,
        ],
    }


def build_order_list_payload(action: str, orders: List[Dict[str, Any]]) -> Dict[str, Any]:

    cfg = ACTION_CONFIG.get(action, ACTION_CONFIG["cancel_order"])
    action_verb = cfg["verb"]

    if not orders:
        if action == "cancel_order":
            prompt = (
                "📦 **I couldn't find an order eligible for cancellation.**\n\n"
                "Only orders in an eligible cancellation status can be cancelled."
            )
        else:
            prompt = (
                "📦 **I couldn't find an order eligible for return.**\n\n"
                "Returns are available for delivered orders within the "
                "7-day return window."
            )

        return {
            "prompt": prompt,
            "options": [
                BTN_TRACK,
                BTN_SPECIALIST,
                BTN_MENU,
            ],
        }

    # show on ui total orders proper
    cards = "\n\n".join([
        f"• **Order #ORD-{order.get('order_id')}** — "
        f"Status: **{order.get('status')}**\n"
        f"  💰 Total: ₹{float(order.get('total_amount', 0)):.2f} | "
        f"📅 Ordered: {str(order.get('order_date'))[:10]}"
        for order in orders
    ])

    # orders options
    options = [
        {
            "label": f"📦 ORD-{order.get('order_id')}",
            "value": f"ORD-{order.get('order_id')}",
        }
        for order in orders
    ]

    options.extend([
        BTN_SPECIALIST,
        BTN_MENU,
    ])

    return {
        "prompt": f"📦 **Select an order to {action_verb}:**\n\n{cards}",
        "options": options,
    }


def build_item_selection_payload(order_id: str,action: str,active_items: List[Dict[str, Any]],) -> Dict[str, Any]:
    
    cfg = ACTION_CONFIG.get(action, ACTION_CONFIG["cancel_order"])
    action_verb = cfg["verb"]
    action_noun = cfg["noun"]

    items_data = [
        {
            "item_id": item.get("order_item_id"),
            "name": item.get("product_name", "Item"),
            "quantity": int(item.get("quantity")),
            "unit_price": float(item.get("unit_price")),
        }
        for item in active_items
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
            BTN_MENU,
        ],
    }


def build_confirmation_payload(order_id: str,action: str,selected_items: List[Dict[str, Any]],refund_amount: float,) -> Dict[str, Any]:
    cfg = ACTION_CONFIG.get(action, ACTION_CONFIG["cancel_order"])
    action_verb = cfg["verb"]
    action_noun = cfg["noun"]

    items_summary = "\n".join(
        [
        f"• {items.get('quantity', 1)}× {items.get('name', 'Item')} (₹{float(items.get('unit_price', 0)) * int(items.get('quantity', 1)):.2f})"
        for items in selected_items
    ])

    prompt = (
    f"⚠️ **Confirm {action_noun} (Order #ORD-{order_id})**\n\n"
        f"**Selected Items:**\n{items_summary}\n\n"
        f"💰 **Estimated Refund:** ₹{refund_amount:.2f}\n\n"
        f"Are you sure you want to proceed with this {action_verb}?"
    )
    options = [
        {"label": f"✅ Yes, Confirm {action_noun}", "value": "confirm"},
        {"label": f"❌ Keep Order (Don't {action_verb.title()})", "value": "abort"},
        BTN_MENU,
    ]
    return {"prompt": prompt, "options": options}


def build_receipt_message(
    order_id: str,
    action: str,
    selected_items: List[Dict[str, Any]],
    refund_amount: float,
) -> str:
    cfg = ACTION_CONFIG.get(action, ACTION_CONFIG["cancel_order"])
    action_done = cfg["done"]
    sec_tag = "[SEC-4.0]" if action == "cancel_order" else "[SEC-3.1]"

    items_summary = "\n".join([
        f"• {it.get('quantity', 1)}× {it.get('name', 'Item')} (₹{float(it.get('unit_price', 0)) * int(it.get('quantity', 1)):.2f})"
        for it in selected_items
    ])

    return (
        f"✅ **Order #{order_id} — {action_done.title()} Successfully!**\n\n"
        f"**Items {action_done.title()}:**\n{items_summary}\n\n"
        f"💰 **Total Refund:** ₹{refund_amount:.2f}\n\n"
        f"A refund of ₹{refund_amount:.2f} has been initiated to your original payment method (takes 4–7 business days) {sec_tag}.\n\n"
        f"---\n"
        f"**Is there anything else I can help you with today?**\n\n"
        f"*(You are completely free to ask anything about your refund, other orders, or store policies!)*"
    )


def build_blocked_payload(
    action: str,
    order_id: str,
    reason: str = "",
) -> Dict[str, Any]:
    cfg = ACTION_CONFIG.get(action, ACTION_CONFIG["cancel_order"])
    action_noun = cfg["noun"]

    prompt = (
        f"⚠️ **{action_noun} Unavailable for Order #ORD-{order_id}**\n\n"
        f"{reason}\n\n"
        f"Would you like to connect with a support specialist or return to the main menu?"
    )
    options = [
        BTN_SPECIALIST,
        BTN_MENU,
    ]
    return {"prompt": prompt, "options": options}


def build_escalation_message(user_id: int) -> str:
    return (
        f"🎫 **Support Ticket Created: #TCK-{user_id}-8891**\n\n"
        f"A senior support specialist has been assigned to your request and will follow up with you shortly.\n\n"
        f"Thank you for your patience! 🙏"
    )
