from langgraph.types import interrupt
from langgraph.graph import START, END, StateGraph
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

import os
from customer_support_ai_agent.nodes import (
    start,
    return_cancel_flow_ask,
    # CANCEL NODES
    ask_for_order_id_cancel,
    ask_for_confirmation_cancel_node,
    cancel_order_node,
    human_escalate_node,
    out_for_delivery_node_cancel,
    cancel_blocked_node,
    retry_exhausted_node,
    
    # RETTURN NODE
    return_order_node,
    return_blocked_node,
    ask_for_order_id_return,
    ask_for_confirmation_return_node,
    out_for_delivery_node_return,
    cancel_blocked_node,
    retry_exhausted_node
)
from customer_support_ai_agent.routes import (
    route_menu,
    route_return_or_cancel,
    route_order_lookup_cancel,
    route_cancel_order,
    route_retry_exhausted,
    route_guided_options,

    # RETURN ROUTEs
    route_order_lookup_return,
    route_return_order,

)
from customer_support_ai_agent.state import CustomerState

#The Fundamental Rule in LangGraph Multi-Turn Graphs
#Every node that asks the user a question MUST route to END.

graph = StateGraph(CustomerState)



graph.add_node("return_cancel_flow_node", return_cancel_flow_ask)

# CANCEL FLOW NODES
graph.add_node("ask_for_order_id_cancel", ask_for_order_id_cancel)
graph.add_node("ask_for_confirmation_cancel_node", ask_for_confirmation_cancel_node)
graph.add_node("cancel_order_node", cancel_order_node)
graph.add_node("out_for_delivery_node_cancel", out_for_delivery_node_cancel)
graph.add_node("cancel_blocked_node", cancel_blocked_node)

# RETURN NODES

graph.add_node("ask_for_confirmation_return_node", ask_for_confirmation_return_node)
graph.add_node("ask_for_order_id_return", ask_for_order_id_return)  
graph.add_node("out_for_delivery_node_return", out_for_delivery_node_return)
graph.add_node("return_blocked_node", return_blocked_node)  
graph.add_node("return_order_node", return_order_node)

# COMMON NODES
graph.add_node("retry_exhausted_node", retry_exhausted_node)

# EMPTY NODESS:
graph.add_node("human_escalate_node", human_escalate_node)

graph.add_edge("human_escalate_node", END)
#graph.add_edge("out_for_delivery_node_cancel", END)


# LATEST 
from customer_support_ai_agent.nodes import entry_node, order_lookup_node, demo_node
from customer_support_ai_agent.routes import route_order_lookup

graph.add_node("start_node", entry_node)
graph.add_edge(START, "start_node")

graph.add_node("order_lookup_node", order_lookup_node)
graph.add_node("demo_node", demo_node)
graph.add_edge("demo_node", "start_node")


graph.add_conditional_edges(
    "start_node",
    route_menu,
    {   
        "order_lookup": "order_lookup_node",
        "human_escalate": "human_escalate_node",
        "demo_node": "demo_node",
        "start": "start_node",
    },
)
from customer_support_ai_agent.nodes import confirm_action_node 

graph.add_node("confirm_action_node", confirm_action_node)

graph.add_conditional_edges(
    "order_lookup_node",
    route_order_lookup,
    {
        "retry": "order_lookup_node",
        "retry_exhausted": "retry_exhausted_node",
        "eligible": "confirm_action_node",
        "blocked": "policy_blocked_node",
    },
)

graph.add_edge("confirm_action_node", "start_node")

from customer_support_ai_agent.nodes import policy_blocked_node
from customer_support_ai_agent.routes import route_blocked_choice

graph.add_node("policy_blocked_node", policy_blocked_node)

graph.add_conditional_edges(
    "policy_blocked_node",
    route_blocked_choice,
    {
        "human_escalate": "human_escalate_node",
        "start": "start_node",
    },
)


graph.add_conditional_edges("retry_exhausted_node", route_retry_exhausted, {
    "human_escalate": "human_escalate_node",
    "start": "start_node",
})














graph.add_conditional_edges(
    "return_cancel_flow_node",
    route_return_or_cancel,
    {   
        "return_order": "ask_for_order_id_return",
        "cancel_order": "ask_for_order_id_cancel",  
        "start": "start_node",
        "retry": "return_cancel_flow_node",
    }
)

#####################################
# RETURN WORKFLOW
####################################

graph.add_conditional_edges("ask_for_order_id_return", route_order_lookup_return, {
    "retry_exhausted": "retry_exhausted_node", # pass to the same node as cancel for retry exhaust handles same work
    "retry": "ask_for_order_id_return",
    
    "ask_for_confirmation_return_node": "ask_for_confirmation_return_node",
    "out_for_delivery_node_return": "out_for_delivery_node_return",
    "return_blocked_node": "return_blocked_node",
})

# FINAL RETURN ORDER NODE
graph.add_conditional_edges(
    "ask_for_confirmation_return_node",
    route_return_order,
    {
        "return_order": "return_order_node",
        "start": "start_node",
    }
)

graph.add_conditional_edges("out_for_delivery_node_return",
    route_guided_options,{
        "human_escalate": "human_escalate_node",
        "start": "start_node",
    }
)
from customer_support_ai_agent.routes import route_return_blocked

graph.add_conditional_edges("return_blocked_node", route_return_blocked, {
    "human_escalate": "human_escalate_node",
    "start": "start_node",
})

##################################################
# CANCEL WORKFLOW
############################
graph.add_conditional_edges("ask_for_order_id_cancel", route_order_lookup_cancel, {
    "retry_exhausted": "retry_exhausted_node",
    "retry": "ask_for_order_id_cancel",
    "ask_for_confirmation_cancel_node": "ask_for_confirmation_cancel_node",
    "out_for_delivery_node_cancel": "out_for_delivery_node_cancel",
    "cancel_blocked_node": "cancel_blocked_node",
})

from customer_support_ai_agent.routes import route_cancel_blocked


graph.add_conditional_edges("out_for_delivery_node_cancel",
    route_guided_options,{
        "human_escalate": "human_escalate_node",
        "start": "start_node",
    }
)

graph.add_conditional_edges("cancel_blocked_node", route_cancel_blocked, {
    "human_escalate": "human_escalate_node",
    "start": "start_node",
})


graph.add_conditional_edges(
    "ask_for_confirmation_cancel_node",
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
graph.add_edge("return_order_node", "start_node")

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
    user_id = int(input("Enter your user_id: "))
    result = app.invoke(
        {"user_id": user_id, "session_id": "session-123"},
        config=config,
    )

    last_printed_count = 0
    while True:
        # Show any NEW message the last node left behind
        messages = result.get("messages", [])
        if len(messages) > last_printed_count:
            for m in messages[last_printed_count:]:
                print("\nAI:", m.content)
            last_printed_count = len(messages)

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