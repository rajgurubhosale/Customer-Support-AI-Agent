import re
from typing import Optional, Dict, Any, Set
from customer_support_ai_agent.model import model
from customer_support_ai_agent.schemas import IntentClassifier, ActionConfirmationClassifier
from customer_support_ai_agent.prompts import START_NODE_INTENT_SYSTEM_PROMPT, ACTION_CONFIRMATION_SYSTEM_PROMPT

# Lightweight structured LLM classifiers
classifier_llm = model.with_structured_output(IntentClassifier)
confirmation_classifier_llm = model.with_structured_output(ActionConfirmationClassifier)

# 0ms Fast Token Filter: Standard UI button clicks that never require an LLM
BUTTON_TOKENS = {
    "yes", "no", "all", "all items", "entire", "whole",
    "back", "menu", "main menu", "exit", "ticket",
    "1", "2", "3", "4", "keep", "confirm", "confirm it",
    "yes confirm", "proceed", "go ahead", "do it",
    "nevermind", "never mind", "abort", "cancel", "stop",
}

ABORT_TOKENS = {
    "menu", "main menu", "back", "go back", "exit", "quit", "no", "stop",
    "cancel", "abort", "nevermind", "never mind", "leave", "home", "reset",
    "start over", "back to menu", "return to menu", "no thanks", "keep order",
    "keep", "dont cancel", "dont return", "don't cancel", "don't return",
}


def is_abort_intent(user_input: Any) -> bool:
    """
    Checks if the user wants to cancel the current workflow, go back,
    or return to the main menu. Matches exact tokens and common conversational phrases.
    """
    if not user_input:
        return False
    raw_val = user_input.get("value") if isinstance(user_input, dict) else user_input
    text = str(raw_val or "").strip().lower()
    if text in ABORT_TOKENS:
        return True
    phrases = (
        "back to menu", "return to menu", "go back", "nevermind", "never mind",
        "start over", "take me back", "cancel this", "stop this", "leave this",
        "main menu", "keep my order", "keep order", "don't want to cancel",
        "dont want to cancel", "back please", "return to main menu"
    )
    return any(p in text for p in phrases)


def validate_expected_input(user_input: Any, expected_tokens: Set[str]) -> bool:
    """
    Tier 1 Fast-Path (0ms, 0 Cost):
    Validates whether the input directly satisfies the expected choices of the current node
    (e.g., button clicks like 'yes', 'no', '1', 'all', or an exact expected order ID).
    """
    if not user_input:
        return False

    if is_abort_intent(user_input):
        return True

    raw_val = user_input.get("value") if isinstance(user_input, dict) else user_input
    clean_val = str(raw_val or "").strip().lower()

    if clean_val in expected_tokens:
        return True

    if "__order_id__" in expected_tokens and (clean_val.isdigit() or re.match(r"^(?:order|ord)?\s*[-#]?\s*\d+$", clean_val)):
        return True

    return False


def detect_intent_switch(user_input: Any, current_flow: str) -> Optional[Dict[str, Any]]:
    """
    Lightweight LLM Intent Classifier for unexpected free-text input.
    Detects whether the user is asking a read-only policy FAQ, switching to another action,
    or requesting human support.
    """
    raw_val = user_input.get("value") if isinstance(user_input, dict) else user_input
    text = str(raw_val or "").strip()
    if not text or text.lower() in BUTTON_TOKENS:
        return None

    # Fast regex fallback for order ID digits (e.g. ORD-15, order-15, order 15, #15)
    id_match = re.search(r"(?:order|ord)\s*[-#]?\s*(\d+)", text, re.I) or re.search(r"#\s*(\d+)", text, re.I)
    extracted_order_id = id_match.group(1) if id_match else None

    text_lower = text.lower()

    # Fast Tier 2: Keyword & regex matching (0ms, avoids Groq rate-limiting)
    fast_action = None
    if any(p in text_lower for p in ("order status", "check status", "track status", "track order", "track package", "where is my order", "my orders", "recent orders")) or (
        ("check" in text_lower or "track" in text_lower or "where" in text_lower or "status" in text_lower)
        and ("order" in text_lower or "package" in text_lower or "item" in text_lower)
    ):
        return {
            "type": "faq_query",
            "action_type": "faq",
            "question": text,
            "order_id": extracted_order_id,
        }
    elif any(p in text_lower for p in ("human", "agent", "representative", "specialist", "escalate", "support ticket", "raise ticket", "talk to human", "talk to agent")):
        fast_action = "human_support"
    elif any(w in text_lower for w in ("cancel", "cancellation", "cancelling")) and not is_abort_intent(text_lower):
        fast_action = "cancel_order"
    elif (
        any(w in text_lower for w in ("return", "returning", "replacement"))
        and not is_abort_intent(text_lower)
        and not any(q in text_lower for q in ("how", "what", "policy", "window", "when", "?"))
    ):
        fast_action = "return_order"

    if fast_action and fast_action != current_flow:
        init_msgs = {
            "cancel_order": "Sure, I can help you cancel your order.",
            "return_order": "Sure, I can help you request a return.",
            "human_support": "Connecting you with human customer support...",
        }
        transitions = {
            "cancel_order": "Understood. Switching over to cancel your order instead.",
            "return_order": "Got it! Let's switch to returning your order instead.",
            "human_support": "Connecting you with human support...",
        }
        msg = init_msgs.get(fast_action, f"Helping you with {fast_action.replace('_', ' ')}.") if current_flow == "open" else transitions.get(fast_action, f"Switching to {fast_action.replace('_', ' ')}...")
        return {
            "type": "workflow_switch",
            "action_type": fast_action,
            "order_id": extracted_order_id,
            "transition_message": msg,
        }

    try:
        res: IntentClassifier = classifier_llm.invoke([
            {"role": "system", "content": START_NODE_INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ])
        action = res.action_type
        order_id = res.order_id or extracted_order_id

        # 1. Read-only Policy or store inquiry
        if action == "faq":
            return {
                "type": "faq_query",
                "action_type": "faq",
                "question": text,
                "order_id": order_id,
            }

        # 2. Action Trigger or Workflow Switch
        if action in ("cancel_order", "return_order", "human_support") and action != current_flow:
            if current_flow == "open":
                init_msgs = {
                    "cancel_order": "Sure, I can help you cancel your order.",
                    "return_order": "Sure, I can help you request a return.",
                    "human_support": "Connecting you with human customer support...",
                }
                msg = init_msgs.get(action, f"Helping you with {action.replace('_', ' ')}.")
            else:
                transitions = {
                    "cancel_order": "Understood. Switching over to cancel your order instead.",
                    "return_order": "Got it! Let's switch to returning your order instead.",
                    "human_support": "Connecting you with human support...",
                }
                msg = transitions.get(action, f"Switching to {action.replace('_', ' ')}...")

            return {
                "type": "workflow_switch",
                "action_type": action,
                "order_id": order_id,
                "transition_message": msg,
            }
    except Exception as e:
        print(f"Intent classification notice: {e}")

    return None


def classify_confirmation_intent(
    user_input: Any,
    action: str,
    order_id: str,
    refund_amount: float = 0.0
) -> ActionConfirmationClassifier:
    """
    Evaluates confirmation intent using structured LLM classification.
    Adheres strictly to the zero-ambiguity rule: only confirms if 100% confident.
    """
    raw_val = user_input.get("value") if isinstance(user_input, dict) else user_input
    clean_val = str(raw_val or "").strip().lower()

    # Fast-path 1: Direct unambiguous affirmative tokens
    if clean_val in ("yes", "y", "1", "confirm", "confirm it", "yes confirm", "proceed", "go ahead", "do it"):
        return ActionConfirmationClassifier(decision="confirm", confidence=1.0, explanation="Direct affirmative button/token")
    if clean_val in ("no", "n", "2", "back", "menu", "keep", "keep order") or is_abort_intent(clean_val):
        return ActionConfirmationClassifier(decision="reject", confidence=1.0, explanation="Direct negative button/token")

    action_noun = "Cancellation" if action == "cancel_order" else "Return"
    prompt = ACTION_CONFIRMATION_SYSTEM_PROMPT.format(
        action_noun=action_noun,
        order_id=order_id,
        refund_amount=refund_amount,
    )

    try:
        res: ActionConfirmationClassifier = confirmation_classifier_llm.invoke([
            {"role": "system", "content": prompt},
            {"role": "user", "content": str(raw_val or user_input)},
        ])
        return res
    except Exception as e:
        print(f"Confirmation classification notice: {e}")
        return ActionConfirmationClassifier(
            decision="unclear",
            confidence=0.0,
            explanation=f"Classifier fallback on error: {e}",
        )


def clear_flow_state(state: Dict[str, Any], new_order_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Centralized state cleanup when switching workflows.
    Wipes flow-local keys to prevent data contamination while preserving identity.
    """
    return {
        "order_id": new_order_id or state.get("order_id"),
        "customer_details": None,
        "retry_count": 0,
        "confirmed": None,
        "context": None,
    }
