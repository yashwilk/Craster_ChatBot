"""Prompt loading — templates are read once at import time, not per request."""

import os
from datetime import datetime
from typing import Optional

from app.core.config import settings

_PROMPTS_DIR = os.path.dirname(__file__)

with open(os.path.join(_PROMPTS_DIR, "system.md"), "r") as _f:
    _SYSTEM_PROMPT_TEMPLATE = _f.read()

with open(os.path.join(_PROMPTS_DIR, "session_title.md"), "r") as _f:
    SESSION_TITLE_PROMPT = _f.read()


def load_system_prompt(username: Optional[str] = None, **kwargs):
    """Render the system prompt template with runtime context."""
    user_context = f"# User\nYou are talking to {username}.\n" if username else ""
    return _SYSTEM_PROMPT_TEMPLATE.format(
        agent_name=settings.PROJECT_NAME + " Agent",
        current_date_and_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user_context=user_context,
        **kwargs,
    )
