
####################################################################################################

# human platform should get to see the ticket thats should be implemented then handle this later

####################################################################################################
# ADD REFUND STATUS IN DB
# DEFAULT NULL

On Cancel / Return Request: Set to 'Processing' (or 'Pending').

When Bank Credits Funds: Updated to 'Completed'.

If Bank Rejects: Updated to 'Failed'. RAISE HUMAN TICKET

# SHOULD BE AN OPTIONS THERE FOR THE CHECK ORDER ALSO

Yes, substantially. Here is how it saves cost:

1. 50% to 80% Lower Token Pricing
Major LLM providers (Anthropic, OpenAI, DeepSeek, Gemini, and Groq's tiered models) offer discounted pricing on cached prompt tokens:

Uncached Input: Charged at standard rate (100%).
Cached Input: Discounted by 50% to 90% depending on the provider, because their chips do not recompute the attention matrices for the cached tokens.
2. The Math for 100 User Queries
Without KV Caching: 100 queries × ~3,900 policy tokens = 390,000 input tokens computed from scratch.
With KV Caching: 1 warmup call computes 3,900 tokens. The other 99 queries read from the cache at the cached discount rate (or 0 incremental compute on hardware).
3. Bonus: 2x to 4x Faster Latency
Beyond saving direct dollar costs, cached requests return responses significantly faster (Time to First Token drops from ~300ms–800ms down to ~50ms–100ms) because the model skips processing 3,900 tokens on every turn.



# IMP 
# THE CONFIRM ACTION NODE IS FOR TEMP WILL CHANGES OR UPDATE IN UI CODE
# BREAK CONFIRM CODE INTO RETURN NODE AND CANCEL NODE LAST ASK FIRST INTERRUPT CONFIRM AND 
# USE ROUTE TO ROUTE TO THEM FROM CONFIRM CODE LAST

# BlockedOptionClassifier WRITE PROPER IN SCHEMASS.py


# Current Task & Architectural Roadmap

## 1. Implemented: `confirm_action_node` (Unified Confirmation)
- **Scope**: Handles both **Cancellation** and **Returns** dynamically using `state["action_type"]`.
- **Single-Item Orders**:
  - `Qty == 1`: Direct yes/no prompt with refund amount.
  - `Qty > 1`: Prompts for quantity to cancel/return (1 to N, or 'all') with exact proportional refund calculation.
- **Multi-Item Orders**:
  - Step 1: Lists active items with numbers + `'all'` entire order option.
  - Step 2: If item has `Qty > 1`, prompts for specific quantity.
  - Step 3: Final explicit `yes/no` confirmation before returning state.
- **State Storage**: Saves selection metadata into `state["context"]` (`action_scope`, `item_id`, `item_name`, `quantity`, `refund_amount`).

## 2. Future Web App / Streamlit UI Roadmap
- When building the web interface, replace CLI multi-turn interrupts with native UI components:
  - **Item Select**: Checkboxes or product cards.
  - **Quantity Adjuster**: Interactive number input or `+ / -` quantity stepper.
  - **Live Refund Display**: Reactive price calculator showing immediate refund total before final submit.

## 3. Pending / Next Steps
- **`retry_exhausted_node`**: Add dual-mode handling (shortcuts + LLM intent classification for natural complaint handling).
- **`execute_action_node`**: Add atomic database write transactions (`cancel_order_in_db` / `return_order_in_db`).
