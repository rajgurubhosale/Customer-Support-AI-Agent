
from typing import Optional, Literal
from pydantic import BaseModel, Field



# 1. Strict Schema: LLM is restricted ONLY to these 5 choices
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



# 2. Structured Mutation Schemas for Cancel & Return Execution
class SelectedItemSchema(BaseModel):
    item_id: int
    quantity: int = Field(default=1, gt=0)


class ActionSelectionPayload(BaseModel):
    action: Optional[str] = "cancel"
    scope: Optional[Literal["all", "partial"]] = "partial"
    items: list[SelectedItemSchema] = Field(default_factory=list)


class OrderMutationContext(BaseModel):
    order_id: str
    action_type: Literal["cancel_order", "return_order"]
    action_scope: Literal["all", "partial"]
    items: list[dict]
    refund_amount: float


# 3. Ultra-Conservative Confirmation Intent Classifier
class ActionConfirmationClassifier(BaseModel):
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

