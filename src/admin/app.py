"""Admin Dashboard — Clean two-pane console for customer issues and cancellations/returns."""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from admin.db import (
    get_case,
    list_cases,
    list_order_actions,
    reopen_case,
    resolve_issue,
    start_review,
)


# -----------------------------------------------------------------------------
# Page Configuration & Clean Minimal Styling (No Sidebar)
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Support Admin Desk",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    /* Hide sidebar completely since all navigation is on-page */
    [data-testid="stSidebar"] {
        display: none;
    }
    [data-testid="collapsedControl"] {
        display: none;
    }
    
    /* Metrics clean border */
    div[data-testid="stMetric"] {
        background-color: rgba(128, 128, 128, 0.04);
        border: 1px solid rgba(128, 128, 128, 0.18);
        padding: 10px 14px;
        border-radius: 8px;
    }
    .badge-pill {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 6px;
        font-size: 0.82rem;
        font-weight: 500;
        margin-right: 6px;
        margin-bottom: 4px;
        background-color: rgba(128, 128, 128, 0.12);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Initialize selection state
if "selected_case_id" not in st.session_state:
    st.session_state.selected_case_id = None
if "selected_action_id" not in st.session_state:
    st.session_state.selected_action_id = None


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _label(value: Any) -> str:
    if not value:
        return "Unknown"
    return str(value).replace("_", " ").title()


def _format_currency(val: Any) -> str:
    if val is None:
        return "₹0.00"
    try:
        return f"₹{float(val):,.2f}"
    except (ValueError, TypeError):
        return f"₹{val}"


def _format_date(dt: Any) -> str:
    if not dt:
        return "—"
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M")
    return str(dt)[:16].replace("T", " ")


def _status_badge(status: str | None) -> None:
    val = (status or "unknown").lower()
    color_map = {
        "open": "orange",
        "in_progress": "blue",
        "resolved": "green",
        "escalated": "red",
        "completed": "green",
        "pending": "orange",
        "processing": "blue",
        "failed": "red",
        "initiated": "blue",
        "cancelled": "red",
        "partially_cancelled": "orange",
        "return_requested": "orange",
        "returned": "violet",
        "partially_returned": "violet",
    }
    color = color_map.get(val, "gray")
    st.badge(_label(val), color=color)


def _priority_badge(priority: str | None) -> None:
    val = (priority or "medium").lower()
    if val == "high":
        st.badge("High Priority", color="red")
    elif val == "medium":
        st.badge("Medium Priority", color="yellow")
    else:
        st.badge("Low Priority", color="gray")


# -----------------------------------------------------------------------------
# 1. Customer Issues & Cases Detail (Right Pane)
# -----------------------------------------------------------------------------
def _render_case_detail(case_id: int) -> None:
    try:
        case = get_case(case_id)
    except Exception as exc:
        st.error(f"Error loading case: {exc}")
        return

    if not case:
        st.info("Select a case on the left to view details.")
        return

    # Dossier Card
    with st.container(border=True):
        st.caption("CASE DOSSIER")
        head_l, head_m, head_r = st.columns([3, 1, 1], vertical_alignment="center")
        with head_l:
            st.subheader(f"CASE-{case['case_id']}")
        with head_m:
            _status_badge(case.get("status"))
        with head_r:
            _priority_badge(case.get("priority"))

        meta1, meta2, meta3 = st.columns(3)
        meta1.caption(f"**Customer:** #{case['customer_id']}")
        meta2.caption(f"**Created:** {_format_date(case.get('created_at'))}")
        res_src = "🤖 AI Assistant" if case.get("resolution_source") == "assistant" else (
            "👤 Admin Staff" if case.get("resolution_source") == "admin" else "Pending"
        )
        meta3.caption(f"**Resolved by:** {res_src}")

        st.markdown(f"**{case.get('summary') or 'Support Case'}**")
        st.info(case.get("raw_message") or "No customer message recorded.")

        # Lifecycle review button
        if case["status"] == "open":
            if st.button("▶️ Start Review", type="primary", key=f"start_rev_{case_id}"):
                try:
                    start_review(case_id)
                    st.rerun()
                except ValueError as err:
                    st.warning(str(err))
        elif case["status"] == "resolved" and case.get("resolution_source") == "assistant":
            if st.button("🔄 Reopen for Human Review", key=f"reopen_rev_{case_id}"):
                try:
                    reopen_case(case_id)
                    st.rerun()
                except ValueError as err:
                    st.warning(str(err))

    # Child Issues List
    issues = case.get("issues") or []
    st.markdown(f"##### Reported Issues ({len(issues)})")
    if not issues:
        st.caption("No child issues attached to this case.")
        return

    for issue in issues:
        with st.container(border=True):
            i_head, i_badge = st.columns([4, 1], vertical_alignment="center")
            with i_head:
                st.markdown(f"**Issue #{issue['issue_id']} — {_label(issue.get('issue_type'))}**")
            with i_badge:
                _status_badge(issue.get("status"))

            st.write(issue.get("description") or "No description recorded.")

            # Context Badges
            chips = []
            if issue.get("order_id"):
                chips.append(f"ORD-{issue['order_id']}")
            if issue.get("product_name"):
                chips.append(issue["product_name"])
            if issue.get("order_status"):
                chips.append(_label(issue["order_status"]))
            if issue.get("unit_price"):
                chips.append(_format_currency(issue["unit_price"]))
            if issue.get("expected_delivery_date"):
                chips.append(f"Est Delivery: {_format_date(issue['expected_delivery_date'])[:10]}")

            if chips:
                st.markdown(
                    "".join(f'<span class="badge-pill">{c}</span>' for c in chips),
                    unsafe_allow_html=True,
                )

            # Details
            details = issue.get("details")
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except ValueError:
                    details = {}
            if details and isinstance(details, dict):
                with st.expander("Reported Details", expanded=False):
                    for k, v in details.items():
                        st.markdown(f"- **{_label(k)}:** `{v}`")

            # Resolution box / form
            if issue.get("status") == "resolved":
                st.success(f"✅ **Resolution:** {issue.get('resolution_summary') or 'Marked resolved.'}")
            else:
                with st.form(f"resolve_form_{issue['issue_id']}"):
                    note = st.text_area(
                        "Resolution Note",
                        placeholder="Record what was verified and actions taken...",
                    )
                    submit = st.form_submit_button("Save Resolution", type="primary", width="stretch")
                    if submit:
                        if not note.strip():
                            st.warning("Please enter a resolution note before saving.")
                        else:
                            try:
                                resolve_issue(case_id, issue["issue_id"], note)
                                st.rerun()
                            except ValueError as err:
                                st.error(str(err))


# -----------------------------------------------------------------------------
# 1. Customer Issues & Cases Main View (Left List + Right Details)
# -----------------------------------------------------------------------------
def _issues_view() -> None:
    try:
        cases = list_cases()
    except Exception as exc:
        st.error(f"Could not load cases: {exc}")
        return

    # Top Metrics Row
    needs_review = [c for c in cases if c["status"] in ("open", "in_progress")]
    resolved_count = sum(c["status"] == "resolved" for c in cases)
    high_prio_count = sum(c.get("priority") == "high" and c["status"] != "resolved" for c in cases)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("All Cases", len(cases))
    m2.metric("Needs Review", len(needs_review))
    m3.metric("High Priority", high_prio_count)
    m4.metric("Resolved", resolved_count)

    st.markdown("---")

    # Filters Row
    f_col1, f_col2, f_col3 = st.columns([2, 1, 1])
    with f_col1:
        search = st.text_input(
            "Search Cases",
            placeholder="Search by Case ID, Customer, Order ID, or keyword...",
            label_visibility="collapsed",
        ).strip().lower()
    with f_col2:
        status_filter = st.selectbox(
            "Status Filter",
            ["Needs Review", "All Cases", "Open", "In Progress", "Resolved"],
            label_visibility="collapsed",
        )
    with f_col3:
        prio_filter = st.selectbox(
            "Priority Filter",
            ["All Priorities", "High", "Medium", "Low"],
            label_visibility="collapsed",
        )

    # Filtering
    filtered = cases
    if status_filter == "Needs Review":
        filtered = [c for c in filtered if c["status"] in ("open", "in_progress")]
    elif status_filter != "All Cases":
        filtered = [c for c in filtered if c["status"] == status_filter.lower().replace(" ", "_")]

    if prio_filter != "All Priorities":
        filtered = [c for c in filtered if c.get("priority") == prio_filter.lower()]

    if search:
        filtered = [
            c for c in filtered
            if any(
                search in str(c.get(f) or "").lower()
                for f in ("case_id", "customer_id", "order_refs", "summary", "status")
            )
        ]

    # Validate active selection
    active_ids = [c["case_id"] for c in filtered]
    if st.session_state.selected_case_id not in active_ids:
        st.session_state.selected_case_id = active_ids[0] if active_ids else None

    if not filtered:
        st.info("No customer issues match the current filters.")
        return

    # Two-Pane Layout: Left List, Right Detail
    col_left, col_right = st.columns([1, 1.3], gap="large")

    with col_left:
        st.markdown(f"**Cases Queue ({len(filtered)})**")
        with st.container(height=650):
            for c in filtered:
                cid = c["case_id"]
                is_selected = (cid == st.session_state.selected_case_id)

                with st.container(border=True):
                    card_head, card_st = st.columns([3, 1], vertical_alignment="center")
                    with card_head:
                        st.markdown(f"**CASE-{cid}**")
                    with card_st:
                        _status_badge(c.get("status"))

                    prio = c.get("priority", "medium")
                    prio_icon = "🔴" if prio == "high" else ("🟡" if prio == "medium" else "🔵")
                    orders = c.get("order_refs") or "No Order"
                    st.caption(f"{prio_icon} {_label(prio)}  ·  Cust #{c['customer_id']}  ·  {orders}")

                    summary = c.get("summary") or "Support case"
                    if len(summary) > 95:
                        summary = summary[:92] + "..."
                    st.write(summary)

                    btn_label = "Viewing Details 👉" if is_selected else "Inspect Case"
                    btn_type = "primary" if is_selected else "secondary"
                    if st.button(btn_label, key=f"btn_case_{cid}", type=btn_type, width="stretch"):
                        st.session_state.selected_case_id = cid
                        st.rerun()

    with col_right:
        if st.session_state.selected_case_id:
            _render_case_detail(st.session_state.selected_case_id)
        else:
            st.info("Click on any case from the list on the left to view its details.")


# -----------------------------------------------------------------------------
# 2. Cancellations & Returns Detail (Right Pane)
# -----------------------------------------------------------------------------
def _render_action_detail(action: dict) -> None:
    with st.container(border=True):
        st.caption("ACTION DETAILS")
        head_l, head_r = st.columns([3, 1], vertical_alignment="center")
        with head_l:
            st.subheader(f"Action #{action['action_id']}")
        with head_r:
            _status_badge(action.get("action_status"))

        meta1, meta2 = st.columns(2)
        meta1.markdown(f"**Order:** `ORD-{action['order_id']}`")
        meta1.markdown(f"**Customer:** `#{action['customer_id']}`")
        meta1.markdown(f"**Action Type:** `{_label(action['action_type'])}`")
        meta2.markdown(f"**Scope:** `{_label(action.get('scope'))}`")
        meta2.markdown(f"**Confirmed:** {_format_date(action.get('confirmed_at'))}")
        meta2.markdown(f"**Completed:** {_format_date(action.get('completed_at'))}")

        st.divider()

        m_ref1, m_ref2 = st.columns(2)
        with m_ref1:
            st.metric("Recorded Refund", _format_currency(action.get("refund_amount")))
        with m_ref2:
            st.write("**Refund Status:**")
            _status_badge(action.get("refund_status"))

    # Selected Items
    raw_items = action.get("selected_items") or []
    if isinstance(raw_items, str):
        try:
            raw_items = json.loads(raw_items)
        except ValueError:
            raw_items = []

    if raw_items:
        with st.container(border=True):
            st.markdown("##### 📦 Items Included in this Action")
            item_rows = [
                {
                    "Item ID": it.get("item_id") or it.get("source_item_id") or "—",
                    "Product": it.get("name") or it.get("product_name") or f"Item #{it.get('item_id', '')}",
                    "Quantity": it.get("quantity", 1),
                    "Unit Price": _format_currency(it.get("unit_price")),
                }
                for it in raw_items
            ]
            st.dataframe(item_rows, hide_index=True, width="stretch")


# -----------------------------------------------------------------------------
# 2. Cancellations & Returns Main View (Left List + Right Details)
# -----------------------------------------------------------------------------
def _actions_view() -> None:
    try:
        actions = list_order_actions()
    except Exception as exc:
        st.error(f"Could not load order actions: {exc}")
        return

    total_actions = len(actions)
    cancels = sum(a["action_type"] == "cancel_order" for a in actions)
    returns = sum(a["action_type"] == "return_order" for a in actions)
    total_refund = sum(float(a.get("refund_amount") or 0) for a in actions)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Recorded Actions", total_actions)
    m2.metric("Cancellations 🚫", cancels)
    m3.metric("Return Requests ↩️", returns)
    m4.metric("Total Refunds Recorded", _format_currency(total_refund))

    st.markdown("---")

    # Filters Row
    f_col1, f_col2, f_col3 = st.columns([2, 1, 1])
    with f_col1:
        search = st.text_input(
            "Search Actions",
            placeholder="Search by Action ID, Order ID, or Customer ID...",
            label_visibility="collapsed",
        ).strip().lower()
    with f_col2:
        action_filter = st.selectbox(
            "Action Type",
            ["All Actions", "Cancellations", "Return Requests"],
            label_visibility="collapsed",
        )
    with f_col3:
        status_filter = st.selectbox(
            "Action Status",
            ["All Statuses", "Completed", "Pending", "Processing"],
            label_visibility="collapsed",
        )

    filtered = actions
    if action_filter == "Cancellations":
        filtered = [a for a in filtered if a["action_type"] == "cancel_order"]
    elif action_filter == "Return Requests":
        filtered = [a for a in filtered if a["action_type"] == "return_order"]

    if status_filter != "All Statuses":
        filtered = [a for a in filtered if a.get("action_status") == status_filter.lower()]

    if search:
        filtered = [
            a for a in filtered
            if any(
                search in str(a.get(f) or "").lower()
                for f in ("action_id", "order_id", "customer_id", "action_type")
            )
        ]

    # Validate active selection
    active_ids = [a["action_id"] for a in filtered]
    if st.session_state.selected_action_id not in active_ids:
        st.session_state.selected_action_id = active_ids[0] if active_ids else None

    if not filtered:
        st.info("No order actions match the current filters.")
        return

    # Two-Pane Layout: Left List, Right Detail
    col_left, col_right = st.columns([1, 1.3], gap="large")

    with col_left:
        st.markdown(f"**Recorded Actions ({len(filtered)})**")
        with st.container(height=650):
            for a in filtered:
                aid = a["action_id"]
                is_selected = (aid == st.session_state.selected_action_id)

                with st.container(border=True):
                    act_icon = "🚫" if a["action_type"] == "cancel_order" else "↩️"
                    card_l, card_r = st.columns([3, 1], vertical_alignment="center")
                    with card_l:
                        st.markdown(f"**{act_icon} Action #{aid}**")
                    with card_r:
                        _status_badge(a.get("action_status"))

                    st.caption(f"ORD-{a['order_id']}  ·  Cust #{a['customer_id']}  ·  {_label(a.get('scope'))} Order")
                    st.markdown(f"**Refund:** {_format_currency(a.get('refund_amount'))}  ·  *Refund: {_label(a.get('refund_status'))}*")

                    btn_label = "Viewing Details 👉" if is_selected else "Inspect Action"
                    btn_type = "primary" if is_selected else "secondary"
                    if st.button(btn_label, key=f"btn_act_{aid}", type=btn_type, width="stretch"):
                        st.session_state.selected_action_id = aid
                        st.rerun()

    with col_right:
        act = next((a for a in filtered if a["action_id"] == st.session_state.selected_action_id), None)
        if act:
            _render_action_detail(act)
        else:
            st.info("Click on any action from the list on the left to view its details.")


# -----------------------------------------------------------------------------
# On-Page Top Navigation (NO SIDEBAR)
# -----------------------------------------------------------------------------
top_col1, top_col2, top_col3 = st.columns([4, 4, 1], vertical_alignment="center")
with top_col1:
    st.subheader("🛡️ Support Operations Desk")
    st.caption("Review customer cases, manage issues, and audit order cancellations & returns.")

with top_col2:
    active_view = st.segmented_control(
        "Navigation",
        ["🚨 Customer Issues", "📦 Cancellations & Returns"],
        default="🚨 Customer Issues",
        label_visibility="collapsed",
    )

with top_col3:
    if st.button("🔄 Refresh", width="stretch"):
        st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

# Render View Based on Top Segmented Control
if active_view == "🚨 Customer Issues":
    _issues_view()
else:
    _actions_view()
