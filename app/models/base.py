"""Base model with common fields."""

from datetime import datetime, UTC
from sqlmodel import Field, SQLModel


class BaseModel(SQLModel):
    """Base model providing created_at to every table."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
