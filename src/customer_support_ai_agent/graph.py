from langgraph.graph import START, END, StateGraph
from langgraph.checkpoint.memory import MemorySaver
import os
from customer_support_ai_agent.nodes import (
    entry_node,
    human_escalate_node,
    demo_node,
    order_lookup_node,
    policy_blocked_node,
    confirm_action_node,
    retry_exhausted_node,
)
from customer_support_ai_agent.routes import (
    route_menu,
    route_order_lookup,
    route_blocked_choice,
    route_retry_exhausted,
)
from customer_support_ai_agent.state import CustomerState
graph = StateGraph(CustomerState)

# 1. Register Active Nodes
graph.add_node("start_node", entry_node)
graph.add_node("demo_node", demo_node)
graph.add_node("order_lookup_node", order_lookup_node)
graph.add_node("policy_blocked_node", policy_blocked_node)
graph.add_node("confirm_action_node", confirm_action_node)
graph.add_node("retry_exhausted_node", retry_exhausted_node)
graph.add_node("human_escalate_node", human_escalate_node)

# 2. Register Simple Edges
graph.add_edge(START, "start_node")
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




graph.add_conditional_edges("policy_blocked_node",
route_blocked_choice,
    {
        "human_escalate": "human_escalate_node",
        "start": "start_node",
    },
)

graph.add_conditional_edges("retry_exhausted_node", 
route_retry_exhausted, {
    "human_escalate": "human_escalate_node",
    "start": "start_node",
})

# imports 
from langgraph.types import Command



def main():
    checkpointer = MemorySaver()
    app = graph.compile(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "user-123"}}


    # First call — starts the graph, runs until it hits the first interrupt()
    user_id = int(input("Enter your user_id: "))
    result = app.invoke(
        {"user_id": user_id, "session_id": "session-123"},
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