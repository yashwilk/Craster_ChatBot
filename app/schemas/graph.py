"""LangGraph state schema."""

from typing import Annotated

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class GraphState(BaseModel):
    """State carried through the agent graph."""

    messages: Annotated[list, add_messages] = Field(default_factory=list)
    long_term_memory: str = Field(default="")
