import streamlit as st
import requests
import uuid


# ============================================================
# 1. PAGE SETUP
# ============================================================

st.set_page_config(
    page_title="Customer Support AI Agent",
    page_icon="💬",
    layout="centered"
)

st.title("💬 Customer Support AI Agent")

# Custom styling for quick option buttons
st.markdown(
    """
    <style>
    div.stButton > button {
        border-radius: 8px;
        min-height: 48px;
        font-weight: 500;
        font-size: 0.95rem;
        transition: all 0.15s ease-in-out;
    }
    div.stButton > button:hover {
        border-color: #ff4b4b;
        transform: translateY(-1px);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

BACKEND_URL = "http://127.0.0.1:8000"


# ============================================================
# 2. SESSION STATE
# ============================================================
# Streamlit reruns this script whenever the user interacts
# with the UI, so we store important conversation data here.

if "user_id" not in st.session_state:
    st.session_state.user_id = 29

if "messages" not in st.session_state:
    st.session_state.messages = []

if "options" not in st.session_state:
    st.session_state.options = []

if "thread_id" not in st.session_state:
    st.session_state.thread_id = (
        f"user-{st.session_state.user_id}-{uuid.uuid4().hex[:6]}"
    )




# ============================================================
# 3. BACKEND API FUNCTIONS
# ============================================================
# These functions are only responsible for communicating
# with FastAPI. They don't contain UI logic.

def chat_with_backend(message: str | None = None) -> dict:
    '''
    send message to the backend and return the agent's response if message is given otherwise return the initial response

    '''
    payload = {
        "user_id": st.session_state.user_id,
        "thread_id": st.session_state.thread_id,
        "message": message.strip() if message else None,
    }

    response = requests.post(
        f"{BACKEND_URL}/chat",
        json=payload,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


def get_orders():

    response = requests.get(
        f"{BACKEND_URL}/orders/{st.session_state.user_id}",
        timeout=3,
    )

    response.raise_for_status()

    return response.json().get("orders", [])


# ============================================================
# 5. SIDEBAR — USER SETTINGS
# ============================================================

st.sidebar.header("User Settings")

new_user_id = st.sidebar.number_input(
    "Customer ID",
    min_value=1,
    value=st.session_state.user_id,
    step=1,
)


# If the customer changes, start a fresh conversation.
if new_user_id != st.session_state.user_id:

    st.session_state.user_id = new_user_id

    st.session_state.thread_id = (
        f"user-{new_user_id}-{uuid.uuid4().hex[:6]}"
    )

    st.session_state.messages = []
    st.session_state.options = []

    st.rerun()


# Reset the current conversation.
if st.sidebar.button(
    "🔄 Reset Conversation",
    use_container_width=True
):

    st.session_state.messages = []
    st.session_state.options = []

    st.session_state.thread_id = (
        f"user-{st.session_state.user_id}-{uuid.uuid4().hex[:6]}"
    )

    st.rerun()


# ============================================================
# 6. SIDEBAR — POLICY
# ============================================================

with st.sidebar.expander("📖 Return & Cancellation Policy"):

    st.markdown("""
    - **Cancellation**: Eligible while in *Placed* or *Processing* status.
    - **Returns**: Eligible within **7 days** of delivery.
    - **Refunds**: Processed back to original payment method in 3–5 business days.
    """)


with st.sidebar.expander("🎥 Demo Walkthrough"):

    st.markdown(
        "[Watch Demo Walkthrough](https://example.com/demo)"
    )


# ============================================================
# 7. SIDEBAR — CUSTOMER ORDERS
# ============================================================
# This is separate from the conversation.
# We simply fetch the customer's orders from FastAPI
# and display them in the sidebar.

st.sidebar.subheader("Your Orders")

try:

    orders = get_orders()

    if orders:

        for order in orders:

            st.sidebar.markdown(
                f"- **ORD-{order['order_id']}** "
                f"({order['status']}, ₹{order['total_amount']})"
            )

    else:

        st.sidebar.markdown("No orders found.")

except requests.RequestException:

    st.sidebar.warning(
        "Backend offline. Start FastAPI on port 8000."
    )






# ============================================================
# 4. HANDLE A USER ACTION
# ============================================================
# Both kinds of input eventually come here:
#
#   - User types something
#   - User clicks a quick-option button
#
# The flow is:
#
# User action
#      ↓
# Add it to chat history
#      ↓
# Send it to FastAPI
#      ↓
# Receive agent response
#      ↓
# Save response + options
#      ↓
# Rerun Streamlit to display everything
# ============================================================

def handle_user_submission(
    text: str,
    display_label: str | None = None
):

    # What the user sees in the chat.
    # For a button, we show the button label instead of
    # the internal value sent to the backend.
    display_text = display_label or text

    st.session_state.messages.append({
        "role": "user",
        "content": display_text,
    })

    # The previous options have now been used,
    # so remove them before processing the next turn.
    st.session_state.options = []

    try:

        with st.spinner("AI Agent is processing..."):

            # Send the user's answer to FastAPI.
            data = chat_with_backend(text)

        # Save any additional messages produced by the agent.
        for notice in data.get("messages", []):

            st.session_state.messages.append({
                "role": "assistant",
                "content": f"✅ {notice}",
            })

        # Save the agent's main response.
        ai_reply = data.get("ai_response", "")
        if ai_reply:
            st.session_state.messages.append({
                "role": "assistant",
                "content": ai_reply,
            })

        # If the backend provides choices, save them so the UI can turn them into buttons.
        st.session_state.options = data.get("options") or []

    except requests.RequestException as e:

        st.error(f"Error communicating with backend: {e}")

    # Rerun the app so the new messages/options appear.
    st.rerun()





# ============================================================
# 8. START THE CONVERSATION
# ============================================================
# When the chat history is empty, this is the first request
# sent to the backend.
#
# The backend gives us the initial agent response and,
# if applicable, some options for the user.

if not st.session_state.messages:

    try:

        data = chat_with_backend()

        ai_reply = data.get("ai_response", "")
        if ai_reply:
            st.session_state.messages.append({
                "role": "assistant",
                "content": ai_reply,
            })

        st.session_state.options = data.get("options") or []

    except requests.RequestException as e:

        st.error(f"Could not connect to backend: {e}")


# ============================================================
# 9. DISPLAY CHAT HISTORY
# ============================================================
# Everything stored in messages is rendered here.

for message in st.session_state.messages:

    with st.chat_message(message["role"]):

        st.markdown(message["content"])


# ============================================================
# 10. DISPLAY QUICK OPTIONS
# ============================================================
# The backend can send structured choices.
#
# Streamlit doesn't know what those choices mean.
# It simply turns each option into a clickable button.
#
# Clicking a button sends opt["value"] to the backend,
# while opt["label"] is what the user sees.
# ============================================================

if st.session_state.options:

    st.markdown("##### Quick Options:")

    cols_per_row = 2
    for row_start in range(0, len(st.session_state.options), cols_per_row):
        row_opts = st.session_state.options[row_start : row_start + cols_per_row]
        cols = st.columns(cols_per_row)
        for col_idx, option in enumerate(row_opts):
            label = option.get("label", str(option)) if isinstance(option, dict) else str(option)
            val = option.get("value", str(option)) if isinstance(option, dict) else str(option)
            overall_idx = row_start + col_idx

            if cols[col_idx].button(
                label,
                key=f"option_{overall_idx}_{len(st.session_state.messages)}",
                use_container_width=True,
            ):
                handle_user_submission(
                    val,
                    display_label=label,
                )


# NORMAL TEXT INPUT
# The user can also ignore the buttons and type their own
# response. It goes through the exact same handler.

user_text = st.chat_input("Type your message...")

if user_text:

    handle_user_submission(user_text)