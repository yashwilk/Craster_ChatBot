"""Human-in-the-loop confirmation tool."""

from langchain_core.tools import tool
from langgraph.types import interrupt


@tool
def ask_human(question: str) -> str:
    """Pause execution and ask the human a question before proceeding.

    Use this whenever you need clarification or confirmation before taking a
    significant or irreversible action.

    Args:
        question: The question to ask the human.

    Returns:
        str: The human's response.
    """
    return str(interrupt(question))
