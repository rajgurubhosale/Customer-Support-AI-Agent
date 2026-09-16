from typing import  Any
from functools import lru_cache
from pathlib import Path
from langchain_core.messages import SystemMessage, HumanMessage

from customer_support_ai_agent.model import model
from customer_support_ai_agent.schemas import UserInput, UserIntent
from customer_support_ai_agent.prompts import UNIFIED_SYSTEM_PROMPT


# load prompt at startup server
_policy_path = Path(__file__).resolve().parents[2] / "docs" / "cancellation_and_return_policy.md"
SYSTEM_PROMPT = UNIFIED_SYSTEM_PROMPT.format(
    store_policies=_policy_path.read_text(encoding="utf-8")
)


user_intent_llm = model.with_structured_output(UserIntent, method="json_mode")

def classify_user_intent(user_text: str) -> UserIntent:
    """Classify free-text messages using a single structured LLM call."""
    text = str(user_text or "").strip()

    if not text:
        return UserIntent(intent="other", reply="How can I help you today?")
    
    try:
        return user_intent_llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=text),
        ])
    except Exception as error:
        print(f"Intent classifier error: {error}")
        return UserIntent(
            intent="other",
            reply="I'm having a brief connection issue. Please try again in a moment!",
        )

