
from langchain_core.messages import AIMessage
from langgraph.types import interrupt
from customer_support_ai_agent.state import CustomerState
from customer_support_ai_agent.prompts import INITIAL_GREETING

MAX_MENU_RETRIES = 3

#######################################################################

# MAIN NODES

#######################################################################
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



####################################################################################################

# human platform should get to see the ticket thats should be implemented then handle this later

####################################################################################################




# using regex is great way ? here!!!!
# we can grab it from the chat string #id-24
# make changes in database

def human_escalate_node(state: CustomerState) -> dict:

    # it should have the interrupt msg and the msg box that will tell the user
    # to write the input or msg for the human
    # or the email maybe for the human esacaltion if u wnat adding latency so 
    # this way only serioes people will write the email and get to us4
    return {"messages": [AIMessage(content="Human escalate — placeholder")]}





##################################################################################

# RETURN NODES

# the ask_for_order_id can be used both times
###################################################################################################


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

            "Cancelled": (
                f"Order #{order_id} has already been cancelled, so no return is needed. "
                "Your refund is already being processed."
            ),
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
    """After MAX_ORDER_RETRIES failed order ID attempts, ask the user
    whether to escalate to a human or go back to the main menu."""
    reply = interrupt(
        "We weren't able to locate that order after a few attempts.\n"
        "It seems like u may have mistyped order id (if u want to retry u can choose 2)"
        "\nTYPE: 1 -> Raise a support ticket — our team will reach out within 24 hours\n"
        "TYPE: 2 -> Return to the main menu"
    )
    return {"retry_exhausted_choice": reply.strip().lower()}


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


