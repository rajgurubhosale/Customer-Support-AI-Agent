
from asyncio import coroutines
from langchain_core.messages import AIMessage
from langgraph.types import interrupt
from customer_support_ai_agent.state import CustomerState
from customer_support_ai_agent.prompts import INITIAL_GREETING

MAX_MENU_RETRIES = 3


#######################################################################

# MAIN NODES

#######################################################################

# put in separate class later

from pydantic import BaseModel, Field
from typing import Literal
from langchain_groq import ChatGroq
import os
from dotenv import load_dotenv
load_dotenv()
api_key = os.getenv("CHAT_GROQ")     

model = ChatGroq(
    model = "openai/gpt-oss-120b",
    api_key=api_key,
    temperature=0
)
# 1. Strict Schema: LLM is restricted ONLY to these 4 choices
class IntentClassifier(BaseModel):
    action_type: Literal["cancel", "return", "faq", "escalate"] = Field(
        description="The customer's primary goal."
    )

# ADD THE SYSTEM PROMPT LATER
structured_llm = model.with_structured_output(IntentClassifier)

######################################################################  

import re

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

    # Step A: Deterministic Regex for Order ID (Zero Hallucination)
    id_match = re.search(r'ord-?(\d+)', user_input)
    extracted_order_id = id_match.group(1) if id_match else None

    # Step B: Fast Shortcuts (Zero Cost)
    if user_input in ("1", "faq", "policy"):
        action_type = "faq"
    elif user_input in ("2", "cancel"):
        action_type = "cancel"
    elif user_input in ("3", "return"):
        action_type = "return"
    elif user_input in ("4", "ticket", "human", "agent"):
        action_type = "escalate"
    elif user_input in ("5", "demo", "video"):
        action_type = "demo"


    # Step C: Strict LLM Intent Classification (Only when shortcuts didn't match)
    else:
        ai_response: IntentClassifier = structured_llm.invoke(
            f"Classify the user intent for customer support: '{user_input}'"
        )
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

    # 1. Only prompt if we don't have an order_id yet
    if not order_id:
        if retries > 0:
            prompt = f"❌ We couldn't find that order. Please check and enter your Order ID (Attempt {retries + 1}/3):"
        else:
            prompt = "Please enter your Order ID (e.g. ORD-15):"

        user_input = interrupt(prompt).strip().upper()
        id_match = re.search(r'(\d+)', user_input)
        order_id = id_match.group(1) if id_match else user_input

    # 2. Query PostgreSQL (Only ONE place in the entire node!)
    order_details = get_order_with_items(order_id, customer_id=user_id)

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
    action_verb = "cancel" if action == "cancel" else "return"
    action_noun = "Cancellation" if action == "cancel" else "Return Request"

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

        action_done = "cancelled" if action == "cancel" else "returned"
        refund_note = (
            f"A refund of ₹{total_amount} has been initiated."
            if action == "cancel"
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

    action_done = "cancelled" if action == "cancel" else "returned"

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
            if action == "cancel"
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




############## TRANSFER LATER
from typing import Optional


class BlockedOptionClassifier(BaseModel):
    decision: Literal["ticket", "menu"] = Field(
        description="Classify if the customer wants to raise a support ticket / speak with an agent, or return to the main menu."
    )
    user_complaint: Optional[str] = Field(
        default=None,
        description="Brief summary of the customer's grievance or question for the support ticket."
    )

blocked_classifier_llm = model.with_structured_output(BlockedOptionClassifier)

def policy_blocked_node(state: CustomerState) -> dict:
    """Explains policy rejection and handles both numeric choices and natural complaints."""
    order = state["customer_details"]
    order_id = order.get("order_id", state.get("order_id"))
    status = order.get("status", "")
    action = state.get("action_type")
    delivery_date = order.get("delivery_date")

    # --- 1. Policy Explanation Messages ---
    if action == "cancel":
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
            msg = f"Order #{order_id} has already been cancelled. Your refund is in progress."
        else:
            msg = f"Order #{order_id} is currently '{status}' and cannot be cancelled."

    elif action == "return":
        if status == "Delivered" and delivery_date:
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
        elif status == "Returned":
            msg = f"A return for Order #{order_id} has already been initiated/completed."
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







####################################################################################################

# human platform should get to see the ticket thats should be implemented then handle this later

####################################################################################################



# using regex is great way ? here!!!!
# we can grab it from the chat string #id-24
# make changes in database




##################################################################################

# RETURN NODES

# the ask_for_order_id can be used both times
###################################################################################################


def start(state: CustomerState) -> dict:
    choice = interrupt(
        "Hi! What can I help you with today?\n please type options between(1,2,3)\n"
        "\nTYPE: 1 -> General chat (FAQ, policies, order status)\n"
        "TYPE: 2 -> Cancel or return an order\n"
        "TYPE: 3 -> Product enquiry"
    )
    return {
        "menu_choice": choice.strip().lower(),
        "order_id": None,
        "customer_details": None,
        "confirmed": None,
        "retry_count": 0,
        "return_cancel_choice": None,
        "retry_exhausted_choice": None,
        "guided_choice": None,
    }




def return_cancel_flow_ask(state: CustomerState) -> dict:
    choice = interrupt(
        "You want to return or cancel an order?\n"
        "TYPE: 1 -> return order\n"
        "TYPE: 2 -> cancel order\n"
        "TYPE: 3 -> back to main menu"
    )
    return {"return_cancel_choice": choice.strip().lower()}

from customer_support_ai_agent.db_functions import get_order_with_items


def ask_for_order_id_return(state: CustomerState) -> dict:
    """First node in the return chain — asks for order ID, validates it exists."""
    user_id = state["user_id"]
    retries = state.get("retry_count", 0)

    order_id = interrupt("Please enter your order ID:")
    order_id = order_id.strip().upper()
    
    order_details = get_order_with_items(int(order_id), customer_id=int(user_id))

    if order_details is None:
        return {
            "retry_count": retries + 1,
            "order_id": None,
            "customer_details": None,
        }

    else: 
        return {
            "retry_count": 0,
            "order_id": order_id,
            "customer_details": order_details,

        }


def ask_for_confirmation_return_node(state: CustomerState) -> dict:
    """Asks user to confirm return before executing."""
    order_details = state["customer_details"]
    total_amount = order_details.get("total_amount")
    refund_str = f"• Estimated Refund: ₹{total_amount}\n" if total_amount else ""

    item_names = []
    for item in order_details.get("items", []):
        item_names.append(f"{item['product_name']} (x{item['quantity']})")
    items_str = ", ".join(item_names) or "N/A"

    prompt_text = (
            f"You are about to request a return for Order #{state['order_id']}:\n\n"
            f"• Item(s): {items_str}\n"
            f"{refund_str}"
            "Are you sure you want to initiate this return? (yes/no)\n\n"
            
            "• TYPE: 'yes' to proceed with the return\n"
            "• TYPE: 'no' to keep your order and return to the main menu"
        )

    reply = interrupt(prompt_text)
    return_confirmed = reply.strip().lower() in ("y", "yes")

    if return_confirmed:
        return {"return_confirmed": True}

    return {
        "return_confirmed": False,
        "messages": [AIMessage(content=(
            f"You've chosen not to return order #{order_details['order_id']}. "
            "routing you back to the main menu."
        ))],
    }



def return_blocked_node(state: CustomerState) -> dict:
    order = state["customer_details"]
    order_id = order.get("order_id", state.get("order_id"))
    status = order.get("status", "")
    delivery_date = order.get("delivery_date")

    if status == "Delivered" and delivery_date:
        d_date = delivery_date.date() if isinstance(delivery_date, datetime) else delivery_date
        date_str = f" on {d_date.strftime('%Y-%m-%d')}"
        msg = (
            f"Order #{order_id} was delivered{date_str}, which is more than "
            f"{RETURN_WINDOW_DAYS} days ago. It's outside our return window so according to policy we cannot accept the return."
        )
    else:
        status_messages = {
            "Placed": (
                f"Order #{order_id} is still being processed and hasn't shipped yet! "
                "Because you haven't received it, it can't be returned, but you can cancel "
                "it immediately from the main menu cancel order for a full refund."
            ),
            #########################################################   
######################################################
            # what if its older order? and its alredy cancelled and the refund is alredy got to him? how to handle thi situration
            "Cancelled": (
                f"Order #{order_id} has already been cancelled, so no return is needed. "
                "Your refund is already being processed."
            ),
         #########################################################   
######################################################
            # if its arledy returend similar to upper one handle this later
            "Returned": (
                f"A return for Order #{order_id} has already been returned."
            ),
        }
        msg = status_messages.get(status, f"Order #{order_id} can't be returned right now.")

    reply = interrupt(
        f"{msg}\n\n"
        "TYPE: 1 -> Raise a support ticket\n"
        "TYPE: 2 -> Back to main menu"
    )

    return {
        "return_blocked_choice": reply.strip().lower(),
        "order_id": None,
        "customer_details": None,
    }

def out_for_delivery_node_return(state: CustomerState) -> dict:
    order = state["customer_details"]
    order_id = order.get("order_id", state.get("order_id"))
    status = order.get("status", "Shipped")

    choice = interrupt(
        f"Order #{order_id} is currently '{status}' and cannot be directly returned since it hasnt been delivered yet.\n"
        "once the order is delivered you can return the order within 7 days .\n\n"
        "TYPE: 1 -> Raise a support ticket\n"
        "TYPE: 2 -> Back to main menu"
        "TYPE: exit -> exit"
    )
    
    cleaned_choice = choice.strip().lower()

    # Dynamic, natural acknowledgement before routing to main menu
    if cleaned_choice in {"thanks", "thank you", "thx"}:
        msg = "You're very welcome! Routing you back to the main menu."

    elif cleaned_choice in {"ok", "okay", "got it", "understood", "sure", "k"}:
        msg = "Understood! Let us know if you need anything else. Returning to the main menu."
    
    elif cleaned_choice in {"2", "menu", "main menu", "back"}:
        msg = "got it ! routing you back to the main menu."

    elif cleaned_choice in {"1"}: 
        msg = "your raising a ticket !"

    updates = {"guided_choice": cleaned_choice}

    if msg:
        updates["messages"] = [AIMessage(content=msg)]
        
    return updates


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




    
# guided_return_options_node
# write u can cancell and something like that with menu

######################################################

 # CANCEL ORDER NODES

#####################################################


from customer_support_ai_agent.db_functions import get_order_with_items
def ask_for_order_id_cancel(state: CustomerState) -> dict:
    """Asks for order ID, displaying an error message if previous attempts failed."""
    user_id = state["user_id"]
    retries = state.get("retry_count", 0)

    # Show error prompt on retry, default prompt on first attempt
    if retries > 0:
        prompt = f"❌ We couldn't find that order. Please check and enter your Order ID again"
    else:
        prompt = "Please enter your order ID:"

    order_id = interrupt(prompt).strip().upper()
    order_details = get_order_with_items(order_id, customer_id=user_id)

    if order_details is None:
        return {
            "retry_count": retries + 1,
            "order_id": None,
            "customer_details": None,
        }

    return {
        "retry_count": 0,
        "order_id": order_id,
        "customer_details": order_details,
    }



def retry_exhausted_node(state: CustomerState) -> dict:
    """Runs after MAX_ORDER_RETRIES failed order lookups.
    Provides dual-mode resolution (shortcuts or LLM intent) to escalate or return to menu."""
    prompt = (
        "⚠️ We couldn't locate that order after 3 attempts.\n\n"
        "How would you like to proceed?\n"
        "• TYPE: 1 -> Raise a support ticket (our team will reach out within 24 hours)\n"
        "• TYPE: 2 -> Return to the main menu\n"
        "(Or type your message/question directly)"
    )
    reply = interrupt(prompt).strip()

    # Step A: Fast Shortcuts (0ms, Zero Cost)
    cleaned = reply.lower()
    if cleaned in ("1", "ticket", "human", "agent", "escalate", "help"):
        decision = "ticket"
    elif cleaned in ("2", "menu", "main menu", "back", "exit", "cancel", "retry", "again"):
        decision = "menu"
    # Step B: LLM Fallback for Natural / Ambiguous Language
    else:
        try:
            ai_choice: BlockedOptionClassifier = blocked_classifier_llm.invoke(
                f"The customer failed 3 attempts to find their order ID.\n"
                f"Customer response: '{reply}'.\n"
                "Classify whether the customer wants human support/ticket ('ticket') "
                "or wants to return to the main menu/exit ('menu')."
            )
            decision = ai_choice.decision
        except Exception:
            decision = "ticket"  # Safe default: when stuck, connect to human

    # Clean up state so next order lookup starts fresh
    return {
        "retry_exhausted_choice": decision,
        "retry_count": 0,
        "order_id": None,
        "customer_details": None,
    }





def ask_for_confirmation_cancel_node(state: CustomerState) -> dict:
    """Lets user select an item or entire order, then asks for a final yes/no confirmation."""
    order_details = state["customer_details"]
    items = order_details.get("items", [])
    total_amount = order_details.get("total_amount")

    # CASE 1: Only 1 item in the entire order -> Direct yes/no
    if len(items) <= 1:
        item_text = f"{items[0]['product_name']} (Qty: {items[0]['quantity']})" if items else "All items"
        prompt = (
            f"Order Summary for Cancellation:\n\n"
            f"• Order ID: #{order_details['order_id']}\n"
            f"• Item: {item_text}\n"
            f"• Refund Amount: ₹{total_amount}\n\n"
            "Are you sure you want to cancel this order? (yes/no)\n"
            "• TYPE: 'yes' to cancel\n"
            "• TYPE: 'no' to keep order and return to main menu"
        )
        reply = interrupt(prompt).strip().lower()
        if reply in ("y", "yes"):
            return {
                "cancel_confirmed": True,
                "context": {"cancel_scope": "all", "item_name": item_text, "refund": total_amount},
            }
        return {"cancel_confirmed": False}

    # CASE 2: Multiple items -> Step 1: Choose item or ALL
    item_lines = "\n".join(
        f"[{idx + 1}] {item['product_name']} (Qty: {item['quantity']}, ₹{item['unit_price'] * item['quantity']})"
        for idx, item in enumerate(items)
    )

    selection_prompt = (
        f"Order Summary for Cancellation:\n\n"
        f"• Order ID: #{order_details['order_id']}\n"
        f"• Current Status: {order_details['status']}\n\n"
        f"Items in this order:\n{item_lines}\n\n"
        "What would you like to cancel?\n"
        "• TYPE: Item number (e.g. 1 or 2) to cancel just that item\n"
        f"• TYPE: 'all' to cancel the ENTIRE order (₹{total_amount} refund)\n"
        "• TYPE: 'no' to keep order and return to main menu"
    )

    reply = interrupt(selection_prompt).strip().lower()

    if reply in ("n", "no", "exit", "back"):
        return {"cancel_confirmed": False}

    # Determine what was selected
    if reply in ("all", "entire"):
        selected_info = {"cancel_scope": "all", "item_name": "All Items", "refund": total_amount}
    else:
        try:
            choice_idx = int(reply) - 1
            if 0 <= choice_idx < len(items):
                chosen = items[choice_idx]
                refund = chosen["unit_price"] * chosen["quantity"]
                selected_info = {
                    "cancel_scope": "single",
                    "order_item_id": chosen["order_item_id"],
                    "item_name": f"{chosen['product_name']} (Qty: {chosen['quantity']})",
                    "refund": refund,
                }
            else:
                return {"cancel_confirmed": False}
        except ValueError:
            return {"cancel_confirmed": False}

    # CASE 2 -> Step 2: Final yes/no confirmation showing chosen option
    confirmation_prompt = (
        f"You have selected to cancel:\n"
        f"• Item: {selected_info['item_name']}\n"
        f"• Refund Amount: ₹{selected_info['refund']}\n\n"
        "Are you sure you want to confirm this cancellation? (yes/no)\n"
        "• TYPE: 'yes' to cancel\n"
        "• TYPE: 'no' to keep order and return to main menu"
    )

    confirm_reply = interrupt(confirmation_prompt).strip().lower()

    if confirm_reply in ("y", "yes"):
        return {
            "cancel_confirmed": True,
            "context": selected_info,
        }

    return {"cancel_confirmed": False}
    
# check cancel can happen and all here only if its placed then show it can be cancelled or if its deliverd
# or something then show the return it something
# if else should be here only not route direcltu 

    
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



def out_for_delivery_node_cancel(state: CustomerState) -> dict:
    order = state["customer_details"]
    order_id = order.get("order_id", state.get("order_id"))
    status = order.get("status", "Shipped")

    choice = interrupt(
        f"Order #{order_id} is currently '{status}' and cannot be directly cancelled.\n"
        "You can refuse delivery at your doorstep for an auto-refund "
        "or return the package within 7 days of delivery.\n\n"
        "TYPE: 1 -> Raise a support ticket\n"
        "TYPE: 2 -> Back to main menu"
        "TYPE: exit -> exit"
    )
    
    cleaned_choice = choice.strip().lower()

    # Dynamic, natural acknowledgement before routing to main menu
    if cleaned_choice in {"thanks", "thank you", "thx"}:
        msg = "You're very welcome! Routing you back to the main menu."

    elif cleaned_choice in {"ok", "okay", "got it", "understood", "sure", "k"}:
        msg = "Understood! Let us know if you need anything else. Returning to the main menu."
    
    elif cleaned_choice in {"2", "menu", "main menu", "back"}:
        msg = "got it ! routing you back to the main menu."

    else:
        # If they selected option 1 (ticket), no menu message needed
        msg = "your raising a ticket !"
    ####################
    # WRITE BETTER VARIABLE NAME
    ##################
    updates = {"guided_choice": cleaned_choice}

    if msg:
        updates["messages"] = [AIMessage(content=msg)]
        
    return updates


from datetime import datetime, date
RETURN_WINDOW_DAYS = 7


def cancel_blocked_node(state: CustomerState) -> dict:
    """Handles orders that cannot be cancelled — already Delivered,
    Cancelled, or Returned. Offers a ticket or main menu."""
    order = state["customer_details"]
    order_id = order.get("order_id", state.get("order_id"))
    status = order.get("status", "")
    delivery_date = order.get("delivery_date")

    if status == "Delivered" and delivery_date:
        d_date = delivery_date.date() if isinstance(delivery_date, datetime) else delivery_date
        days_since = (date.today() - d_date).days
        date_str = f" on {d_date.strftime('%Y-%m-%d')}"

        if days_since > RETURN_WINDOW_DAYS:
            msg = (
                f"Order #{order_id} was delivered{date_str} (over {RETURN_WINDOW_DAYS} days ago) "
                "and can no longer be cancelled or returned under our policy."
            )
        else:
            msg = (
                f"Order #{order_id} was already delivered{date_str}. "
                "Delivered orders can't be cancelled — choose 'Return order' from the main menu instead."
            )
    else:
        status_messages = {
            "Cancelled": f"Order #{order_id} has already been cancelled.",
            "Returned": f"Order #{order_id} has already been returned.",
        }
        msg = status_messages.get(
            status,
            f"Order #{order_id} with status '{status}' cannot be cancelled.",
        )

    reply = interrupt(
        f"{msg}\n\n"
        "TYPE: 1 -> Raise a support ticket\n"
        "TYPE: 2 -> Back to main menu"
    )

    return {
        "messages": [AIMessage(content=reply)],
        "cancel_blocked_choice": reply.strip().lower(),
        "order_id": None,
        "customer_details": None,
    }


