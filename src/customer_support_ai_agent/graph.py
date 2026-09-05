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
        "end": END,
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
        "start": "start_node",
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
    "retry": "order_lookup_node",
    "human_escalate": "human_escalate_node",
    "start": "start_node",
})

# imports 
from langgraph.types import Command


def main():
    checkpointer = MemorySaver()
    app = graph.compile(checkpointer=checkpointer)
    
    user_id = int(input("Enter your user_id: "))

    #thread_id = conversation identity
    config = {"configurable": {"thread_id": f"user-{user_id}"}}

    # First call: real starting state (not a Command yet)
    next_input = {"user_id": user_id, "session_id": "session-123"}

    while True:

        prompt_question =  None

        # first iteration: next_input = starting dict -> starts a NEW run
        # it runs till the end or interrupt
        for event in app.stream(next_input, config=config, stream_mode='updates'):

            # 1. Print any AI messages nodes left on the belt
            # this loops runs for yeild in genrator app.stream()
            for node_name, node_output in event.items():
                
                # event exmaple: {"confirm_action_node": {"confirmed": False, "messages": [...]}}
                if isinstance(node_output, dict) and "messages" in node_output:
                    for msg in node_output["messages"]:
                        print("\nAI:", msg.content)
                        

            # 2. Catch pause points (interrupts)
            # {"__interrupt__": (Interrupt(value="Are you sure? (yes/no)"),)}

            if "__interrupt__" in event:
                prompt_question = event["__interrupt__"][0].value
            
        

        # Graph reached the end without interrupting
        if not prompt_question:
            print("\nSession ended. Goodbye!")
            break

        # Display the prompt and wait for user input
        
        print("\nAI:", prompt_question)

        try:    

            user_reply = input("You: ").strip()        
            if user_reply.lower() in ("exit", "quit", "bye"):
                print("\nSession ended. Goodbye!")
                break
        
        except KeyboardInterrupt:
            print("\nSession ended. Goodbye!")
            break

        # Next loop iteration resumes the graph with the user's answer
        # "Don't start a new graph run. Instead, resume the paused thread 
        # (identified by config's thread_id), and make user_reply be the return value of
        #  whatever interrupt(...) call froze it."
        next_input = Command(resume=user_reply)


if __name__ == "__main__":
    main()