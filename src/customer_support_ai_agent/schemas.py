from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field, field_validator



DIRECT_ACTIONS = frozenset({
    "confirm",
    "abort",
    "back",
    "menu",
    "ticket",
    "human",
    "exit",
    "track_order",
})


class UserIntent(BaseModel):
    intent: Literal[
        "cancel_order",
        "return_order",
        "track_order",
        "faq",
        "human_support",
        "abort",
        "other",
    ] = Field(description="The primary detected intent of the customer message.")
    order_id: Optional[str] = Field(
        default=None,
        description="Extracted numeric order ID if user mentioned one (e.g. '15' for 'ORD-15' or '#15').",
    )
    reply: Optional[str] = Field(
        default=None,
        description=(
            "A concise policy-grounded markdown answer only when the customer explicitly asks "
            "a policy or timeline question, including alongside another intent; otherwise null. "
            "Cite relevant section tags such as [SEC-1.1] or [SEC-4.0]."
        ),
    )

class UserInput(BaseModel):
    """Canonical user input model normalized at the system boundary."""

    text: str = ""
    action: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)

    @property
    def lower_text(self) -> str:
        return self.text.lower().strip()


class SelectedItemInput(BaseModel):
    """One item and quantity submitted by the item-selection UI."""

    item_id: str | int
    quantity: int = Field(gt=0)

class PartialItemSelection(BaseModel):
    """Validated payload for a partial cancellation or return."""

    scope: Literal["partial"] = "partial"
    items: list[SelectedItemInput] = Field(min_length=1)

    @field_validator("items")
    @classmethod
    def check_unique_items(cls, items: list[SelectedItemInput]) -> list[SelectedItemInput]:
        ids = [str(it.item_id) for it in items]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate items selected in payload.")
        return items



def normalize_user_input(raw: Any) -> UserInput:
    """
    Convert text or a UI payload to the stable UserInput contract.
    """
    if isinstance(raw, UserInput):
        return raw

    if isinstance(raw, str):
        text = raw.strip()
        lower_text = text.lower()
        action = lower_text if lower_text in DIRECT_ACTIONS else None
        return UserInput(text=text, action=action, data={})

    if isinstance(raw, dict):
        value = str(raw.get("value") or "").strip()
        action = str(raw.get("action") or "").strip().lower()

        text = value or action

        if action:
            action = action.lower()
            
        elif value.lower() in DIRECT_ACTIONS:
            action = value.lower()
        else:
            action = None

        return UserInput(
            text=text,
            action=action,
            data=raw,
    )
    
    if raw is None:
        return UserInput()

    return UserInput(text=str(raw).strip(), action=None, data={})
