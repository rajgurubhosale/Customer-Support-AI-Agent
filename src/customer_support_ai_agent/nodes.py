
# interrupt() is what makes the graph pause execution and wait for a human
from langgraph.types import interrupt

from langchain_core.messages import AIMessage
from customer_support_ai_agent.state import CustomerState


MAX_MENU_RETRIES = 3


def start(state: CustomerState) -> dict:
    """First node — shows the main menu and waits for the user's choice."""
    prefix = "Sorry, I didn't get that. " 

    choice = interrupt(
        f"{prefix}Hi! What can I help you with today?\n"
        "1. General chat (FAQ, policies, order status)\n"
        "2. Cancel or return an order\n"
        "3. Product enquiry\n"
    )

    return {
        "menu_choice": choice.strip().lower(),
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


def cancel_node(state: CustomerState) -> dict:
    return {"messages": [AIMessage(content="Cancel flow — placeholder")]}
