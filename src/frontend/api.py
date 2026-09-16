"""
HTTP calls used by the Streamlit frontend.
"""

from typing import Any

import requests


BACKEND_URL = "http://127.0.0.1:8000"


def chat_with_backend(user_id: int, thread_id: str, message: Any = None) -> dict:
    """Send one chat turn and return the backend response."""
    payload = {
        "user_id": user_id,
        "thread_id": thread_id,
        "message": message.strip() if isinstance(message, str) else message,
    }
    response = requests.post(f"{BACKEND_URL}/chat", json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def get_orders(user_id: int) -> list[dict]:
    """Return the customer's recent orders."""
    response = requests.get(f"{BACKEND_URL}/orders/{user_id}", timeout=3)
    response.raise_for_status()
    return response.json().get("orders", [])
