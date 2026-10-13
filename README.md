# Customer Support AI Agent

> **Work in progress**: Actively being built

A local customer-support demo for orders, cancellations, returns, and support cases. Customers use a Streamlit chat app; a separate Streamlit admin app reviews cases and order actions. FastAPI serves both apps, LangGraph manages the conversation, and PostgreSQL stores orders and results.

The model interprets free text and investigates reported issues. Python checks order ownership, policy eligibility, item links, and the customer's approval before a database write.

## What it handles

### Customer operations
- **Policy questions**: Answers store policy questions grounded directly in verified policy documentation.
- **Order tracking**: Retrieves order status and expected delivery dates from the database (no live carrier tracking).
- **Cancellations**: Cancels full or partial quantities for eligible unfulfilled orders (`Placed` or `Partially_Cancelled`) after customer confirmation.
- **Returns**: Validates return eligibility within the 7-day delivery window and records return requests.
- **Issue reporting**: Investigates order problems, clarifies missing details, and drafts support cases for customer review.
- **Case tracking**: Checks status and updates on existing support cases using a Case ID.

### Admin operations
- **Case & action review**: Lets support staff review open cases, inspect logged order actions, and add resolution notes.
- **Manual follow-up**: Allows reopening assistant-resolved cases for manual investigation (does not trigger payment refunds or courier dispatches).

## Supported issue scenarios

The agent handles **delivery issues** and **item issues** (scoped to one order per case):

| Customer situation | How the agent handles it |
| --- | --- |
| **Delivery feels slow, but on schedule** | Explains the verified estimated delivery date. Closes only if the customer confirms with **"That solved it"**. |
| **Overdue, missing, or stalled delivery** | Verifies order records and escalates to a structured support ticket for human review. |
| **Damaged, defective, or incorrect item** | Identifies the specific order item and drafts a support ticket with the reported defect. |
| **Missing or ambiguous details** | Prompts the customer for clarification before taking action. |

### Safety & boundaries
- **Customer-scoped queries**: All database lookups are strictly bound to the verified customer ID, preventing unauthorized order access.
- **Customer-in-the-loop review**: The customer must review and confirm draft findings and order actions before any database changes are saved.
- **What is NOT handled**: The system does not process live payment refunds, book courier pickups, or trigger replacement shipments. These require manual administrative handling.

## How the app is organized

```text
Customer Streamlit app ──► FastAPI /chat ──► LangGraph
                                           ├─ intent and policy response
                                           ├─ order cancel/return selection → approval → DB action
                                           └─ issue investigation → clarification → review → DB case

Admin Streamlit app ──────────────────────► PostgreSQL case/action records
```

Order selection, item selection, confirmation, and the database action follow deterministic rules. Free-text questions or changes of intent can still be classified by the model between those steps. The issue workflow uses an agent for investigation, followed by Python validation and a customer review screen. Case and order-action writes are transactional; the model cannot call a write tool directly.

## Run locally

**Requirements:** Python 3.12+, PostgreSQL, and [`uv`](https://docs.astral.sh/uv/).

1. Create a **disposable local PostgreSQL database**. Apply [`docs/000_base_schema.sql`](docs/000_base_schema.sql), [`docs/001_v1_schema.sql`](docs/001_v1_schema.sql), then [`docs/002_v1_seed.sql`](docs/002_v1_seed.sql), in that order. The seed creates its own demo customers, orders, cases, and action history; it does not depend on existing order IDs.
2. Copy `.env.example` to `.env`. Set `DATABASE_URL`, `MODEL_NAME`, `BASE_URL`, and `MESHAPI_DEEPSEEK_API` for your PostgreSQL database and OpenAI-compatible model endpoint. Set `LANGSMITH_TRACING=false` if you are not using LangSmith.
3. Install dependencies:

   ```bash
   uv sync
   ```

4. Start each service in a separate terminal:

   ```bash
   uv run uvicorn backend.main:app --app-dir src --reload --port 8000
   uv run streamlit run src/frontend/app.py --server.port 8501
   uv run streamlit run src/admin/app.py --server.port 8502
   ```

The API docs are at `http://localhost:8000/docs`. The customer app is at `http://localhost:8501`; the admin app is at `http://localhost:8502`.

### Try the demo

Set **Customer ID** to `9001` in the customer app sidebar. The seed uses fixed order IDs and dates relative to when it is applied. The admin dashboard opens with 14 cases and four historical order actions. These prompts are starting points; the model may ask for clarification before showing a review card.

| Situation | Orders | Example prompt |
| --- | --- | --- |
| On-schedule delivery | 9101–9104 | “Where is order 9101?” |
| Overdue or stalled delivery | 9111–9114 | “Order 9111 is late. What happened?” |
| Damaged, defective, missing, or wrong item | 9121–9124 | “The cup in order 9121 arrived broken.” |
| Cancellation | 9131–9134 | “Cancel order 9131.” Try 9132 for a partial quantity, 9133 for an already partly cancelled order, and 9134 for a shipped order. |
| Return | 9141–9144 | “Return order 9141.” Try 9142 for a partial quantity, 9143 for an already partly returned order, and 9144 for an expired return window. |
| Multiple issues in one order | 9151–9153 | “The bowl in order 9152 is broken and the strainer is missing.” |

The admin dashboard also includes cases `CASE-9201`–`CASE-9253` and past actions on orders 9161–9164. Customer `9002` owns order 9199; it should not be accessible as customer 9001. Confirmation changes trial orders and creates new records. Rerunning the seed preserves those changes, so use a fresh disposable database to reset the trial.

Run the tests with:

```bash
uv run python -m unittest discover -s tests -q
```

## Important limits

- Order tracking reads the application's database, not a courier feed. Return requests and cancellation refund records do not send money through a payment provider.
- Return eligibility checks only order status, item status, and the 7-day window. It does not enforce category-specific policy exceptions, physical item inspections, or courier quality checks.

## Future scope

1. **User and admin authentication**: Implement login, identity verification, and role-based access control for the customer chat app and admin dashboard instead of relying on client-supplied customer IDs.
2. **Durable conversation persistence**: Replace in-memory checkpoints with a persistent LangGraph checkpointer (e.g., PostgreSQL) so active conversations survive backend restarts.
3. **Focused dispute and replacement workflows**: Add dedicated workflows for refund disputes, pickup problems, and replacements, each with verified data and explicit approval where needed.
4. **Carrier and payment system integrations**: Connect live carrier tracking/pickups and payment gateways only when their status and execution can be verified end to end.
5. **Modular order-action architecture**: Simplify the order-action code around shared input contracts and smaller domain modules, guided by real customer journeys rather than a full graph rewrite.

## Code map

| Path | Purpose |
| --- | --- |
| `src/customer_support_ai_agent/graph.py`, `routes.py`, `nodes.py` | Conversation graph and order-action workflow. |
| `src/customer_support_ai_agent/issues/` | Issue investigation, review, case tracking, and case persistence. |
| `src/customer_support_ai_agent/policy_rules.py`, `db_functions.py` | Order eligibility and transactional cancel/return actions. |
| `src/backend/` | FastAPI routes and graph runner. |
| `src/frontend/` | Customer chat interface. |
| `src/admin/` | Local admin case and action interface. |
