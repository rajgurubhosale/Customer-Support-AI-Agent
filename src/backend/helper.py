from typing import Any, Optional
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver
from customer_support_ai_agent.graph import graph
from customer_support_ai_agent.schemas import normalize_user_input

# 1. Compile agent ONCE here inside helper
checkpointer = MemorySaver()
agent = graph.compile(checkpointer=checkpointer)


def run_graph(graph_input, config):
    """
    Run LangGraph until it finishes or pauses at an interrupt.
    """
    messages = []
    question = None

    for event in agent.stream(graph_input, config=config, stream_mode="updates"):
        # Normal node outputs
        for node_output in event.values():
            if isinstance(node_output, dict):
                for message in node_output.get("messages", []):
                    messages.append(message.content)

        # Graph paused (interrupted) and is waiting for user input
        if "__interrupt__" in event:
            question = event["__interrupt__"][0].value

    return question, messages


def execute_agent_turn(
    user_id: int,
    user_message: Optional[Any] = None,
    thread_id: Optional[str] = None,
):
    thread_id = thread_id or f"user-{user_id}"
    config = {"configurable": {"thread_id": thread_id}}
    
    # Check whether conversation already exists
    state = agent.get_state(config)
    is_new_chat = not state.values
    all_messages = []

    # --------------------------------
    # New conversation
    # --------------------------------
    if is_new_chat:
        initial_state = {"user_id": user_id, "session_id": f"sess-{user_id}"}
        question, messages = run_graph(initial_state, config)
        all_messages.extend(messages)

        # User already sent a message with first request
        if user_message is not None and (not isinstance(user_message, str) or user_message.strip()) and question:
            normalized = normalize_user_input(user_message)
            question, messages = run_graph(Command(resume=normalized), config)
            all_messages.extend(messages)

    # --------------------------------
    # Existing conversation
    # --------------------------------
    else:
        if user_message is None or (isinstance(user_message, str) and not user_message.strip()):
            # User sent no message (e.g. page refresh) -> return current interrupt question without resuming
            question = state.tasks[0].interrupts[0].value if (state.tasks and state.tasks[0].interrupts) else None
        else:
            normalized = normalize_user_input(user_message)
            question, messages = run_graph(Command(resume=normalized), config)
            all_messages.extend(messages)

    # Get latest graph state
    current_state = agent.get_state(config).values or {}

    # Unpack prompt, clickable options, and rich UI data if interrupt returned a dict
    options = []
    ui_data = None
    if isinstance(question, dict):
        ai_response = question.get("prompt") or question.get("message") or ""
        options = question.get("options", [])
        if question.get("type"):
            ui_data = question
    elif question:
        ai_response = str(question)
    else:
        ai_response = "Session ended. Thank you for reaching out! 👋"

    return {
        "thread_id": thread_id,
        "user_id": user_id,
        "status": "waiting_for_input" if question else "completed",
        "ai_response": ai_response,
        "messages": all_messages,
        "current_action": current_state.get("action_type"),
        "order_id": (
            str(current_state["order_id"])
            if current_state.get("order_id")
            else None
        ),
        "options": options,
        "ui_data": ui_data,
    }
