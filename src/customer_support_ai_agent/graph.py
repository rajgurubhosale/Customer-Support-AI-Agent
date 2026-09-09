from langgraph.graph import START, END, StateGraph
from langgraph.checkpoint.memory import MemorySaver
import os

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
graph = StateGraph(CustomerState)

# 1. Register Core Nodes
graph.add_node("start_node", start_node)
graph.add_node("order_lookup_node", order_lookup_node)
graph.add_node("select_items_node", select_items_node)
graph.add_node("confirm_action_node", confirm_action_node)
graph.add_node("cancel_order_node", cancel_order_node)
graph.add_node("return_order_node", return_order_node)
graph.add_node("policy_blocked_node", policy_blocked_node)
graph.add_node("human_escalate_node", human_escalate_node)

# 2. Simple Direct Edges
graph.add_edge(START, "start_node")
graph.add_edge("cancel_order_node", "start_node")
graph.add_edge("return_order_node", "start_node")
graph.add_edge("human_escalate_node", "start_node")

# 3. Dynamic Decision Routing
graph.add_conditional_edges("start_node", route_open_router)
graph.add_conditional_edges("order_lookup_node", route_order_lookup)
graph.add_conditional_edges("select_items_node", route_select_items)
graph.add_conditional_edges("confirm_action_node", route_confirm_action)
graph.add_conditional_edges("policy_blocked_node", route_blocked_choice)

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