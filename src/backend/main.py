import threading
from fastapi import FastAPI
from customer_support_ai_agent.intent_router import load_policy_files
from customer_support_ai_agent.prompts import UNIFIED_SYSTEM_PROMPT
from customer_support_ai_agent.model import model
from langchain_core.messages import SystemMessage, HumanMessage


def warmup_kv_cache():
    """Background worker to warm up both RAM cache and LLM provider KV cache on boot."""
    try:
        policy = load_policy_files()
        system_prompt = UNIFIED_SYSTEM_PROMPT.format(store_policies=policy)
        model.invoke([SystemMessage(content=system_prompt), HumanMessage(content="ping")])
        print("[Warmup] Store policy KV Cache primed successfully on LLM provider!")
    except Exception as e:
        print(f"[Warmup] Non-fatal notice: {e}")



app = FastAPI(
    title="Customer Support AI Agent API",
    description="REST API powering the Customer Support LangGraph AI Agent",
    version="0.1.0",
)


@app.on_event("startup")
def startup_event():
    threading.Thread(target=warmup_kv_cache, daemon=True).start()



@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/")
def welcome():
    return {
        "message": "Customer Support AI Agent API is online!",
        "docs_url": "/docs",
    }
    

from customer_support_ai_agent.db_functions import get_order_history
from backend.schemas import ChatRequest, ChatResponse
from backend.helper import execute_agent_turn

# -----------------------------
# API Routes
# -----------------------------



@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):

    result = execute_agent_turn(
        user_id=request.user_id,
        user_message=request.message,
        thread_id=request.thread_id,
    )

    return ChatResponse(**result)


@app.get("/orders/{user_id}")
def get_orders(user_id: int):

    return {
        "user_id": user_id,
        "orders": get_order_history(user_id) or []
    }


# -----------------------------
# Terminal testing
# -----------------------------

def main():

    user_id = int(input("User ID: "))
    thread_id = f"cli-{user_id}"

    response = execute_agent_turn(
        user_id=user_id,
        thread_id=thread_id
    )

    print("\nAI:", response["ai_response"])

    while response["status"] == "waiting_for_input":

        message = input("\nYou: ").strip()

        if message.lower() in {"exit", "quit", "bye"}:
            break

        response = execute_agent_turn(
            user_id=user_id,
            user_message=message,
            thread_id=thread_id
        )

        for notice in response["messages"]:
            print("AI:", notice)

        print("AI:", response["ai_response"])


if __name__ == "__main__":
    main()