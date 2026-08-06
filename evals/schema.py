"""Schemas for evals."""

from pydantic import BaseModel, Field


class ScoreSchema(BaseModel):
    """A single metric's evaluation result."""

    score: float = Field(description="score between 0 and 1")
    reasoning: str = Field(description="one sentence reasoning")
