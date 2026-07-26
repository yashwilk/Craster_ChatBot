"""Base response schema shared by every endpoint."""

from uuid import UUID, uuid4

from asgi_correlation_id import correlation_id
from pydantic import BaseModel, Field


def _get_request_id() -> UUID:
    value = correlation_id.get()
    return UUID(value) if value else uuid4()


class BaseResponse(BaseModel):
    """Adds an auto-populated request_id to every response model."""

    request_id: UUID = Field(default_factory=_get_request_id)
