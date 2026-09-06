import streamlit as st
import requests
import uuid


# UI Configuration
st.set_page_config(
    page_title="Customer Support AI Agent",
    page_icon="💬"
)

st.title("💬 Customer Support AI Agent")

BACKEND_URL = "http://127.0.0.1:8000"

# Session State
# markdown IT PROPER LOGIC LATER THE ACCESSS LOGIC LIKE LOGIN AND SignUp AND THING LIKE TH T 

if "user_id" not in st.session_state:
    st.session_state.user_id = 29

if "messages" not in st.session_state:
    st.session_state.messages = []
    

if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"user-{st.session_state.user_id}-{uuid.uuid4().hex[:6]}"


# -----------------------------
# API Helpers
# -----------------------------


def chat_with_backend(message: str | None = None) -> dict:
    """
    Send a message to the backend, or initialize a new chat session when message is None.
    """
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
        timeout=3
    )

    response.raise_for_status()

    return response.json().get("orders", [])


# -----------------------------
# Sidebar
# -----------------------------

st.sidebar.header("User Settings")

new_user_id = st.sidebar.number_input(
    "Customer ID",
    min_value=1,
    value=st.session_state.user_id,
    step=1
)

# If user changes customer
if new_user_id != st.session_state.user_id:
    st.session_state.user_id = new_user_id
    st.session_state.thread_id = f"user-{new_user_id}-{uuid.uuid4().hex[:6]}"
    st.session_state.messages = []
    st.rerun()


if st.sidebar.button("🔄 Reset Conversation"):
    st.session_state.messages = []
    st.session_state.thread_id = (
        f"user-{st.session_state.user_id}-{uuid.uuid4().hex[:6]}"
    )
    st.rerun()


# -----------------------------
# Orders
# -----------------------------

st.sidebar.subheader("Your Orders")
# In st.sidebar:
with st.sidebar.expander("📖 Return & Cancellation Policy"):
    st.markdown("""
    - **Cancellation**: Only eligible while in *Placed* or *Processing* status.
    - **Returns**: Eligible within **7 days** of delivery.
    - **Refunds**: Processed back to original payment method in 3-5 days.
    """)

with st.sidebar.expander("🎥 Demo Walkthrough"):
    st.markdown("[Watch Demo Walkthrough](https://example.com/demo)")

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


# -----------------------------
# Initial Greeting
# -----------------------------

if not st.session_state.messages:

    try:
        data = chat_with_backend()

        st.session_state.messages.append({
            "role": "assistant",
            "content": data["ai_response"]
        })

    except requests.RequestException as e:
        st.error(f"Could not connect to backend: {e}")


# -----------------------------
# Display Chat History
# -----------------------------

for message in st.session_state.messages:

    with st.chat_message(message["role"]):
        st.markdown(message["content"])


# -----------------------------
# User Input
# -----------------------------

user_text = st.chat_input(
    "Type your message..."
)

if user_text:

    # Show user message
    st.session_state.messages.append({
        "role": "user",
        "content": user_text
    })

    with st.chat_message("user"):
        st.markdown(user_text)

    # Call backend
    try:

        data = chat_with_backend(user_text)

        # Intermediate messages
        for notice in data.get("messages", []):

            assistant_message = f"✅ {notice}"

            st.session_state.messages.append({
                "role": "assistant",
                "content": assistant_message
            })

            with st.chat_message("assistant"):
                st.markdown(assistant_message)

        # Main response
        ai_reply = data["ai_response"]

        st.session_state.messages.append({
            "role": "assistant",
            "content": ai_reply
        })

        with st.chat_message("assistant"):
            st.markdown(ai_reply)

    except requests.RequestException as e:

        st.error(
            f"Error communicating with backend: {e}"
        )