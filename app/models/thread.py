"""Thread model — reserved for future use; LangGraph's own checkpoint tables
(checkpoints/checkpoint_writes/checkpoint_blobs) are what actually persist
conversation state today. Kept for schema parity / future extension (e.g.
if you want an app-level thread record independent of the checkpointer)."""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class Thread(SQLModel, table=True):
    """A conversation thread record."""

    id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
