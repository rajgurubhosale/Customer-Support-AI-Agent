from langgraph.graph import START, END, StateGraph

from customer_support_ai_agent.routes import (
    route_menu,
    route_return_or_cancel
    )

from customer_support_ai_agent.nodes import (
    start,
    return_cancel_flow_ask,
    cancel_node,
    return_node
    )
from customer_support_ai_agent.state import CustomerState


graph = StateGraph(CustomerState)


graph.add_node("start_node", start)
graph.set_entry_point("start_node")
graph.add_node("return_cancel_flow_node", return_cancel_flow_ask)

graph.add_node("return_node", return_node)
graph.add_node("cancel_node", cancel_node)

graph.add_conditional_edges(
    "start_node",
    route_menu,
    {
        #"reset_state": "reset_state",
        #"general_inquiry": "general_inquiry",
        "return_cancel_flow": "return_cancel_flow_node",
        #"product_enquiry": "product_enquiry",
        #"human_escalate": "human_escalate",
    },
)

graph.add_conditional_edges(
    "return_cancel_flow_node",
    route_return_or_cancel,
    {
        "return_order_node": "return_node",
        "cancel_order_node": "cancel_node",
        "start": "start_node",
        "retry": "return_cancel_flow_node",   # self-loop, but conditional
    }
)
graph.add_edge("return_node", END)
graph.add_edge("cancel_node", END)


# right now we are working on the return cancel flow
