
############## TRANSFER LATER
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
    confidence_reason: str = Field(
        description="Short 1-sentence explanation of why this category was chosen."
    )


class BlockedOptionClassifier(BaseModel):
    decision: Literal["ticket", "menu"] = Field(
        description="Classify if the customer wants to raise a support ticket / speak with an agent, or return to the main menu."
    )
    user_complaint: Optional[str] = Field(
        default=None,
        description="Brief summary of the customer's grievance or question for the support ticket."
    )


class RetryExhaustedClassifier(BaseModel):
    decision: Literal["retry", "menu", "ticket"] = Field(
        description="Classify if the customer wants to retry entering their order details ('retry'), return to the main menu ('menu'), or talk to human support ('ticket')."
    )
