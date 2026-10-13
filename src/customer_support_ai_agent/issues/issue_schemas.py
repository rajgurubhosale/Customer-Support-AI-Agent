from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class EvaluatedIssue(BaseModel):
    model_config = {"populate_by_name": True, "extra": "ignore"}

    issue_type: Literal["delivery_issue", "item_issue"] = Field(
        default="item_issue",
        description="'delivery_issue' for shipping/delivery problems; 'item_issue' for damaged, defective, or wrong items.",
    )
    kind: str = Field(
        default="unclassified",
        description="Subtype: delayed, possibly_lost, tracking_not_updated, delivered_not_received, wrong_item, missing_item, damaged_item, wrong_variant.",
    )
    order_id: Optional[int] = Field(default=None, description="Verified numeric order ID from tool facts, or null if unknown.")
    order_item_id: Optional[int] = Field(default=None, description="Verified order_item_id from tool facts, or null if not an item issue.")
    item_reference: Optional[str] = Field(default=None, description="Item name or keyword cited by customer (e.g. 'watch', 'keyboard').")
    description: str = Field(default="", description="Concise description of the customer's stated issue.")
    reported: Dict[str, Any] = Field(
        default_factory=dict,
        description="Customer-claimed details such as damage_description, customer_statement, or received_variant.",
    )
    explanation: str = Field(
        default="",
        alias="response",
        description="Agent's finding and reasoning citing verified dates, order facts, and store policies.",
    )
    next_step: Literal["answer", "ask_customer", "open_case"] = Field(
        default="open_case",
        alias="outcome",
        description="'answer' for on-schedule deliveries; 'ask_customer' if essential details are missing; 'open_case' for damage, delays, or return claims.",
    )
    question: Optional[str] = Field(default=None, description="Question to ask customer if next_step='ask_customer'.")

    @field_validator("reported", mode="before")
    @classmethod
    def parse_reported(cls, v: Any) -> Dict[str, Any]:
        if isinstance(v, str):
            return {"customer_statement": v}
        if isinstance(v, dict):
            return v
        return {}

    @field_validator("next_step", mode="before")
    @classmethod
    def normalize_next_step(cls, v: Any) -> str:
        val = str(v or "open_case").strip().lower()
        if val in {"answer", "resolved"}:
            return "answer"
        if val in {"ask_customer", "ask", "question"}:
            return "ask_customer"
        return "open_case"


class CaseInvestigation(BaseModel):
    model_config = {"populate_by_name": True, "extra": "ignore"}

    summary: str = Field(default="Customer support case investigation.", description="1-2 sentence overall summary of the case.")
    overall_priority: Literal["low", "medium", "high"] = Field(default="medium")
    issues: list[EvaluatedIssue] = Field(min_length=1, description="List of investigated issues.")
