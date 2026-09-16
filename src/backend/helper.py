from typing import Any, Optional
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver
from customer_support_ai_agent.graph import graph
from customer_support_ai_agent.schemas import normalize_user_input


checkpointer = MemorySaver()
agent = graph.compile(checkpointer=checkpointer)


def run_graph(graph_input, config):
    """
    Run LangGraph until it finishes or pauses at an interrupt.
    """
    messages = []
    interrupt_prompt  = None

    for event in agent.stream(graph_input, config=config, stream_mode="updates"):
        for node_output in event.values():
            if isinstance(node_output, dict):
                for message in node_output.get("messages", []):
                    messages.append(message.content)


        if "__interrupt__" in event:
            interrupt_prompt = event["__interrupt__"][0].value

    return interrupt_prompt, messages


def execute_agent_turn(user_id: int,user_message: Optional[Any] = None,thread_id: Optional[str] = None):
    """
    Executes one interaction cycle with the customer support agent.
    1. New Chat: Initializes thread and runs to first msg
    2. Existing Chat: Resumes paused graph with user input, 
    or re-fetches pending prompt if input is empty.
    3. Unpacks text prompts, quick-reply options,
    and UI forms into an API response.

    """
   
    thread_id = thread_id or f"user-{user_id}"
    config = {"configurable": {"thread_id": thread_id}}
    
    # Check whether conversation already exists
    state = agent.get_state(config)
    is_new_chat = False
    if not state.values:
        is_new_chat = True

    all_messages = []

    if is_new_chat:

        initial_state = {"user_id": user_id}
        interrupt_prompt , messages = run_graph(initial_state, config)
        all_messages.extend(messages)

    # Existing conversation
    else:
        is_empty = not user_message or (isinstance(user_message, str) and not user_message.strip())
        if is_empty:

            if (state.tasks and state.tasks[0].interrupts):
                interrupt_prompt = state.tasks[0].interrupts[0].value 
            else:            
                interrupt_prompt =  None

        else:
            # continue graph
            normalized = normalize_user_input(user_message)
            interrupt_prompt , messages = run_graph(Command(resume=normalized), config)
            all_messages.extend(messages)

    current_state = agent.get_state(config).values or {}

    # Unpack prompt, clickable options, UI data if interrupt returned a dict
    options = []
    ui_data = None

    if isinstance(interrupt_prompt , dict):

        ai_response = interrupt_prompt.get("prompt") or interrupt_prompt.get("message") or ""
        options = interrupt_prompt.get("options", [])

        # Load UI data when its type is present
        if interrupt_prompt.get("type"):
            ui_data = interrupt_prompt 

    elif interrupt_prompt:
        ai_response = str(interrupt_prompt)
    else:
        ai_response = "Session ended. Thank you for reaching out! 👋"

    return {
        "thread_id": thread_id,
        "user_id": user_id,
        "status": "waiting_for_input" if interrupt_prompt  else "completed",
        "ai_response": ai_response,
        "messages": all_messages,
        "current_action": current_state.get("action_type"),
        "order_id": 
        (
            str(current_state["order_id"])
            if current_state.get("order_id")
            else None
        ),
        "options": options,
        "ui_data": ui_data,
    }
