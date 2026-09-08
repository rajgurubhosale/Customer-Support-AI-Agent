
from functools import lru_cache
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.types import interrupt
from customer_support_ai_agent.state import CustomerState
from customer_support_ai_agent.db_functions import get_order_with_items, get_order_history
from datetime import datetime, date

RETURN_WINDOW_DAYS = 7
MAX_MENU_RETRIES = 3


import re
import json
from customer_support_ai_agent.prompts import START_NODE_INTENT_SYSTEM_PROMPT, FAQ_SYSTEM_PROMPT
from customer_support_ai_agent.model import model
from customer_support_ai_agent.schemas import IntentClassifier



structured_llm = model.with_structured_output(IntentClassifier)

# 2. Inside entry_node
def entry_node(state: CustomerState) -> dict:
    raw_input = interrupt({
        "prompt": (
            "**Hi! How can I help you today?**\n\n"
            "*(You can also type naturally with your Order ID, e.g. `cancel ORD-15`)*"
        ),
        "options": [
            {"label": "📖 Policy FAQ & Inquiries", "value": "faq"},
            {"label": "❌ Cancel an Order", "value": "cancel_order"},
            {"label": "📦 Return an Order", "value": "return_order"},
            {"label": "💬 Talk to Human / Ticket", "value": "human_support"},
        ]
    })

    user_input = str(raw_input or "").strip().lower()

    # Step A: Deterministic Regex for Order ID (Accepts ORD-15, ORD15, ord-15, ord15)
    id_match = re.search(r'ord-?(\d+)', user_input)
    extracted_order_id = id_match.group(1) if id_match else None

    # Step B: Fast Shortcuts (Zero Cost)
    if user_input in ("1", "faq", "policy"):
        action_type = "faq"
    elif user_input in ("2", "cancel", "cancel_order"):
        action_type = "cancel_order"
    elif user_input in ("3", "return", "return_order"):
        action_type = "return_order"
    elif user_input in ("4", "ticket", "human", "agent", "human_support"):
        action_type = "human_support"
    elif user_input in ("no", "nothing", "bye", "exit", "quit", "done", "nope"):
        return {
            "menu_choice": user_input,
            "action_type": "exit",
            "order_id": None,
            "customer_details": None,
            "retry_count": 0,
            "confirmed": None,
            "policy_block_reason": None,
            "context": None,
            "messages": [AIMessage(content="No problem! Have a wonderful day! 👋")],
        }
    
    # Step C: Strict LLM Intent Classification (Only when shortcuts didn't match)
    else:
        ai_response: IntentClassifier = structured_llm.invoke([
            {"role": "system", "content": START_NODE_INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_input}
        ])
    
        action_type = ai_response.action_type
    return {
        "menu_choice": user_input,
        "action_type": action_type,
        "order_id": extracted_order_id,
        "customer_details": None,
        "retry_count": 0,
        "confirmed": None,
        "policy_block_reason": None,
        "context": None,
    }



"""
- One extra tool, `signal_intent`, lets the LLM itself decide when the user
  is clearly asking to cancel/return/talk-to-human/go-to-menu vs. just asking
  a policy question. The graph routes based on that — buttons are the job of
  whatever node action_type points to, not this one.
- Node just: get user message -> call model with tools -> either hand off
  (intent) or answer conversationally.
"""


from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.types import interrupt
from customer_support_ai_agent.tools import make_tools

from pathlib import Path
# LOAD AND KEEP THE PATH INSIDE THE API AFTER THE USER CLICKS ON THE FaQ NODE AND KEEP THERE
@lru_cache(maxsize=1)
def load_policy_files() -> str:
    policy_path = Path(__file__).resolve().parents[2] / "docs" / "cancellation_and_return_policy.md"
    return policy_path.read_text(encoding="utf-8")



def faq_node(state: CustomerState) -> dict:
    """Conversational policy & order assistant with LLM-driven intent handoff."""
    user_id = int(state.get("user_id") or 1)

    # 1. Prompt for current turn: friendly greeting on first entry, or the AI's previous answer
    prompt = state.get("faq_prompt") or "Hi! How can I help you today? Feel free to ask about our store policies or check your orders."

    # Exactly ONE interrupt per turn: displays the prompt and receives user input
    raw = interrupt({
        "prompt": prompt,
        "options": [{"label": "🏠 Return to Main Menu", "value": "menu"}]
    })
    user_msg = str(raw or "").strip()

    # 2. Fast exit to menu
    if user_msg.lower() in ("menu", "back", "exit", "main menu"):
        return {
            "action_type": "exit_to_menu",
            "faq_prompt": None,
            "menu_choice": None,
            "messages": [AIMessage(content="Returned to Main Menu.")],
        }

    tools = make_tools(user_id)
    tool_map = {t.name: t for t in tools}
    model_with_tools = model.bind_tools(tools)


    messages = [
        SystemMessage(content=FAQ_SYSTEM_PROMPT.format(store_policies=load_policy_files())),
        HumanMessage(content=user_msg),
    ]

    try:
        ai_msg = model_with_tools.invoke(messages)
    except Exception as e:
        print(f"FAQ Agent error: {e}")
        ai_msg = AIMessage(content="I can help with orders, cancellations, returns, and refunds. Could you rephrase your question?")

    # 3. Intent handoff takes priority (when user asks to cancel/return/human/menu)
    for tc in getattr(ai_msg, "tool_calls", None) or []:
        if tc["name"] == "signal_intent":
            args = tc["args"]
            intent = args.get("intent", "faq")
            raw_oid = args.get("order_id")
            if not raw_oid:
                m = re.search(r'ord-?(\d+)', user_msg, re.IGNORECASE) or re.search(r'order\s*#?\s*(\d+)', user_msg, re.IGNORECASE)
                raw_oid = m.group(1) if m else None
            order_id = re.sub(r'[^\d]', '', str(raw_oid)) if raw_oid else None
            return {
                "action_type": intent,
                "order_id": order_id,
                "faq_prompt": None,
                "menu_choice": None,
                "messages": [AIMessage(content=f"Got it, let's {intent.replace('_', ' ')}.")],
            }

    # 4. Resolve data lookup tool calls (get_recent_orders, get_order_details)
    if getattr(ai_msg, "tool_calls", None):
        messages.append(ai_msg)
        for tc in ai_msg.tool_calls:
            func = tool_map.get(tc["name"])
            result = func.invoke(tc["args"]) if func else "Tool not found"
            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        answer = model.invoke(messages).content
    else:
        answer = ai_msg.content

    # 5. Save answer as next turn's prompt and loop back to faq_node
    return {
        "action_type": "faq",
        "faq_prompt": answer,
        "menu_choice": None,
    }





def order_lookup_node(state: CustomerState) -> dict:
    """Fetches order. If order_id is missing, prompts user with structured order options. Loops via router if not found."""
    user_id = state["user_id"]
    retries = state.get("retry_count", 0)
    order_id = state.get("order_id")
    action = state.get("action_type")
    action_verb = "cancel" if action == "cancel_order" else "return"
    action_text = "cancel your order" if action == "cancel_order" else "request a return"

    # 1. Only prompt if we don't have an order_id yet
    if not order_id:
        eligible_orders = []
        if retries > 0:
            prompt = (
                f"❌ We couldn't find that order. Please check and enter your Order ID in format `ORD-XX` "
                f"(Attempt {retries + 1}/3):\n\n*(Or select an option below)*"
            )
            payload = {
                "type": "order_selection",
                "prompt": prompt,
                "orders": [],
                "options": [
                    {"label": "🔙 Back to Main Menu", "value": "menu"},
                    {"label": "💬 Talk to Human / Ticket", "value": "ticket"},
                ]
            }
        else:
            all_recent = get_order_history(user_id) or []

            # Action-aware filtering: only show orders eligible for the selected action
            if action == "cancel_order":
                eligible_orders = [
                    o for o in all_recent
                    if o.get("status") in ("Placed", "Processing", "Partially_Cancelled")
                ]
                header_title = "📦 Orders Eligible for Cancellation:"
            elif action == "return_order":
                eligible_orders = []
                for o in all_recent:
                    if o.get("status") in ("Delivered", "Partially_Returned"):
                        d_date = o.get("delivery_date")
                        if d_date:
                            d_val = d_date.date() if isinstance(d_date, datetime) else d_date
                            if (date.today() - d_val).days <= RETURN_WINDOW_DAYS:
                                eligible_orders.append(o)
                header_title = "📦 Orders Eligible for Return:"
            else:
                eligible_orders = all_recent
                header_title = "📦 Your Recent Orders:"

            displayed_orders = eligible_orders[:4]
            if displayed_orders:
                orders_options = [
                    {
                        "label": f"📦 ORD-{o['order_id']} — ₹{float(o.get('total_amount', 0)):.2f} — {o.get('status')}",
                        "value": str(o['order_id'])
                    }
                    for o in displayed_orders
                ]
                payload = {
                    "type": "order_selection",
                    "title": f"Select an Order to {action_verb.title()}",
                    "prompt": f"📦 **Select an order to {action_verb}:**",
                    "orders": [
                        {
                            "order_id": str(o["order_id"]),
                            "status": o.get("status", ""),
                            "total": float(o.get("total_amount", 0)),
                            "order_date": str(o.get("order_date", ""))[:10] if o.get("order_date") else "",
                        }
                        for o in displayed_orders
                    ],
                    "options": orders_options + [{"label": "🔙 Back to Main Menu", "value": "menu"}]
                }
            else:
                if action == "cancel_order":
                    reason_text = "cancellation (orders already shipped or delivered cannot be cancelled directly)"
                else:
                    reason_text = f"return (orders must be delivered within the last {RETURN_WINDOW_DAYS} days)"

                payload = {
                    "type": "order_selection",
                    "prompt": (
                        f"Sure, I can help you {action_text}.\n\n"
                        f"ℹ️ **You have no recent orders eligible for {reason_text}.**\n\n"
                        f"👉 Please enter your **Order ID** in format `ORD-XX` (e.g. `ORD-15`) if you wish to check another order:\n\n"
                    ),
                    "orders": [],
                    "options": [{"label": "🔙 Back to Main Menu", "value": "menu"}]
                }

        raw_input = interrupt(payload)

        # Handle structured dictionary or string response
        if isinstance(raw_input, dict):
            selected_val = str(
                raw_input.get("selected_order_id")
                or raw_input.get("order_id")
                or raw_input.get("value")
                or ""
            ).strip()
        elif isinstance(raw_input, str):
            raw_str = raw_input.strip()
            if raw_str.startswith("{") and raw_str.endswith("}"):
                try:
                    parsed = json.loads(raw_str)
                    selected_val = str(
                        parsed.get("selected_order_id")
                        or parsed.get("order_id")
                        or parsed.get("value")
                        or ""
                    ).strip()
                except Exception:
                    selected_val = raw_str
            else:
                selected_val = raw_str
        else:
            selected_val = str(raw_input or "").strip()

        clean_val = selected_val.upper()
        if clean_val in ("MENU", "MAIN MENU", "BACK", "EXIT", "NO"):
            return {
                "action_type": "exit_to_menu",
                "retry_count": 0,
                "order_id": None,
                "customer_details": None,
            }

        # Check if user typed index like '1' or '2'
        displayed_orders = eligible_orders[:4] if eligible_orders else []
        if displayed_orders and clean_val.isdigit() and 1 <= int(clean_val) <= len(displayed_orders):
            selected_order = displayed_orders[int(clean_val) - 1]
            order_id = str(selected_order.get("order_id"))
        else:
            id_match = re.search(r'ORD-?(\d+)', clean_val, re.IGNORECASE)
            if id_match:
                order_id = id_match.group(1)
            elif clean_val.isdigit():
                order_id = clean_val
            else:
                order_id = None

    # 2. Query PostgreSQL only if valid format was provided
    order_details = get_order_with_items(order_id, customer_id=user_id) if order_id else None

    # 3. If not found -> increment retries and clear order_id so next loop prompts the user
    if order_details is None:
        return {
            "retry_count": retries + 1,
            "order_id": None,
            "customer_details": None,
        }

    # 4. If found -> success!
    return {
        "retry_count": 0,
        "order_id": order_id,
        "customer_details": order_details,
    }



def human_escalate_node(state: CustomerState) -> dict:
    """Displays human escalation & support ticket placeholder with option to return to the main menu."""
    interrupt({
        "prompt": (
            "💬 **Human Support & Ticket Escalation (Placeholder)**\n\n"
            "Your request has been routed to our priority customer care team. "
            "A support ticket has been recorded, and an agent will follow up with you shortly.\n\n"
            "*(Click below when you want to return to the main menu)*"
        ),
        "options": [
            {"label": "🏠 Return to Main Menu", "value": "menu"}
        ]
    })
    return {
        "action_type": "exit_to_menu",
        "messages": [AIMessage(content="Returned from Human Support.")],
    }



def confirm_action_node(state: CustomerState) -> dict:
    """Unified confirmation node for both Cancel and Return.
    Uses structured UI interrupts: item selection with steppers, server-side refund calculation, and final confirmation."""
    order = state.get("customer_details") or {}
    order_id = str(order.get("order_id", state.get("order_id") or ""))
    all_items = order.get("items", [])
    total_amount = float(order.get("total_amount", 0))
    action = state.get("action_type", "cancel_order")

    action_verb = "cancel" if action == "cancel_order" else "return"
    action_noun = "Cancellation" if action == "cancel_order" else "Return"
    action_done = "cancelled" if action == "cancel_order" else "returned"

    # Filter active items that can still be cancelled or returned
    active_items = [
        it for it in all_items 
        if it.get("item_status") not in ("Cancelled", "Returned")
    ]
    if not active_items:
        active_items = all_items

    # Format items for structured UI
    items_data = [
        {
            "item_id": it.get("order_item_id") or it.get("id"),
            "name": it.get("product_name", "Item"),
            "quantity": int(it.get("quantity", 1)),
            "unit_price": float(it.get("unit_price", 0)),
        }
        for it in active_items
    ]

    # --- Turn 1: Item & Quantity Selection Interrupt ---
    selection_payload = {
        "type": "item_quantity_selection",
        "title": f"Order #ORD-{order_id}",
        "order_id": order_id,
        "action": action,
        "action_verb": action_verb,
        "action_noun": action_noun,
        "status": order.get("status", ""),
        "order_date": str(order.get("order_date", ""))[:10] if order.get("order_date") else "",
        "order_total": total_amount,
        "items": items_data,
        "prompt": f"Please select the items and quantities you wish to {action_verb} for **Order #ORD-{order_id}**:",
        "options": [
            {"label": f"❌ {action_verb.title()} Entire Order", "value": "all"},
            {"label": "🔙 Keep Order / Back", "value": "back"},
        ]
    }

    selection_response = interrupt(selection_payload)

    # Check if user cancelled or went back
    if isinstance(selection_response, dict):
        if selection_response.get("action") in ("back", "abort", "exit") or selection_response.get("value") in ("back", "menu", "keep"):
            return {
                "confirmed": False,
                "context": None,
                "messages": [AIMessage(content=f"No changes made to Order #ORD-{order_id}. Returning to main menu.")],
            }
        chosen_items = selection_response.get("items", [])
    elif isinstance(selection_response, str):
        clean_str = selection_response.strip().lower()
        if clean_str in ("back", "menu", "keep", "no", "exit", "abort"):
            return {
                "confirmed": False,
                "context": None,
                "messages": [AIMessage(content=f"No changes made to Order #ORD-{order_id}. Returning to main menu.")],
            }
        if clean_str.startswith("{") and clean_str.endswith("}"):
            try:
                parsed = json.loads(selection_response)
                chosen_items = parsed.get("items", [])
            except Exception:
                chosen_items = []
        elif clean_str in ("all", "all items", "entire", "yes"):
            chosen_items = [{"item_id": it["item_id"], "quantity": it["quantity"]} for it in items_data]
        else:
            chosen_items = []
    else:
        chosen_items = []

    # Authoritative server-side refund calculation (never trust client amount)
    selected_summary = []
    authoritative_refund = 0.0

    for chosen in chosen_items:
        it_id = chosen.get("item_id")
        req_qty = int(chosen.get("quantity", 0))
        if req_qty <= 0:
            continue

        matching = next((it for it in items_data if it["item_id"] == it_id), None)
        if matching:
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
            "context": None,
            "messages": [AIMessage(content=f"No items were selected for {action_noun}. Returning to main menu.")],
        }

    # --- Turn 2: Final Structured Confirmation Interrupt ---
    summary_lines = "\n".join([
        f"- **{it['name']}** × {it['quantity']} (₹{it['subtotal']:.2f})"
        for it in selected_summary
    ])

    confirm_payload = {
        "type": "confirmation",
        "title": f"Confirm {action_noun}",
        "order_id": order_id,
        "items": selected_summary,
        "refund_amount": authoritative_refund,
        "prompt": (
            f"⚠️ **Confirm {action_noun}**\n\n"
            f"**Selected Items:**\n{summary_lines}\n\n"
            f"💰 **Estimated Refund:** ₹{authoritative_refund:.2f}\n\n"
            f"Are you sure you want to proceed with this {action_verb}?"
        ),
        "options": [
            {"label": f"✅ Yes, Confirm {action_noun}", "value": "yes"},
            {"label": "🔙 Go Back", "value": "no"},
        ]
    }

    final_reply = interrupt(confirm_payload)

    # Check confirmation reply
    is_confirmed = False
    if isinstance(final_reply, dict):
        is_confirmed = bool(final_reply.get("confirmed")) or final_reply.get("value") in ("yes", "1")
    elif isinstance(final_reply, str):
        is_confirmed = final_reply.strip().lower() in ("yes", "y", "1", "confirm", "sure", "true")

    if is_confirmed:
        note = (
            f"A refund of ₹{authoritative_refund:.2f} has been initiated to your original payment method. "
            f"It will be credited back to your account within 4–7 business days according to our store policy [SEC-4.0]."
            if action == "cancel_order"
            else (
                f"Our courier partner will pick up the package within 24–48 hours. "
                f"Once doorstep inspection is completed, your refund of ₹{authoritative_refund:.2f} will be credited "
                f"back to your account within 4–7 business days according to our store policy [SEC-4.0]."
            )
        )
        return {
            "confirmed": True,
            "context": {
                "action_scope": "all" if len(selected_summary) == len(items_data) else "partial",
                "order_id": order_id,
                "items": selected_summary,
                "refund_amount": authoritative_refund,
            },
            "messages": [AIMessage(content=f"✅ Successfully {action_done} selected items for Order #ORD-{order_id}!\n\n{note}")],
        }

    return {
        "confirmed": False,
        "context": None,
        "messages": [AIMessage(content=f"No changes made to Order #ORD-{order_id}. Returning to main menu.")],
    }



from customer_support_ai_agent.schemas import BlockedOptionClassifier, RetryExhaustedClassifier

blocked_classifier_llm = model.with_structured_output(BlockedOptionClassifier)
retry_classifier_llm = model.with_structured_output(RetryExhaustedClassifier)

def policy_blocked_node(state: CustomerState) -> dict:
    """Explains policy rejection and handles both numeric choices and natural complaints."""
    order = state["customer_details"]
    order_id = order.get("order_id", state.get("order_id"))
    status = order.get("status", "")
    action = state.get("action_type")
    delivery_date = order.get("delivery_date")
    updated_at = order.get("updated_at") or order.get("order_date")
    total_amount = order.get("total_amount", 0)

    # Helper date formatting
    u_date = updated_at.date() if isinstance(updated_at, datetime) else updated_at
    date_str = f" on {u_date.strftime('%d %b %Y')}" if u_date else ""
    days_since_update = (date.today() - u_date).days if u_date else 0

    # --- 1. Policy Explanation Messages ---
    if action == "cancel_order":
        if status in ("Shipped", "Out for Delivery"):
            msg = (
                f"🚚 Order #{order_id} has already shipped and is on its way! "
                "Because it has left our warehouse, it cannot be cancelled directly. "
                "You may refuse the delivery at your door or return it once received."
            )
        elif status == "Delivered":
            msg = (
                f"📦 Order #{order_id} has already been delivered. It cannot be cancelled, "
                "but you can request a return within 7 days from the main menu."
            )
        elif status == "Cancelled":
            if days_since_update <= 5:
                msg = (
                    f"Order #{order_id} was cancelled{date_str}. "
                    f"Your refund of ₹{total_amount} is currently being processed (takes 5–7 business days)."
                )
            else:
                msg = (
                    f"Order #{order_id} was cancelled{date_str}. "
                    f"The refund of ₹{total_amount} was already completed. "
                    "If you don't see it on your bank statement, choose 1 to raise a support ticket."
                )
        elif status == "Partially_Cancelled":
            msg = f"All remaining items in Order #{order_id} have already been cancelled."
        else:
            msg = f"Order #{order_id} is currently '{status}' and cannot be cancelled."

    elif action == "return_order":
        if status == "Return_Requested":
            msg = (
                f"Order #{order_id} already has a return in progress. Our courier partner is scheduled "
                f"to pick up the item. Your refund of ₹{total_amount} will be processed within 48 hours of pickup."
            )
        elif status == "Returned":
            msg = (
                f"Order #{order_id} has already been returned and processed{date_str}. "
                f"Your refund of ₹{total_amount} has already been completed to your original payment method."
            )
        elif status == "Delivered" and delivery_date:
            d_date = delivery_date.date() if isinstance(delivery_date, datetime) else delivery_date
            days_ago = (date.today() - d_date).days
            msg = (
                f"⏳ Order #{order_id} was delivered on {d_date} ({days_ago} days ago). "
                f"Our return policy only allows returns within {RETURN_WINDOW_DAYS} days of delivery."
            )
        elif status in ("Placed", "Processing"):
            msg = (
                f"Order #{order_id} hasn't shipped yet! You cannot return an unreceived order, "
                "but you can cancel it directly from the main menu for a full refund."
            )
        elif status in ("Shipped", "Out for Delivery"):
            msg = (
                f"🚚 Order #{order_id} is currently in transit ({status}). "
                "You can initiate a return once the package is delivered."
            )
        elif status == "Cancelled":
            msg = f"Order #{order_id} was cancelled before shipment, so no return is needed."
        elif status == "Partially_Returned":
            msg = f"All eligible items in Order #{order_id} have already been returned or requested for return."
        else:
            msg = f"Order #{order_id} is currently '{status}' and cannot be returned."

    # --- 2. Prompt Customer ---
    reply = interrupt({
        "prompt": (
            f"❌ **Policy Notice:**\n{msg}\n\n"
            "**How would you like to proceed?**\n\n"
            "*(Or type your question/complaint directly)*"
        ),
        "options": [
            {"label": "🎫 Raise Support Ticket / Talk to Agent", "value": "1"},
            {"label": "🏠 Return to Main Menu", "value": "2"},
        ]
    })

    # --- 3. Step A: Fast Shortcuts (Zero Cost) ---
    raw_val = reply.get("value") if isinstance(reply, dict) else reply
    cleaned = str(raw_val or "").strip().lower()
    if cleaned in ("1", "ticket", "human", "agent", "escalate"):
        decision = "ticket"
    elif cleaned in ("2", "menu", "main menu", "back", "exit", "no"):
        decision = "menu"

    # --- 4. Step B: LLM Fallback (Ambiguous / Natural Text) ---
    else:
        try:
            ai_choice: BlockedOptionClassifier = blocked_classifier_llm.invoke(
                f"The customer's request was rejected with message: '{msg}'.\n"
                f"Customer typed: '{cleaned}'.\n"
                "Classify whether the customer wants human support/ticket ('ticket') "
                "or wants to return to the main menu/exit ('menu')."
            )
            decision = ai_choice.decision
        except Exception:
            decision = "ticket"  # Safe default: when in doubt, connect customer to human support

    return {
        "blocked_choice": decision,
        "order_id": None,
        "customer_details": None,
    }




def retry_exhausted_node(state: CustomerState) -> dict:
    """Runs after MAX_ORDER_RETRIES failed order lookups.
    Provides options to retry entering order ID, return to main menu, or raise a support ticket."""
    prompt = (
        "⚠️ **We couldn't locate that order after 3 attempts.**\n\n"
        "**How would you like to proceed?**\n\n"
        "*(Or type your message directly)*"
    )
    reply = interrupt({
        "prompt": prompt,
        "options": [
            {"label": "🔁 Try Entering Order ID Again", "value": "1"},
            {"label": "🏠 Return to Main Menu", "value": "2"},
            {"label": "🎫 Raise Support Ticket", "value": "3"},
        ]
    })

    # Step A: Fast Shortcuts (0ms, Zero Cost)
    raw_val = reply.get("value") if isinstance(reply, dict) else reply
    cleaned = str(raw_val or "").strip().lower()
    if cleaned in ("1", "retry", "again", "try again", "re-enter", "cancel", "return", "i want to cancel", "i want to return", "i wnat to cancel my order"):
        decision = "retry"
    elif cleaned in ("2", "menu", "main menu", "back", "exit", "no"):
        decision = "menu"
    elif cleaned in ("3", "ticket", "human", "agent", "escalate", "help"):
        decision = "ticket"
    # Step B: LLM Fallback for Natural / Ambiguous Language
    else:
        try:
            ai_choice: RetryExhaustedClassifier = retry_classifier_llm.invoke(
                f"The customer failed 3 attempts to find their order ID.\n"
                f"Customer response: '{reply}'.\n"
                "Classify whether the customer wants to try entering their order again ('retry'), "
                "return to the main menu ('menu'), or raise a support ticket / speak with a human ('ticket')."
            )
            decision = ai_choice.decision
        except Exception:
            decision = "retry"  # Safe default: give user another chance to input ID before burdening human

    # Clean up state so next order lookup starts fresh
    return {
        "retry_exhausted_choice": decision,
        "retry_count": 0,
        "order_id": None,
        "customer_details": None,
    }





# PRESERVSE THIS NODES WRITE SOME LOGIC SO IT WILL SAFELY RETURN TO THOSE FROM THE CONFIRMATION NODE TO THIS NODE:



def return_order_node(state: CustomerState) -> dict:
    # WRITE UPDATE CODE
    # WRITE REFUND MSG
    # WRITE REFUND CODE

    #refund_line = (
    #        f"• Refund Amount: ₹{total_amount} (processed within 3-5 business days after pickup)\n"
    #        if total_amount
    #        else "• Refund: Initiated to your original payment method once the package is inspected\n"
    #    )

    msg = (
            f"Return Request Confirmed! 📦\n\n"
            f"• Order ID: #{state['order_id']}\n"
     #       f"{refund_line}"
            f"• Next Steps: Our courier partner will pick up the package within 24–48 hours. "
            f"Make sure the order isnt damaged\n"
            f"Please ensure all original tags and packaging are intact.\n\n"
            f"We're redirecting you to the main menu."
        )

    return {
        "messages": [AIMessage(content=msg)],
        "order_id": None,
        "customer_details": None,
        "return_confirmed": None,
    }

    
def cancel_order_node(state: CustomerState) -> dict:
    """Executes cancellation and displays what was cancelled."""
    cancel_info = state.get("context") or {}
    scope = cancel_info.get("cancel_scope", "all")
    item_name = cancel_info.get("item_name", "Order")
    refund = cancel_info.get("refund", 0)
    # TODO: Execute DB Update (SQL query) using cancel_info
    # if scope == "all": cancel entire order
    # if scope == "single": cancel order_item_id only
    msg = (
        f"Cancellation Confirmed! ✅\n\n"
        f"• Cancelled: {item_name}\n"
        f"• Refund Initiated: ₹{refund}\n\n"
        f"Redirecting you back to the main menu."
    )
    return {
        "messages": [AIMessage(content=msg)],
        "order_id": None,
        "customer_details": None,
        "cancel_confirmed": None,
        "context": None,
    }

    # then cancel and show the msg of cancellations
    # and update in db user data

