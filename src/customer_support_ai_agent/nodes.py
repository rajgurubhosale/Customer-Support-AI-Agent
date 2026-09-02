
from langchain_core.messages import AIMessage
from langgraph.types import interrupt
from customer_support_ai_agent.state import CustomerState
from customer_support_ai_agent.prompts import INITIAL_GREETING

MAX_MENU_RETRIES = 3


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


def return_node(state: CustomerState) -> dict:
    return {"messages": [AIMessage(content="Return flow — placeholder")]}


def human_escalate_node(state: CustomerState) -> dict:

    # it should have the interrupt msg and the msg box that will tell the user
    # to write the input or msg for the human
    # or the email maybe for the human esacaltion if u wnat adding latency so 
    # this way only serioes people will write the email and get to us4
    return {"messages": [AIMessage(content="Human escalate — placeholder")]}



####################################################################################################

# human platform should get to see the ticket thats should be implemented then handle this later

####################################################################################################




# cancel node -> loop till MAX RETRIES
# ask for confirmation node if confirmed ? then reroute

# ask for order id ->loop 3 ?times escalate human
# conditional routing
# order id present -> check if its cancellabale if not then  askf for return or generate ticket  
# ask him or check if u have make a mistake in typing


# using regex is great way ? here!!!!
# we can grab it from the chat string
# make changes in database


######################################################

 # CANCEL ORDER NODES

#####################################################


from customer_support_ai_agent.db_functions import get_order

def ask_for_order_id_cancel(state: CustomerState) -> dict:
    """First node in the cancel chain — asks for order ID, validates it exists."""
    user_id = state["user_id"]
    retries = state.get("retry_count", 0)

    order_id = interrupt("Please enter your order ID:")
    order_details = get_order(order_id.strip().upper(), customer_id=user_id)

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


def ask_for_confirmation_node(state: CustomerState) -> dict:
    """Asks user to confirm cancellation before executing."""
    order = state["customer_details"]

    reply = interrupt(
        f"Confirm cancelling order #{order['order_id']}? (yes/no)\n"
        "yes → cancel the order\n"
        "no → back to main menu"
    )

    confirmed = reply.strip().lower() in ("y", "yes")

    if confirmed:
        return {"confirmed": True}

    return {
        "confirmed": False,
        "messages": [AIMessage(content=(
            f"You've chosen not to cancel order #{order['order_id']}. "
            "routing you back to the main menu."
        ))],
    }

    

def cancel_order_node(state: CustomerState) -> dict:
    print('ORDER CANCELLED')
    msg = f"""
            your order {state['order_id']} has been cancelled !
            redirecting u to main menu !!
        """
    return {"messages": [AIMessage(content=msg)]}
    # then cancel and show the msg of cancellations
    # and update in db user data



def guided_return_options_node(state: CustomerState) -> dict:
    order = state["customer_details"]
    order_id = order.get("order_id", state.get("order_id"))
    status = order.get("status", "Processing")

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


