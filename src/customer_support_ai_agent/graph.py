from langgraph.graph import START, END, StateGraph
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

import os
from customer_support_ai_agent.nodes import (
    start,
    return_cancel_flow_ask,
    return_node,
    ask_for_order_id_cancel,
    ask_for_confirmation_node,
    cancel_order_node,
    human_escalate_node,
    guided_return_options_node,
    cancel_blocked_node,
    retry_exhausted_node
)
from customer_support_ai_agent.routes import (
    route_menu,
    route_return_or_cancel,
    route_order_lookup_cancel,
    route_cancel_order,
    route_retry_exhausted,
    route_guided_options
)
from customer_support_ai_agent.state import CustomerState

#The Fundamental Rule in LangGraph Multi-Turn Graphs
#Every node that asks the user a question MUST route to END.

graph = StateGraph(CustomerState)

graph.add_node("start_node", start)
graph.add_edge(START, "start_node")

graph.add_node("return_cancel_flow_node", return_cancel_flow_ask)

graph.add_node("return_node", return_node)

# CANCEL FLOW NODES
graph.add_node("ask_for_order_id_cancel", ask_for_order_id_cancel)
graph.add_node("ask_for_confirmation_node", ask_for_confirmation_node)
graph.add_node("cancel_order_node", cancel_order_node)

graph.add_node("retry_exhausted_node", retry_exhausted_node)

# EMPTY NODESS:
graph.add_node("human_escalate_node", human_escalate_node)
graph.add_node("guided_return_options_node", guided_return_options_node)
graph.add_node("cancel_blocked_node", cancel_blocked_node)

graph.add_edge("human_escalate_node", END)
graph.add_edge("cancel_blocked_node", END)
#graph.add_edge("guided_return_options_node", END)




graph.add_conditional_edges(
    "start_node",
    route_menu,
    {   
        # guide how to use it # returns small video of 2 min
        #"reset_state": "reset_state",
        #"general_inquiry": "general_inquiry",
        "return_cancel_flow": "return_cancel_flow_node",
        #"product_enquiry": "product_enquiry",
        "human_escalate": "human_escalate_node",
        "start":"start_node"
    },
)

graph.add_conditional_edges(
    "return_cancel_flow_node",
    route_return_or_cancel,
    {
        "return_order_node": "return_node",
        "cancel_order_node": "ask_for_order_id_cancel",  
        "start": "start_node",
        "retry": "return_cancel_flow_node",
    }
)

##################################################
# CANCEL WORKFLOW
graph.add_conditional_edges("ask_for_order_id_cancel", route_order_lookup_cancel, {
    "retry_exhausted": "retry_exhausted_node",
    "retry": "ask_for_order_id_cancel",
    "ask_for_confirmation_node": "ask_for_confirmation_node",
    "guided_return_options_node": "guided_return_options_node",
    "cancel_blocked_node": "cancel_blocked_node",
})

from customer_support_ai_agent.routes import route_cancel_blocked


graph.add_conditional_edges("guided_return_options_node",
    route_guided_options,{
        "human_escalate": "human_escalate_node",
        "start": "start_node",
    }
)

graph.add_conditional_edges("cancel_blocked_node", route_cancel_blocked, {
    "human_escalate": "human_escalate_node",
    "start": "start_node",
})

graph.add_conditional_edges("retry_exhausted_node", route_retry_exhausted, {
    "human_escalate": "human_escalate_node",
    "start": "start_node",
})

graph.add_conditional_edges(
    "ask_for_confirmation_node",
    route_cancel_order,
    {
        "cancel_order": "cancel_order_node",
        "start": "start_node",
    }
)
#########################################
# ask for confirmation node
# if yes : cancel and update
# if no then END go to main menu with clear the requires input that has been fileeed in state for confirmation




graph.add_edge("cancel_order_node", "start_node")
graph.add_edge("return_node", END)

# imports 
from customer_support_ai_agent.prompts import INITIAL_GREETING
from langgraph.types import Command

def main():
    config = {"configurable": {"thread_id": "user-123"}}

    if os.getenv("LANGGRAPH_API_VARIANT"):
        app = graph.compile()
    else:
        checkpointer = MemorySaver()
        app = graph.compile(checkpointer=checkpointer)

    # First call — starts the graph, runs until it hits the first interrupt()
    result = app.invoke(
        {"user_id": 29, "session_id": "session-123"},
        config=config,
    )

    while True:
        # Show any message the last node left behind (e.g. "you chose not to cancel")
        messages = result.get("messages", [])
        if messages:
            print("\nAI:", messages[-1].content)

        if "__interrupt__" not in result:
            print("\nSession ended.")
            break

        question = result["__interrupt__"][-1].value
        print("\nAI:", question)

        try:
            user_input = input("You: ").strip()
            if user_input.lower() in ("exit", "quit", "bye"):
                print("\nSession ended. Goodbye!")
                break
            if not user_input:
                continue
        except KeyboardInterrupt:
            print("\nSession ended. Goodbye!")
            return

        result = app.invoke(Command(resume=user_input), config=config)

if __name__ == "__main__":
    main()