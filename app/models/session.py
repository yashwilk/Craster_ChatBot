"""Chat session model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.user import User


class Session(BaseModel, table=True):
    """A chat session belonging to a user."""

    id: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    name: str = Field(default="")
    username: Optional[str] = Field(default=None)
    user: "User" = Relationship(back_populates="sessions")
