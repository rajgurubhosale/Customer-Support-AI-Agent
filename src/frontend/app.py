import streamlit as st
import requests
import uuid
from typing import Any


# ============================================================
# 1. PAGE SETUP
# ============================================================

st.set_page_config(
    page_title="Customer Support AI Agent",
    page_icon="💬",
    layout="centered"
)

st.title("💬 Customer Support AI Agent")

# Custom styling for quick option buttons (compact pill style)
st.markdown(
    """
    <style>
    div.stButton > button {
        border-radius: 20px;
        min-height: 32px;
        height: auto;
        padding: 4px 14px;
        font-weight: 500;
        font-size: 0.85rem;
        border: 1px solid rgba(128, 128, 128, 0.3);
        transition: all 0.15s ease-in-out;
    }
    div.stButton > button:hover {
        border-color: #ff4b4b;
        color: #ff4b4b;
        background-color: rgba(255, 75, 75, 0.05);
        transform: translateY(-1px);
    }
    div.stButton > button[kind="primary"] {
        background-color: #ff4b4b;
        color: white;
        border-color: #ff4b4b;
        border-radius: 8px;
        min-height: 40px;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: #e03b3b;
        color: white;
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

if "ui_data" not in st.session_state:
    st.session_state.ui_data = None

if "thread_id" not in st.session_state:
    st.session_state.thread_id = (
        f"user-{st.session_state.user_id}-{uuid.uuid4().hex[:6]}"
    )




# ============================================================
# 3. BACKEND API FUNCTIONS
# ============================================================
# These functions are only responsible for communicating
# with FastAPI. They don't contain UI logic.

def chat_with_backend(message: Any = None) -> dict:
    '''
    Send text or structured JSON payload to the backend and return the agent response.
    '''
    payload = {
        "user_id": st.session_state.user_id,
        "thread_id": st.session_state.thread_id,
        "message": message.strip() if isinstance(message, str) else message,
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
    st.session_state.ui_data = None

    st.rerun()


# Reset the current conversation.
if st.sidebar.button(
    "🔄 Reset Conversation",
    use_container_width=True
):

    st.session_state.messages = []
    st.session_state.options = []
    st.session_state.ui_data = None

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
    payload: Any,
    display_label: str | None = None
):

    # What the user sees in the chat history
    if display_label:
        display_text = display_label
    elif isinstance(payload, dict):
        if payload.get("action") in ("back", "cancel"):
            display_text = "🔙 Go Back"
        elif payload.get("confirmed") is True:
            display_text = "✅ Confirmed"
        elif payload.get("items"):
            item_descs = [f"{it.get('quantity')}x Item #{it.get('item_id')}" for it in payload["items"]]
            display_text = f"Selected for processing: {', '.join(item_descs)}"
        elif payload.get("selected_order_id"):
            display_text = f"Selected Order #ORD-{payload['selected_order_id']}"
        else:
            display_text = str(payload)
    else:
        display_text = str(payload)

    st.session_state.messages.append({
        "role": "user",
        "content": display_text,
    })

    # Clear previous options and ui_data
    st.session_state.options = []
    st.session_state.ui_data = None

    try:

        with st.spinner("AI Agent is processing..."):

            # Send payload to FastAPI
            data = chat_with_backend(payload)

        # Save intermediate messages
        for notice in data.get("messages", []):

            st.session_state.messages.append({
                "role": "assistant",
                "content": f"✅ {notice}",
            })

        # Save main AI response
        ai_reply = data.get("ai_response", "")
        if ai_reply:
            st.session_state.messages.append({
                "role": "assistant",
                "content": ai_reply,
            })

        # Save structured interactive data and options
        st.session_state.options = data.get("options") or []
        st.session_state.ui_data = data.get("ui_data")

    except requests.RequestException as e:

        st.error(f"Error communicating with backend: {e}")

    # Rerun the app so the new messages/options appear.
    st.rerun()





# ============================================================
# 8. START THE CONVERSATION
# ============================================================
# When the chat history is empty, this is the first request
# sent to the backend.

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
        st.session_state.ui_data = data.get("ui_data")

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
# 10. REUSABLE STRUCTURED INTERACTION RENDERER
# ============================================================
# Generic renderer for backend interaction directives:
#   - type == "item_quantity_selection" -> interactive order card with + / - steppers
#   - options provided -> clean responsive 2x2 buttons
# ============================================================

ui_data = st.session_state.ui_data

if ui_data and ui_data.get("type") == "item_quantity_selection":
    order_id = ui_data.get("order_id", "")
    items = ui_data.get("items", [])
    action_verb = ui_data.get("action_verb", "cancel")
    action_noun = ui_data.get("action_noun", "Cancellation")
    status = ui_data.get("status", "")
    order_date = ui_data.get("order_date", "")
    order_total = ui_data.get("order_total", 0.0)

    with st.container(border=True):
        st.markdown(f"#### 📦 Order #ORD-{order_id} Details")
        st.caption(f"Status: `{status}`  |  Order Date: `{order_date}`  |  Order Total: `₹{order_total:.2f}`")
        st.markdown("---")

        cols_hdr = st.columns([4, 2, 3])
        cols_hdr[0].markdown("**Item**")
        cols_hdr[1].markdown("**Ordered**")
        cols_hdr[2].markdown(f"**{action_verb.title()} Qty**")

        selected_items = []
        total_refund_estimate = 0.0

        for it in items:
            it_id = it["item_id"]
            it_name = it["name"]
            max_qty = int(it.get("quantity", 1))
            unit_price = float(it.get("unit_price", 0))

            cols_row = st.columns([4, 2, 3])
            cols_row[0].markdown(f"**{it_name}**  \n<small style='color:gray;'>₹{unit_price:.2f} each</small>", unsafe_allow_html=True)
            cols_row[1].markdown(f"`{max_qty}`")

            qty = cols_row[2].number_input(
                label=f"Quantity for {it_name}",
                min_value=0,
                max_value=max_qty,
                value=0,
                step=1,
                key=f"stepper_{it_id}_{len(st.session_state.messages)}",
                label_visibility="collapsed"
            )

            if qty > 0:
                subtotal = qty * unit_price
                total_refund_estimate += subtotal
                selected_items.append({
                    "item_id": it_id,
                    "name": it_name,
                    "quantity": qty,
                    "subtotal": subtotal,
                })

        st.markdown("---")

        # Review Summary Banner
        if selected_items:
            summary_desc = ", ".join([f"{s['quantity']}× {s['name']}" for s in selected_items])
            st.info(f"📋 **Selected for {action_noun}:** {summary_desc}\n\n💰 **Estimated Refund:** ₹{total_refund_estimate:.2f}")
        else:
            st.caption("ℹ️ Adjust quantities above using `+` and `-` to select items.")

        btn_col1, btn_col2 = st.columns(2)
        confirm_disabled = (len(selected_items) == 0)

        if btn_col1.button(
            f"✅ Confirm {action_noun}",
            type="primary",
            disabled=confirm_disabled,
            use_container_width=True,
            key=f"confirm_btn_{len(st.session_state.messages)}"
        ):
            clean_payload_items = [{"item_id": s["item_id"], "quantity": s["quantity"]} for s in selected_items]
            handle_user_submission(
                {"action": action_verb, "items": clean_payload_items},
                display_label=f"Confirm {action_noun} ({len(selected_items)} items)"
            )

        if btn_col2.button(
            "🔙 Back to Main Menu",
            use_container_width=True,
            key=f"back_btn_{len(st.session_state.messages)}"
        ):
            handle_user_submission(
                {"action": "back"},
                display_label="🔙 Back to Main Menu"
            )

elif st.session_state.options:

    # Indent quick options from the left to shift slightly right
    _, opt_col = st.columns([0.7, 9.3])

    with opt_col:
        st.caption("Quick Options:")

        num_opts = len(st.session_state.options)
        if num_opts == 1:
            cols = st.columns([2, 3])
            opt = st.session_state.options[0]
            label = opt.get("label", str(opt)) if isinstance(opt, dict) else str(opt)
            val = opt.get("value", str(opt)) if isinstance(opt, dict) else str(opt)
            if cols[0].button(label, key=f"option_0_{len(st.session_state.messages)}", use_container_width=True):
                handle_user_submission(val, display_label=label)
        else:
            cols_per_row = 2 if num_opts > 2 else num_opts
            for row_start in range(0, num_opts, cols_per_row):
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