from typing import Optional, Literal, Dict, Any
from pydantic import BaseModel, Field


class UserInput(BaseModel):
    """Canonical user input model normalized at the system boundary."""
    text: str = ""
    action: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)


####################################3
# REMOVE THIS BUT FIRST CHECK WHICH SCHEMA TO KEEP IN INTENT ROUTER BEFORE DELETING
############################333
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
