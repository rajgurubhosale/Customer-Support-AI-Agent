
from langchain_core.messages import AIMessage
from langgraph.types import interrupt
from customer_support_ai_agent.state import CustomerState
from customer_support_ai_agent.db_functions import get_order_with_items, get_order_history
from datetime import datetime, date

RETURN_WINDOW_DAYS = 7
MAX_MENU_RETRIES = 3


import re
from customer_support_ai_agent.prompts import START_NODE_INTENT_SYSTEM_PROMPT
from customer_support_ai_agent.model import model
from customer_support_ai_agent.schemas import IntentClassifier



structured_llm = model.with_structured_output(IntentClassifier)

# 2. Inside entry_node:
def entry_node(state: CustomerState) -> dict:
    prompt = (
        "Hi! How can I help you today?\n\n"
        "TYPE: 1 -> Policy FAQ & General Inquiries\n"
        "TYPE: 2 -> Cancel an Order\n"
        "TYPE: 3 -> Return an Order\n"
        "TYPE: 4 -> Talk to Human / Support Ticket\n"
        "TYPE: 5 -> Demo Video\n\n"
        "(You can also type naturally with your Order ID, e.g. 'cancel ORD-15')"
    )
    user_input = interrupt(prompt).strip().lower()

    # Step A: Deterministic Regex for Order ID (Accepts ORD-15, ORD15, ord-15, ord15)
    id_match = re.search(r'ord-?(\d+)', user_input)
    extracted_order_id = id_match.group(1) if id_match else None

    # Step B: Fast Shortcuts (Zero Cost)
    if user_input in ("1", "faq", "policy"):
        action_type = "faq"
    elif user_input in ("2", "cancel"):
        action_type = "cancel_order"
    elif user_input in ("3", "return"):
        action_type = "return_order"
    elif user_input in ("4", "ticket", "human", "agent"):
        action_type = "human_support"
    elif user_input in ("5", "demo", "video"):
        action_type = "demo"
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



def demo_node(state: CustomerState) -> dict:
    # prompt = (
    #     "🎥 [Demo Video]: You can view our quick walkthrough demo at https://example.com/demo\n"
    #     "Press Enter or type any message to return to the main menu."
    # )
    # interrupt(prompt)
    # return {}
    return {"messages": [AIMessage(content="Demo video — placeholder")]}



def order_lookup_node(state: CustomerState) -> dict:
    """Fetches order. If order_id is missing, prompts user. Loops via router if not found."""
    user_id = state["user_id"]
    retries = state.get("retry_count", 0)
    order_id = state.get("order_id")
    action = state.get("action_type")
    action_text = "cancel your order" if action == "cancel_order" else "request a return"

    # 1. Only prompt if we don't have an order_id yet
    if not order_id:
        eligible_orders = []
        if retries > 0:
            prompt = (
                f"❌ We couldn't find that order. Please check and enter your Order ID in format ORD-XX "
                f"(Attempt {retries + 1}/3):\n(Or type 'menu' to return to the main menu)"
            )
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

            displayed_orders = eligible_orders[:3]
            if displayed_orders:
                orders_list = []
                for idx, o in enumerate(displayed_orders, 1):
                    o_id = o.get("order_id")
                    o_status = o.get("status", "")
                    o_amt = o.get("total_amount", 0)
                    orders_list.append(f"  [{idx}] ORD-{o_id} (₹{o_amt}, Status: {o_status})")
                orders_snippet = f"\n\n{header_title}\n" + "\n".join(orders_list) + "\n\n"
                selection_hint = (
                    f"• TYPE: Number (1 to {len(displayed_orders)}) to select an order above, OR enter ORD-XX:\n"
                    f"(Or type 'menu' to return to the main menu)"
                )
                prompt = f"Sure, I can help you {action_text}.{orders_snippet}{selection_hint}"
            else:
                if action == "cancel_order":
                    reason_text = "cancellation (orders already shipped or delivered cannot be cancelled directly)"
                else:
                    reason_text = f"return (orders must be delivered within the last {RETURN_WINDOW_DAYS} days)"

                prompt = (
                    f"Sure, I can help you {action_text}.\n\n"
                    f"ℹ️ You have no recent orders eligible for {reason_text}.\n\n"
                    f"Please enter your Order ID in format ORD-XX (e.g. ORD-15) if you wish to check another order, or type 'menu' to go back:"
                )

        user_input = interrupt(prompt).strip().upper()

        if user_input in ("MENU", "MAIN MENU", "BACK", "EXIT", "NO"):
            return {
                "action_type": "exit_to_menu",
                "retry_count": 0,
                "order_id": None,
                "customer_details": None,
            }

        # Check if user typed a number matching one of the displayed eligible orders (e.g. '1', '2')
        displayed_orders = eligible_orders[:3] if eligible_orders else []
        if displayed_orders and user_input.isdigit() and 1 <= int(user_input) <= len(displayed_orders):
            selected_order = displayed_orders[int(user_input) - 1]
            order_id = str(selected_order.get("order_id"))
        else:
            id_match = re.search(r'ORD-?(\d+)', user_input)
            order_id = id_match.group(1) if id_match else None

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

    # it should have the interrupt msg and the msg box that will tell the user
    # to write the input or msg for the human
    # or the email maybe for the human esacaltion if u wnat adding latency so 
    # this way only serioes people will write the email and get to us4
    return {"messages": [AIMessage(content="Human escalate — placeholder")]}



def confirm_action_node(state: CustomerState) -> dict:
    """Unified confirmation node for both Cancel and Return.
    Handles single-item, multi-item selection, and partial quantity cancellation/returns."""
    order = state.get("customer_details") or {}
    order_id = order.get("order_id", state.get("order_id"))
    all_items = order.get("items", [])
    total_amount = order.get("total_amount", 0)
    action = state.get("action_type", "cancel")

    action_verb = "cancel" if action == "cancel_order" else "return"
    action_noun = "Cancellation" if action == "cancel_order" else "Return Request"

    # Filter for active items that can still be cancelled or returned
    active_items = [it for it in all_items if it.get("item_status") not in ("Cancelled", "Returned")]
    if not active_items:
        active_items = all_items

    # -------------------------------------------------------------
    # CASE 1: Single item in the order
    # -------------------------------------------------------------
    if len(active_items) <= 1:
        item = active_items[0] if active_items else {
            "product_name": "Order Items", "quantity": 1, "unit_price": total_amount, "order_item_id": None
        }
        item_name = item.get("product_name", "Item")
        max_qty = item.get("quantity", 1)
        unit_price = item.get("unit_price", total_amount)

        action_done = "cancelled" if action == "cancel_order" else "returned"

        refund_note = (
            f"A refund of ₹{total_amount} has been initiated."
            if action == "cancel_order"
            else f"Our courier will pick up the package within 24–48 hours. A refund of ₹{total_amount} will be processed after inspection."
        )

        # Subcase 1A: Quantity is exactly 1 -> Direct yes/no prompt
        if max_qty <= 1:
            prompt = (
                f"📋 Order Summary for {action_noun} (Order #{order_id}):\n\n"
                f"• Item: {item_name} (Qty: 1)\n"
                f"• Estimated Refund: ₹{total_amount}\n\n"
                f"Are you sure you want to {action_verb} this order?\n"
                f"• TYPE: 'yes' (or 1) to confirm\n"
                f"• TYPE: 'no' (or 2) to keep your order and return to the main menu"
            )
            reply = interrupt(prompt).strip().lower()
            if reply in ("y", "yes", "1", "confirm", "sure"):
                return {
                    "confirmed": True,
                    "context": {
                        "action_scope": "all",
                        "item_id": item.get("order_item_id"),
                        "item_name": item_name,
                        "quantity": 1,
                        "refund_amount": total_amount,
                    },
                    "messages": [AIMessage(content=f"✅ Successfully {action_done} Order #{order_id} ({item_name})! {refund_note}")],
                }
            return {
                "confirmed": False,
                "context": None,
                "messages": [AIMessage(content=f"No changes made to Order #{order_id}. Returning to main menu.")],
            }

        # Subcase 1B: Single line item, but Quantity > 1 (e.g. 3 T-shirts)
        qty_prompt = (
            f"📋 Order Summary for {action_noun} (Order #{order_id}):\n\n"
            f"• Item: {item_name}\n"
            f"• Ordered Quantity: {max_qty} (₹{unit_price} each | Total: ₹{total_amount})\n\n"
            f"How many would you like to {action_verb}?\n"
            f"• TYPE: Quantity number (1 to {max_qty})\n"
            f"• TYPE: 'all' to {action_verb} all {max_qty} items (₹{total_amount} refund)\n"
            f"• TYPE: 'no' to return to the main menu"
        )
        qty_reply = interrupt(qty_prompt).strip().lower()
        if qty_reply in ("n", "no", "back", "exit"):
            return {
                "confirmed": False,
                "context": None,
                "messages": [AIMessage(content=f"No changes made to Order #{order_id}. Returning to main menu.")],
            }

        if qty_reply in ("all", "entire"):
            target_qty = max_qty
            refund_calc = total_amount
            scope = "all"
        else:
            try:
                target_qty = int(qty_reply)
                if not (1 <= target_qty <= max_qty):
                    return {"confirmed": False, "context": None}
                refund_calc = target_qty * unit_price
                scope = "all" if target_qty == max_qty else "single"
            except ValueError:
                return {"confirmed": False, "context": None}

        # Final Confirmation
        confirm_reply = interrupt(
            f"Confirm {action_noun} for {target_qty}x {item_name} (Refund: ₹{refund_calc})?\n"
            f"• TYPE: 'yes' (or 1) to confirm\n"
            f"• TYPE: 'no' (or 2) to cancel and return to main menu"
        ).strip().lower()
        if confirm_reply in ("y", "yes", "1", "confirm", "sure"):
            note = (
                f"A refund of ₹{refund_calc} has been initiated."
                if action == "cancel"
                else f"Our courier will pick up within 24–48 hours. Refund of ₹{refund_calc} will follow inspection."
            )
            return {
                "confirmed": True,
                "context": {
                    "action_scope": scope,
                    "item_id": item.get("order_item_id"),
                    "item_name": item_name,
                    "quantity": target_qty,
                    "refund_amount": refund_calc,
                },
                "messages": [AIMessage(content=f"✅ Successfully {action_done} {target_qty}x {item_name} from Order #{order_id}! {note}")],
            }
        return {"confirmed": False, "context": None}

    # -------------------------------------------------------------
    # CASE 2: Multiple items in the order
    # -------------------------------------------------------------
    item_lines = "\n".join(
        f"[{idx + 1}] {it['product_name']} (Qty: {it['quantity']}, ₹{it['unit_price'] * it['quantity']})"
        for idx, it in enumerate(active_items)
    )
    selection_prompt = (
        f"📋 Items in Order #{order_id}:\n\n"
        f"{item_lines}\n\n"
        f"What would you like to {action_verb}?\n"
        f"• TYPE: Item number (e.g. 1 or 2) to select a specific item\n"
        f"• TYPE: 'all' to {action_verb} the ENTIRE order (Total Refund: ₹{total_amount})\n"
        f"• TYPE: 'no' to return to the main menu"
    )
    reply = interrupt(selection_prompt).strip().lower()

    if reply in ("n", "no", "exit", "back"):
        return {
            "confirmed": False,
            "context": None,
            "messages": [AIMessage(content=f"No changes made to Order #{order_id}. Returning to main menu.")],
        }

    action_done = "cancelled" if action == "cancel_order" else "returned"

    # If user wants to cancel/return the ENTIRE order:
    if reply in ("all", "entire"):
        final_confirm = interrupt(
            f"Are you sure you want to {action_verb} ALL items in Order #{order_id} for a full refund of ₹{total_amount}?\n"
            f"• TYPE: 'yes' (or 1) to confirm\n"
            f"• TYPE: 'no' (or 2) to return to main menu"
        ).strip().lower()
        if final_confirm in ("y", "yes", "1", "confirm", "sure"):
            note = (
                f"A full refund of ₹{total_amount} has been initiated."
                if action == "cancel"
                else f"Courier pickup arranged within 24–48 hours. Full refund of ₹{total_amount} will follow."
            )
            return {
                "confirmed": True,
                "context": {
                    "action_scope": "all",
                    "item_id": None,
                    "item_name": "All Items",
                    "quantity": sum(it.get("quantity", 1) for it in active_items),
                    "refund_amount": total_amount,
                },
                "messages": [AIMessage(content=f"✅ Successfully {action_done} Order #{order_id} (All Items)! {note}")],
            }
        return {"confirmed": False, "context": None}

    # If user selected a specific item by index:
    try:
        item_index = int(reply) - 1
        if not (0 <= item_index < len(active_items)):
            return {"confirmed": False, "context": None}
        chosen_item = active_items[item_index]
    except ValueError:
        return {"confirmed": False, "context": None}

    item_name = chosen_item["product_name"]
    max_qty = chosen_item.get("quantity", 1)
    unit_price = chosen_item.get("unit_price", 0)

    # If the chosen item has quantity > 1, ask how many units to cancel/return
    if max_qty > 1:
        qty_sub_prompt = (
            f"You selected: {item_name} (Ordered: {max_qty}, ₹{unit_price} each)\n\n"
            f"How many would you like to {action_verb}?\n"
            f"• TYPE: Quantity (1 to {max_qty})\n"
            f"• TYPE: 'all' to {action_verb} all {max_qty}\n"
            f"• TYPE: 'no' to cancel"
        )
        sub_qty_reply = interrupt(qty_sub_prompt).strip().lower()
        if sub_qty_reply in ("n", "no", "back", "exit"):
            return {"confirmed": False, "context": None}

        if sub_qty_reply in ("all", "entire"):
            target_qty = max_qty
        else:
            try:
                target_qty = int(sub_qty_reply)
                if not (1 <= target_qty <= max_qty):
                    return {"confirmed": False, "context": None}
            except ValueError:
                return {"confirmed": False, "context": None}
    else:
        target_qty = 1

    refund_calc = target_qty * unit_price

    # Final Step: Explicit Yes/No confirmation
    final_prompt = (
        f"Confirm {action_noun} Summary:\n"
        f"• Item: {target_qty}x {item_name}\n"
        f"• Estimated Refund: ₹{refund_calc}\n\n"
        f"Proceed with this {action_verb}?\n"
        f"• TYPE: 'yes' (or 1) to confirm\n"
        f"• TYPE: 'no' (or 2) to cancel and return to main menu"
    )
    final_reply = interrupt(final_prompt).strip().lower()
    if final_reply in ("y", "yes", "1", "confirm", "sure", "proceed"):
        note = (
            f"A refund of ₹{refund_calc} has been initiated."
            if action == "cancel_order"
            else f"Our courier will pick up within 24–48 hours. Refund of ₹{refund_calc} will follow."
        )
        return {
            "confirmed": True,
            "context": {
                "action_scope": "single",
                "item_id": chosen_item.get("order_item_id"),
                "item_name": item_name,
                "quantity": target_qty,
                "refund_amount": refund_calc,
            },
            "messages": [AIMessage(content=f"✅ Successfully {action_done} {target_qty}x {item_name} from Order #{order_id}! {note}")],
        }

    return {
        "confirmed": False,
        "context": None,
        "messages": [AIMessage(content=f"No changes made to Order #{order_id}. Returning to main menu.")],
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
    reply = interrupt(
        f"❌ Policy Notice:\n{msg}\n\n"
        "How would you like to proceed?\n"
        "TYPE: 1 -> Raise a support ticket / Talk to an agent\n"
        "TYPE: 2 -> Return to Main Menu\n"
        "(Or simply type your question/complaint)"
    ).strip()


    # --- 3. Step A: Fast Shortcuts (Zero Cost) ---
    cleaned = reply.lower()
    if cleaned in ("1", "ticket", "human", "agent", "escalate"):
        decision = "ticket"
    elif cleaned in ("2", "menu", "main menu", "back", "exit", "no"):
        decision = "menu"

    # --- 4. Step B: LLM Fallback (Ambiguous / Natural Text) ---
    else:
        try:
            ai_choice: BlockedOptionClassifier = blocked_classifier_llm.invoke(
                f"The customer's request was rejected with message: '{msg}'.\n"
                f"Customer typed: '{reply}'.\n"
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
        "⚠️ We couldn't locate that order after 3 attempts.\n\n"
        "How would you like to proceed?\n"
        "• TYPE: 1 -> Try entering Order ID again\n"
        "• TYPE: 2 -> Return to the main menu\n"
        "• TYPE: 3 -> Raise a support ticket (our team will reach out within 24 hours)\n"
        "(Or type your message directly)"
    )
    reply = interrupt(prompt).strip()

    # Step A: Fast Shortcuts (0ms, Zero Cost)
    cleaned = reply.lower()
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

