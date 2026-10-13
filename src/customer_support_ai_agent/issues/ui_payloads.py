from typing import Any, Dict, List

# Reusable Standard Buttons for Issue Workflow
BTN_SUBMIT_CASE = {"label": "🚀 Submit Case", "value": "confirm"}
BTN_EDIT_DETAILS = {"label": "✏️ Edit Details", "value": "edit"}
BTN_CANCEL = {"label": "❌ Cancel", "value": "cancel"}


def build_answer_payload(issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    answer = "\n\n".join(i.get("explanation") or i.get("description", "") for i in issues)
    return {
        "prompt": answer + "\n\nDid that answer your question?",
        "options": [
            {"label": "✅ That solved it", "value": "solved"},
            {"label": "🙋 I still need help", "value": "need_help"},
        ],
    }


def build_clarification_payload(question: str, choices: List[Dict[str, str]] | None = None) -> Dict[str, Any]:
    """Prompt when the agent needs missing details from the customer."""
    return {
        "prompt": question or "Please provide additional details regarding this issue:",
        "options": (choices or []) + [BTN_CANCEL],
    }


def build_review_payload(issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Constructs the review card and option buttons before case submission."""
    lines = [
        f"• **{i.get('description', 'Issue')}** (Order: #{i.get('order_id', 'Unassigned')})\n  *Finding:* {i.get('explanation', '')}"
        for i in issues
    ]

    return {
        "prompt": "📋 **Review your issues:**\n\n" + "\n\n".join(lines) + "\n\n*Would you like to submit this case for review?*",
        "options": [BTN_SUBMIT_CASE, BTN_EDIT_DETAILS, BTN_CANCEL],
    }


def build_track_case_payload() -> Dict[str, Any]:
    """Prompt asking customer for an explicit Case ID to track."""
    return {
        "prompt": "🔍 **Please enter your Case ID (e.g. CASE-1):**",
        "options": [BTN_CANCEL],
    }


def build_track_case_card(case: Dict[str, Any]) -> str:
    status_icon = "🟢" if case["status"] == "resolved" else "🟡"
    card = (
        f"📋 **Support Case #CASE-{case['case_id']}**\n"
        f"• **Status:** {status_icon} `{case['status'].upper()}`\n"
        f"• **Priority:** `{case['priority'].upper()}`\n"
        f"• **Summary:** {case['summary']}\n\n"
        f"**Linked Issues:**\n"
    )
    for iss in case.get("issues", []):
        iss_icon = "🟢" if iss["status"] == "resolved" else "🟡"
        card += f"  {iss_icon} **{iss['issue_type']}** [{iss['status']}]: {iss['description']}\n"
        if iss["status"] == "resolved" and iss.get("resolution_summary"):
            card += f"  *Resolution note:* {iss['resolution_summary']}\n"
    return card
