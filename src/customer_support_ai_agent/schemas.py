from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field


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


class UserInput(BaseModel):
    """Canonical user input model normalized at the system boundary."""

    text: str = ""
    action: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)


def normalize_user_input(raw: Any) -> UserInput:
    """Convert text or a UI payload to the stable UserInput contract."""
    
    if isinstance(raw, UserInput):
        return raw

    if isinstance(raw, str):
        text = raw.strip().lower()

        if text in DIRECT_ACTIONS:
            action = text
        else:
            action = None
        return UserInput(text=text, action=action, data={}) 

    if isinstance(raw, dict):
        value = str(raw.get("value") or "").strip()
        action = str(raw.get("action") or "").strip().lower()

        text = value or action

        if action:
            action = action.lower()
            
        elif value.lower() in DIRECT_ACTIONS:
            action = value
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


class IntentClassifier(BaseModel):
    action_type: Literal[
        "cancel_order",
        "return_order",
        "faq",
        "human_support",
        "unclear"
    ] = Field(
        description="The customer's primary goal. Use 'unclear' if not confident or off-topic."
    )
    order_id: Optional[str] = Field(
        default=None,
        description="Order ID digits if mentioned in the message (e.g., '15' for 'ORD-15' or 'order 12')."
    )
    confidence_reason: Optional[str] = Field(
        default="",
        description="Short 1-sentence explanation of why this category was chosen."
    )


# 3. Ultra-Conservative Confirmation Intent Classifier
class ActionConfirmationClassifier(BaseModel):
    """Ultra-conservative confirmation intent classifier."""
    decision: Literal["confirm", "reject", "faq", "workflow_switch", "unclear"] = Field(
        description=(
            "Strict classification of user's confirmation reply. "
            "Use 'confirm' ONLY if the user is 100% explicitly and unequivocally confirming "
            "(e.g. 'confirm it', 'yes', 'proceed', 'go ahead', 'do it'). "
            "If there is even 5% ambiguity, hesitation, conditionality, or doubt, you MUST NOT use 'confirm'."
        )
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0 that the user unequivocally wants to proceed."
    )
    explanation: Optional[str] = Field(
        default="",
        description="Brief 1-sentence reason for the decision."
    )
