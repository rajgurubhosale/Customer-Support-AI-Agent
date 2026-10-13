"""Case reference parsing shared by chat entry and case tracking."""

import re
from typing import Optional


CASE_ID_PATTERN = re.compile(r"\bcase(?:\s*[-:#]\s*|\s+)([1-9]\d*)\b", re.IGNORECASE)


def parse_case_id(text: str) -> Optional[str]:
    """Return one explicit CASE reference, never a bare number or guess."""
    matches = CASE_ID_PATTERN.findall(text or "")
    return matches[0] if len(matches) == 1 else None
