from langgraph.graph import START, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from customer_support_ai_agent.nodes import (
    start_node,
    order_lookup_node,
    select_items_node,
    confirm_action_node,
    cancel_order_node,
    return_order_node,
    policy_blocked_node,
    human_escalate_node,
)
from customer_support_ai_agent.routes import (
    route_open_router,
    route_order_lookup,
    route_select_items,
    route_confirm_action,
    route_blocked_choice,
)
from customer_support_ai_agent.state import CustomerState
from customer_support_ai_agent.schemas import UserInput

graph = StateGraph(CustomerState)

# REGISTER NODES

graph.add_node("start_node", start_node)
graph.add_node("order_lookup_node", order_lookup_node)
graph.add_node("select_items_node", select_items_node)
graph.add_node("confirm_action_node", confirm_action_node)
graph.add_node("cancel_order_node", cancel_order_node)
graph.add_node("return_order_node", return_order_node)
graph.add_node("policy_blocked_node", policy_blocked_node)
graph.add_node("human_escalate_node", human_escalate_node)


# EDGES
graph.add_edge(START, "start_node")
graph.add_edge("cancel_order_node", "start_node")
graph.add_edge("return_order_node", "start_node")
graph.add_edge("human_escalate_node", "start_node")

graph.add_conditional_edges("start_node", route_open_router)
graph.add_conditional_edges("order_lookup_node", route_order_lookup)
graph.add_conditional_edges("select_items_node", route_select_items)
graph.add_conditional_edges("confirm_action_node", route_confirm_action)
graph.add_conditional_edges("policy_blocked_node", route_blocked_choice)
