"""Streamlit page for the customer-support chat."""

import sys
import uuid
from pathlib import Path
from typing import Any

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import requests
import streamlit as st

from frontend.api import chat_with_backend, get_case, get_cases, get_orders
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
st.session_state.setdefault("is_completed", False)
st.session_state.setdefault("selected_case_id", None)

st.session_state.setdefault(
    "thread_id",
    f"user-{st.session_state.user_id}-{uuid.uuid4().hex[:6]}",
)


def reset_conversation() -> None:
    """Clear the chat and start a new LangGraph thread."""
    st.session_state.messages = []
    st.session_state.options = []
    st.session_state.ui_data = None
    st.session_state.is_completed = False
    st.session_state.selected_case_id = None
    st.session_state.thread_id = (
        f"user-{st.session_state.user_id}-{uuid.uuid4().hex[:6]}"
    )


def handle_backend_response(data: dict) -> None:
    """Update chat history, quick options, UI widgets, and session status."""
    is_completed = data.get("status") == "completed"

    messages = data.get("messages") or []
    for message in messages:
        st.session_state.messages.append({"role": "assistant", "content": message})

    if data.get("ai_response") and not (is_completed and messages):
        st.session_state.messages.append({
            "role": "assistant",
            "content": data["ai_response"],
        })

    st.session_state.options = data.get("options") or []
    st.session_state.ui_data = data.get("ui_data")
    st.session_state.is_completed = is_completed


def submit(backend_payload: Any, button_label: str | None = None) -> None:
    """Handle customer actions (text, quick options, stepper submission)."""
    if st.session_state.is_completed:
        st.session_state.thread_id = (
            f"user-{st.session_state.user_id}-{uuid.uuid4().hex[:6]}"
        )
        st.session_state.is_completed = False

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
    except requests.Timeout:
        st.session_state.options = []
        st.session_state.ui_data = None
        st.session_state.is_completed = True
        st.error(
            "The reply timed out and may still be processing. Check case status "
            "before submitting again; your next message will start a new conversation."
        )
        return
    except requests.RequestException as error:
        st.session_state.options = previous_options
        st.session_state.ui_data = previous_ui_data
        st.error(f"Error communicating with backend: {error}")
        return
    st.rerun()


# -----------------------------------------------------------------------------
# Case Details Component (Shown on main page when a case is selected)
# -----------------------------------------------------------------------------
def _format_case_status(status: str | None) -> None:
    val = (status or "unknown").lower()
    color_map = {
        "open": "orange",
        "in_progress": "blue",
        "resolved": "green",
        "escalated": "red",
    }
    color = color_map.get(val, "gray")
    label = (status or "unknown").replace("_", " ").title()
    st.badge(label, color=color)


def _format_case_priority(priority: str | None) -> None:
    val = (priority or "medium").lower()
    if val == "high":
        st.badge("High Priority", color="red")
    elif val == "medium":
        st.badge("Medium Priority", color="yellow")
    else:
        st.badge("Low Priority", color="gray")


def render_case_details_page(case_id: int) -> None:
    """Render a dedicated, UX-friendly case dossier on the main page."""
    try:
        case = get_case(st.session_state.user_id, case_id)
    except requests.RequestException as err:
        st.error(f"Could not load case details: {err}")
        if st.button("← Back to Chat"):
            st.session_state.selected_case_id = None
            st.rerun()
        return

    # Top Navigation Row: Back button
    top_nav, _ = st.columns([2, 5], vertical_alignment="center")
    with top_nav:
        if st.button("← Back to Chat", type="primary", width="stretch", icon=":material/arrow_back:"):
            st.session_state.selected_case_id = None
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # Dossier Header Card
    with st.container(border=True):
        st.caption("SUPPORT CASE DOSSIER")
        head_l, head_m, head_r = st.columns([3, 1, 1], vertical_alignment="center")
        with head_l:
            st.subheader(f"CASE-{case['case_id']}")
        with head_m:
            _format_case_status(case.get("status"))
        with head_r:
            _format_case_priority(case.get("priority"))

        meta1, meta2, meta3 = st.columns(3)
        meta1.caption(f"**Customer ID:** #{case.get("customer_id")}")
        meta2.caption(f"**Created:** {str(case.get("created_at") or "")[:16].replace("T", " ")}")
        res_src = "🤖 AI Assistant" if case.get("resolution_source") == "assistant" else (
            "👤 Support Specialist" if case.get("resolution_source") == "admin" else "Under Review"
        )
        meta3.caption(f"**Handled by:** {res_src}")

        st.markdown(f"### {case.get("summary") or "Support Case"}")

        if case.get("raw_message"):
            st.info(f"💬 **Your Inquiry / Message:**\n\n\"{case['raw_message']}\"")

    # Reported Issues List
    st.markdown("#### 🔍 Reported Issues")
    issues = case.get("issues") or []
    if not issues:
        st.info("No specific issues attached to this case.")
    else:
        for issue in issues:
            with st.container(border=True):
                i_head, i_badge = st.columns([4, 1], vertical_alignment="center")
                with i_head:
                    issue_title = str(issue.get("issue_type") or "Issue").replace("_", " ").title()
                    st.markdown(f"**Issue #{issue['issue_id']} — {issue_title}**")
                with i_badge:
                    _format_case_status(issue.get("status"))

                st.write(issue.get("description") or "No description provided.")

                # Context details
                chips = []
                if issue.get("order_id"):
                    chips.append(f"📦 Order: ORD-{issue['order_id']}")
                if issue.get("product_name"):
                    chips.append(f"Item: {issue['product_name']}")
                if issue.get("item_quantity"):
                    chips.append(f"Qty: {issue['item_quantity']}")
                if issue.get("unit_price"):
                    try:
                        chips.append(f"Price: ₹{float(issue['unit_price']):,.2f}")
                    except (ValueError, TypeError):
                        chips.append(f"Price: ₹{issue['unit_price']}")
                if issue.get("order_status"):
                    chips.append(f"Order Status: {str(issue['order_status']).replace('_', ' ').title()}")
                if issue.get("expected_delivery_date"):
                    chips.append(f"Est Delivery: {str(issue['expected_delivery_date'])[:10]}")

                if chips:
                    st.caption("  ·  ".join(chips))

                # Extra reported details (JSON)
                details = issue.get("details")
                if details and isinstance(details, dict):
                    with st.expander("Reported Details", expanded=False):
                        for k, v in details.items():
                            st.markdown(f"- **{str(k).replace('_', ' ').title()}:** `{v}`")

                # Resolution outcome
                if issue.get("status") == "resolved":
                    res_note = issue.get("resolution_summary") or "Issue has been resolved."
                    st.success(f"✅ **Resolution Outcome:** {res_note}")
                else:
                    st.info("🕒 **Status:** Our support team is actively reviewing this issue. Updates will appear here.")

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("💬 Return to Chatbot Conversation", width="stretch"):
        st.session_state.selected_case_id = None
        st.rerun()


# -----------------------------------------------------------------------------
# Sidebar: Settings, Navigation, Orders, and Cases
# -----------------------------------------------------------------------------
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

st.sidebar.subheader("Your Cases")
if st.session_state.selected_case_id is not None:
    if st.sidebar.button("💬 Back to Active Chat", type="primary", width="stretch"):
        st.session_state.selected_case_id = None
        st.rerun()

try:
    cases = get_cases(st.session_state.user_id)
    if not cases:
        st.sidebar.caption("No support cases yet.")
    for case in cases:
        case_id = case["case_id"]
        is_active = (case_id == st.session_state.selected_case_id)
        btn_label = f"👉 CASE-{case_id} (Viewing)" if is_active else f"CASE-{case_id} · {case['status'].replace('_', ' ').title()}"
        btn_type = "primary" if is_active else "secondary"
        if st.sidebar.button(
            btn_label,
            key=f"case_{st.session_state.user_id}_{case_id}",
            type=btn_type,
            width="stretch",
        ):
            st.session_state.selected_case_id = case_id
            st.rerun()
        updated = str(case.get("updated_at") or "")[:16]
        st.sidebar.caption(f"{case['summary']} · Updated {updated}" if updated else case["summary"])
except requests.RequestException:
    st.sidebar.warning("Could not load your cases.")


# -----------------------------------------------------------------------------
# Main Content Area: Case Dossier OR Chatbot Conversation
# -----------------------------------------------------------------------------
if st.session_state.selected_case_id is not None:
    render_case_details_page(st.session_state.selected_case_id)
else:
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

    # Show buttons or item selector
    ui_data = st.session_state.ui_data
    key_suffix = len(st.session_state.messages)

    if ui_data and ui_data.get("type") == "item_quantity_selection":
        render_stepper_card(ui_data, submit, key_suffix)
    elif st.session_state.options:
        render_quick_options(st.session_state.options, submit, key_suffix)

    # Chat input
    user_text = st.chat_input("Type your message...")
    if user_text:
        submit(user_text)
