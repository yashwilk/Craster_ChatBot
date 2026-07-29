"""Input sanitization helpers."""

import html
import re
from typing import Any, Dict, List


def sanitize_email(email: str) -> str:
    """Sanitize and validate an email address, returning it lowercased."""
    email = sanitize_string(email)
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        raise ValueError("Invalid email format")
    return email.lower()


def validate_password_strength(password: str) -> bool:
    """Raise ValueError if the password doesn't meet strength requirements."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"[0-9]", password):
        raise ValueError("Password must contain at least one number")
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise ValueError("Password must contain at least one special character")
    return True


def sanitize_string(value: str) -> str:
    """HTML-escape and strip null bytes / script remnants from a string."""
    if not isinstance(value, str):
        value = str(value)
    value = html.escape(value)
    value = re.sub(r"&lt;script.*?&gt;.*?&lt;/script&gt;", "", value, flags=re.DOTALL)
    return value.replace("\0", "")


def sanitize_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively sanitize all string values in a dict."""
    out = {}
    for key, value in data.items():
        if isinstance(value, str):
            out[key] = sanitize_string(value)
        elif isinstance(value, dict):
            out[key] = sanitize_dict(value)
        elif isinstance(value, list):
            out[key] = sanitize_list(value)
        else:
            out[key] = value
    return out


def sanitize_list(data: List[Any]) -> List[Any]:
    """Recursively sanitize all string values in a list."""
    out = []
    for item in data:
        if isinstance(item, str):
            out.append(sanitize_string(item))
        elif isinstance(item, dict):
            out.append(sanitize_dict(item))
        elif isinstance(item, list):
            out.append(sanitize_list(item))
        else:
            out.append(item)
    return out
