import re
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

INJECTION_PATTERNS = [
    r"ignore\s+(previous|all)\s+instructions",
    r"system\s+prompt",
    r"you\s+are\s+now",
    r"forget\s+your\s+(role|instructions)",
    r"<\|.*?\|>",
    r"\[INST\]",
    r"DAN\s+mode",
    r"jailbreak",
    r"bypass\s+(safety|filter|restriction)",
]


def detect_injection(text: str) -> Tuple[bool, str]:
    """
    Detect potential prompt injection attempts.
    Returns (is_injection, reason). Two-layer: regex then length/complexity check.
    """
    if not isinstance(text, str):
        return False, ""

    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            logger.warning(f"Injection pattern detected: {pattern}")
            return True, f"Pattern match: {pattern}"

    # Heuristic: abnormally long input or contains code blocks in incident description
    if len(text) > 5000:
        logger.warning("Input exceeds maximum allowed length")
        return True, "Input exceeds maximum allowed length"

    return False, ""


def sanitize_input(text: str) -> str:
    """
    Strip HTML tags, script tags, and dangerous content.
    Limits text to 5000 characters.
    """
    if not isinstance(text, str):
        return ""

    import html

    # Remove script tags and content
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Unescape HTML entities
    text = html.unescape(text)
    # Limit length
    text = text[:5000].strip()

    return text
