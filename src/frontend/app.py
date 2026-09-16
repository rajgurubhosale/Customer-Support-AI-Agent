"""Streamlit page for the customer-support chat."""

import sys
from pathlib import Path
from typing import Any
import uuid

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import requests
import streamlit as st

from frontend.api import chat_with_backend, get_orders
from frontend.components import render_quick_options, render_stepper_card


st.set_page_config(
    page_title="Customer Support AI Agent",
    page_icon="🤖",
    layout="centered",
)
st.title("🤖 Customer Support AI Agent")


# Session state 
st.session_state.setdefault("user_id", 29)
st.session_state.setdefault("messages", [])
st.session_state.setdefault("options", [])
st.session_state.setdefault("ui_data", None)

# is session completed, (used for restart session)
st.session_state.setdefault("is_completed", False)

# new session start
st.session_state.setdefault(
    "thread_id",
    f"user-{st.session_state.user_id}-{uuid.uuid4().hex[:6]}",
)

#  #######################################################################
# REMOVE THIS LATER BEFORE PUSHING CODE AFTER TESTING ON MY MACHINE
# ALSO REMOVE THE CODE FROM TE 147 LINE TO RUN THIS FUNCTION
# HEY THIS IS BEINF USED FUNCTION FOR THE RESET SEESSION SO JUST REMOVE THE CODE
#  FROM 147 line and not this function
#  #######################################################################

def reset_conversation() -> None:
    """Clear the chat and start a new LangGraph thread."""
    st.session_state.messages = []
    st.session_state.options = []
    st.session_state.ui_data = None
    st.session_state.is_completed = False
    st.session_state.thread_id = (
        f"user-{st.session_state.user_id}-{uuid.uuid4().hex[:6]}"
    )


def handle_backend_response(data: dict) -> None:
    """
    Handles the response came from the backend and 
    Update chat history, quick options, UI widgets,
    and session status from the backend response.
    """

    is_completed = data.get("status") == "completed"

    # Append intermediate graph node notices to chat history so Streamlit renders them on the UI.
    messages = data.get("messages") or []
    for message in messages:
        st.session_state.messages.append({"role": "assistant", "content": message})
    
    # Add AI response to chat (skip duplicate goodbye if node already sent one)
    if data.get("ai_response") and not (is_completed and messages):
        st.session_state.messages.append({
            "role": "assistant",
            "content": data["ai_response"],
        })


    st.session_state.options = data.get("options") or []

    st.session_state.ui_data = data.get("ui_data")
    st.session_state.is_completed = is_completed


def submit(backend_payload: Any, button_label: str | None = None) -> None:
    """
    Handles user actions (chat text, quick buttons, or card selections):
    - Appends user's selection to chat history.
    - Sends payload to FastAPI while showing a loading spinner.
    - Updates messages, options, and UI cards from backend response.
    - Reruns Streamlit to refresh the UI.
    """
    # A completed LangGraph thread cannot resume, so continue on a fresh thread.
    if st.session_state.is_completed:
        st.session_state.thread_id = (
            f"user-{st.session_state.user_id}-{uuid.uuid4().hex[:6]}"
        )
        st.session_state.is_completed = False

    # Show the button text if clicked, otherwise show the typed text
    chat_bubble_text = button_label or str(backend_payload)

    st.session_state.messages.append({
        "role": "user",
        "content": chat_bubble_text,
    })

    previous_options = st.session_state.options
    previous_ui_data = st.session_state.ui_data

    try:
        with st.spinner("AI Agent is processing..."):
            data = chat_with_backend(
                st.session_state.user_id,
                st.session_state.thread_id,
                backend_payload,
            )
        handle_backend_response(data)
    except requests.RequestException as error:
        st.session_state.options = previous_options
        st.session_state.ui_data = previous_ui_data
        st.error(f"Error communicating with backend: {error}")
        return
    st.rerun()



# Sidebar 

st.sidebar.header("User Settings")
user_id = st.sidebar.number_input(
    "Customer ID",
    min_value=1,
    value=st.session_state.user_id,
    step=1,
)

if user_id != st.session_state.user_id:
    st.session_state.user_id = user_id
    reset_conversation()
    st.rerun()



if st.sidebar.button("🔄 Reset Conversation", width="stretch"):
    reset_conversation()
    st.rerun()

with st.sidebar.expander("📖 Return & Cancellation Policy"):
    st.markdown("""
    - **Cancellation**: Eligible while in *Placed* or *Processing* status.
    - **Returns**: Eligible within **7 days** of delivery.
    - **Refunds**: Processed back to original payment method in 3–5 business days.
    """)

with st.sidebar.expander("🎥 Demo Walkthrough"):
    st.markdown("[Watch Demo Walkthrough](https://example.com/demo)")

st.sidebar.subheader("Your Orders")
try:
    orders = get_orders(st.session_state.user_id)
    if orders:
        for order in orders:
            st.sidebar.markdown(
                f"- **ORD-{order['order_id']}** "
                f"({order['status']}, ₹{order['total_amount']})"
            )
    else:
        st.sidebar.markdown("No orders found.")
except requests.RequestException:
    st.sidebar.warning("Backend offline. Start FastAPI on port 8000.")

# MAIN CONVERSATION CODE

# Start new conversation if empty
if not st.session_state.messages:
    try:
        handle_backend_response(
            chat_with_backend(
                st.session_state.user_id,
                st.session_state.thread_id,
            )
        )
    except requests.RequestException as error:
        st.error(f"Could not connect to backend: {error}")

# Show messages 
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


if st.session_state.is_completed:
    if st.button("➕ Start New Conversation", type="primary"):
        reset_conversation()
        st.rerun()


#  Show buttons or the item selector 

ui_data = st.session_state.ui_data
key_suffix = len(st.session_state.messages)

if ui_data and ui_data.get("type") == "item_quantity_selection":
    render_stepper_card(ui_data, submit, key_suffix)
elif st.session_state.options:
    render_quick_options(st.session_state.options, submit, key_suffix)


#Send normal text to the backend 

user_text = st.chat_input("Type your message...")

if user_text:
    submit(user_text)
