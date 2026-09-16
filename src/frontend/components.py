"""Reusable Streamlit widgets for structured backend payloads."""

from collections.abc import Callable
from typing import Any

import streamlit as st


SubmitHandler = Callable[[Any, str | None], None]


def render_stepper_card(
    ui_data: dict,
    on_submit: SubmitHandler,
    key_suffix: int,
) -> None:
    """Render item quantity selectors without changing the payload contract."""
    order_id = ui_data.get("order_id", "")
    action_verb = ui_data.get("action_verb", "cancel")
    action_noun = ui_data.get("action_noun", "Cancellation")
    selected_items = []
    refund = 0.0

    with st.container(border=True):
        st.markdown(f"#### 📦 Order #ORD-{order_id} Details")
        st.caption(
            f"Status: `{ui_data.get('status', '')}`  |  "
            f"Order Date: `{ui_data.get('order_date', '')}`  |  "
            f"Order Total: `₹{float(ui_data.get('order_total', 0)):.2f}`"
        )

        headers = st.columns([4, 2, 3])
        headers[0].markdown("**Item**")
        headers[1].markdown("**Ordered**")
        headers[2].markdown(f"**{action_verb.title()} Qty**")

        for item in ui_data.get("items", []):
            item_id = item["item_id"]
            name = item["name"]
            max_quantity = int(item.get("quantity", 1))
            unit_price = float(item.get("unit_price", 0))
            columns = st.columns([4, 2, 3])

            columns[0].markdown(f"**{name}**  \n₹{unit_price:.2f} each")
            columns[1].markdown(f"`{max_quantity}`")
            quantity = columns[2].number_input(
                f"Quantity for {name}",
                min_value=0,
                max_value=max_quantity,
                value=0,
                step=1,
                key=f"stepper_{item_id}_{key_suffix}",
                label_visibility="collapsed",
            )

            if quantity:
                refund += quantity * unit_price
                selected_items.append({
                    "item_id": item_id,
                    "name": name,
                    "quantity": quantity,
                })

        if selected_items:
            summary = ", ".join(
                f"{item['quantity']}× {item['name']}" for item in selected_items
            )
            st.info(
                f"📋 **Selected for {action_noun}:** {summary}\n\n"
                f"💰 **Estimated Refund:** ₹{refund:.2f}"
            )
        else:
            st.caption("ℹ️ Adjust quantities above using `+` and `-` to select items.")

        buttons = st.columns([1.4, 1.4, 1.2])
        if buttons[0].button(
            f"✅ Confirm {action_noun}",
            type="primary",
            disabled=not selected_items,
            width="stretch",
            key=f"confirm_btn_{key_suffix}",
        ):
            items = [
                {"item_id": item["item_id"], "quantity": item["quantity"]}
                for item in selected_items
            ]
            on_submit(
                {"action": action_verb, "scope": "partial", "items": items},
                f"Confirm {action_noun} ({len(items)} items)",
            )

        if buttons[1].button(
            f"❌ {action_verb.title()} Whole Order",
            width="stretch",
            key=f"whole_order_btn_{key_suffix}",
        ):
            on_submit(
                {"action": action_verb, "scope": "all"},
                f"❌ {action_verb.title()} Whole Order",
            )

        if buttons[2].button(
            "🔙 Back to Menu",
            width="stretch",
            key=f"back_btn_{key_suffix}",
        ):
            on_submit({"action": "back"}, "🔙 Back to Main Menu")


def render_quick_options(
    options: list,
    on_submit: SubmitHandler,
    key_suffix: int,
) -> None:
    """Render the clickable options supplied by the backend."""
    if not options:
        return

    st.caption("Quick Options:")
    columns_per_row = min(2, len(options))

    for row_start in range(0, len(options), columns_per_row):
        row = options[row_start : row_start + columns_per_row]
        columns = st.columns(columns_per_row)

        for offset, (column, option) in enumerate(zip(columns, row)):
            label = option.get("label", str(option)) if isinstance(option, dict) else str(option)
            value = option.get("value", str(option)) if isinstance(option, dict) else str(option)
            index = row_start + offset

            if column.button(
                label,
                key=f"option_{index}_{key_suffix}",
                width="stretch",
            ):
                on_submit(value, label)
