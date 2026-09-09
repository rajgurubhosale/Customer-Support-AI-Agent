from typing import Optional, Any, Literal
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage

from customer_support_ai_agent.model import model
from customer_support_ai_agent.schemas import ActionConfirmationClassifier
from customer_support_ai_agent.prompts import ACTION_CONFIRMATION_SYSTEM_PROMPT


# =====================================================================
# 1. DETERMINISTIC BUTTON SIGNAL (0ms, 0 Cost)
# =====================================================================

def is_button_signal(user_input: Any) -> Optional[str]:
    """
    0ms check for literal UI button payloads and standard one-word commands.
    Returns: 'menu' | 'confirm' | 'abort' | 'all' | 'ticket' | None
    """
    if isinstance(user_input, dict):
        # Ignore item selection payloads (these are handled directly in select_items_node)
        if user_input.get("scope") or user_input.get("items"):
            return None

        val = user_input.get("value") or user_input.get("action")
        val_str = str(val or "").strip().lower()
        if val_str in ("menu", "main menu", "home", "reset", "start over", "back"):
            return "menu"
        if val_str in ("confirm", "yes", "proceed", "sure"):
            return "confirm"
        if val_str in ("abort", "no", "keep"):
            return "abort"
        if val_str in ("all", "all items", "entire", "whole"):
            return "all"
        if val_str in ("ticket", "human", "specialist"):
            return "ticket"
        return None

    text = str(user_input or "").strip().lower()
    if text in ("menu", "main menu", "home", "reset", "start over", "back", "exit", "quit", "bye"):
        return "menu"
    if text in ("confirm", "yes", "y", "proceed", "sure", "ok", "yes confirm", "do it"):
        return "confirm"
    if text in ("abort", "no", "n", "keep", "keep order", "nevermind", "never mind", "dont cancel", "don't cancel"):
        return "abort"
    if text in ("all", "all items", "entire", "whole", "cancel whole order"):
        return "all"
    if text in ("ticket", "human", "agent", "support", "specialist", "escalate"):
        return "ticket"
    return None




from functools import lru_cache
from pathlib import Path
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


user_intent_llm = model.with_structured_output(UserIntent)


def classify_user_intent(user_input: Any) -> UserIntent:
    """Classifies user free-text messages and answers FAQs with a single unified structured LLM call."""
    raw_text = user_input.get("value") if isinstance(user_input, dict) else user_input
    text = str(raw_text or "").strip()
    if not text:
        return UserIntent(intent="other", reply="How can I help you today?")

    # Fast check for literal button/abort signals
    button = is_button_signal(text)
    if button == "menu" or button == "abort":
        return UserIntent(intent="abort")
    if button == "ticket":
        return UserIntent(intent="human_support")

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
        lower = text.lower()
        if "cancel" in lower:
            return UserIntent(intent="cancel_order")
        if "return" in lower:
            return UserIntent(intent="return_order")
        if any(w in lower for w in ("track", "status", "where is", "delivery", "orders")):
            return UserIntent(intent="track_order")
        if any(w in lower for w in ("human", "agent", "ticket", "specialist")):
            return UserIntent(intent="human_support")
        return UserIntent(intent="other")


# =====================================================================
# 3. ISOLATED CONFIRMATION GATE (Strict 0.95 Confidence Floor)
# =====================================================================
# RULE: confirm_action_node NEVER calls classify_user_intent.
# It only calls is_button_signal first, and classify_confirmation second.

confirmation_llm = model.with_structured_output(ActionConfirmationClassifier)

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
    signal = is_button_signal(reply)
    if signal == "confirm":
        return True
    if signal in ("abort", "menu"):
        return False

    text = str(reply or "").strip()
    prompt = ACTION_CONFIRMATION_SYSTEM_PROMPT.format(
        action_noun=action_noun,
        order_id=order_id,
        refund_amount=refund_amount,
    )
    try:
        res = confirmation_llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content=text),
        ])
        if res.decision == "confirm" and res.confidence >= 0.95:
            return True
        elif res.decision in ("reject", "workflow_switch"):
            return False
        return None  # Unclear or FAQ -> do not execute
    except Exception as e:
        print(f"Confirmation classifier error: {e}")
        return None
