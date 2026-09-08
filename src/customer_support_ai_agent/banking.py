import random

# IT WILL BE MANUAL RETURN REFUND OPTION ON TEH HUMAN ADMIN SITE
# refund manual process
# human in the loop refund 

def process_mock_refund(order_id: int, amount: float) -> dict:
    """Simulates a payment gateway response like Razorpay/Stripe."""
    # 90% chance success, 10% chance bank failure (for testing edge cases)
    outcome = random.choices(["Completed", "Failed"], weights=[90, 10])[0]

    return {
        "transaction_id": f"rfnd_mock_{random.randint(10000, 99999)}",
        "order_id": order_id,
        "amount": amount,
        "refund_status": outcome,
    }



# tokens based authentitaction for api calls    