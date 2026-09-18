from typing import  Optional

from langgraph.graph import END

from customer_support_ai_agent.state import CustomerState

from customer_support_ai_agent.policy_rules import check_order_eligibility


# HELPER FUNCTIONS
def _base_route(state: CustomerState) -> Optional[str]:
    action = state.get("action_type")
    if target := _check_global_route(action):
        return target
    if not action:
        return "start_node"
    return None


def _check_global_route(action: Optional[str]) -> Optional[str]:
    """
    Handles universal graph exits and escalations.
    """
    if action == "exit":
        return END
    if action == "human_support":
        return "human_escalate_node"
    return None

# GRAPH ROUTERS

def route_open_router(state: CustomerState) -> str:
    """
    Routes from open_router_node (the conversational front door).
    """
    action = state.get("action_type")
    target = _check_global_route(action)
    
    if target:
        return target

    if action in ("cancel_order", "return_order"):
        return "order_lookup_node"
    
    return "start_node"


def route_order_lookup(state: CustomerState) -> str:
    """Routes after order_lookup_node."""
    action = state.get("action_type")
    if route := _base_route(state):
        return route

    # loop back to the order if not get
    order = state.get("customer_details")
    if not order:
        return "order_lookup_node"

    if check_order_eligibility(order, action) is None:
        return "select_items_node"
    else:
        return "policy_blocked_node"
        

def route_select_items(state: CustomerState) -> str:
    """Routes after select_items_node."""
    if route := _base_route(state):
        return route


    if state.get("context") and state.get("context", {}).get("items"):
        return "confirm_action_node"
    return "select_items_node"



def route_confirm_action(state: CustomerState) -> str:
    """Routes after confirm_action_node."""
    action = state.get("action_type")
    if route := _base_route(state):
        return route

    if state.get("confirmed") is True:
        if action == "cancel_order":
            return "cancel_order_node"
        elif action == "return_order":
            return "return_order_node"
        else:
            return "start_node"

    # Stay on confirmation if transaction is still pending (e.g. FAQ was answered)
    if (
        action in ("cancel_order", "return_order")
        and state.get("context")
        and state.get("confirmed") is None
    ):
        return "confirm_action_node"

    return "start_node"


def route_blocked_choice(state: CustomerState) -> str:
    """Routes from policy_blocked_node (Ticket or Main Menu)."""
    return _base_route(state) or "start_node"
