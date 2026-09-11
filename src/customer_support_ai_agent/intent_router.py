from typing import Optional, Any, Literal
from functools import lru_cache
from pathlib import Path
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage

from customer_support_ai_agent.model import model
from customer_support_ai_agent.schemas import ActionConfirmationClassifier, UserInput
from customer_support_ai_agent.prompts import UNIFIED_SYSTEM_PROMPT, ACTION_CONFIRMATION_SYSTEM_PROMPT


@lru_cache(maxsize=1)
def load_policy_files() -> str:
    policy_path = Path(__file__).resolve().parents[2] / "docs" / "cancellation_and_return_policy.md"
    return policy_path.read_text(encoding="utf-8")


# =====================================================================
# 2. GENERAL USER INTENT CLASSIFIER (AI Router)
# =====================================================================

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
        description="Direct policy-grounded markdown answer citing section tags (e.g. [SEC-1.1], [SEC-4.0]) if intent is 'faq' or 'other'.",
    )


user_intent_llm = model.with_structured_output(UserIntent, method="json_mode")


def classify_user_intent(user_input: Any) -> UserIntent:
    """Classifies user free-text messages and answers FAQs with a single unified structured LLM call."""
    if isinstance(user_input, UserInput):
        text = user_input.text.strip()
    else:
        text = str(user_input or "").strip()

    if not text:
        return UserIntent(intent="other", reply="How can I help you today?")

    
    system_prompt = UNIFIED_SYSTEM_PROMPT.format(
        store_policies=load_policy_files()
    )

    try:
        return user_intent_llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=text),
        ])

    except Exception as e:
        print(f"Intent classifier error: {e}")
        # Deterministic fallback on network error
        return UserIntent(intent="other", reply="I'm having a brief connection issue. Please try again in a moment!")


# =====================================================================
# 3. ISOLATED CONFIRMATION GATE (Strict 0.95 Confidence Floor)
# =====================================================================
confirmation_llm = model.with_structured_output(ActionConfirmationClassifier, method="json_mode")

def classify_confirmation(
    reply: Any,
    action_noun: str,
    order_id: str,
    refund_amount: float,
) -> Optional[bool]:
    """
    Strict confirmation validator.
    Returns:
      True: explicitly confirmed (confidence >= 0.95)
      False: rejected, aborted, or keeping order
      None: ambiguous/unclear -> defaults to SAFE NON-EXECUTION
    """
   
    text = str(reply or "").strip()
    user_context = (
        f"Target Action: {action_noun}\n"
        f"Order ID: ORD-{order_id}\n"
        f"Refund Amount: ₹{refund_amount:.2f}\n"
        f"Customer Response: \"{text}\""
    )
    try:
        res = confirmation_llm.invoke([
            SystemMessage(content=ACTION_CONFIRMATION_SYSTEM_PROMPT),
            HumanMessage(content=user_context),
        ])
        if res.decision == "confirm" and res.confidence >= 0.95:
            return True
        elif res.decision in ("reject", "workflow_switch"):
            return False
        return None  # Unclear or FAQ -> do not execute
    except Exception as e:
        print(f"Confirmation classifier error: {e}")
        return None
