"""Chat request/response schemas."""

import re
from typing import List, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import BaseResponse


class Message(BaseModel):
    model_config = {"extra": "ignore"}

    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=3000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if re.search(r"<script.*?>.*?</script>", v, re.IGNORECASE | re.DOTALL):
            raise ValueError("Content contains potentially harmful script tags")
        if "\0" in v:
            raise ValueError("Content contains null bytes")
        return v


class ChatRequest(BaseModel):
    messages: List[Message] = Field(min_length=1)


class ChatResponse(BaseResponse):
    messages: List[Message]


class StreamResponse(BaseResponse):
    content: str = ""
    done: bool = False


class SessionTitle(BaseModel):
    """Structured output schema for LLM-generated session titles."""

    title: str = Field(min_length=1, max_length=60)

    @field_validator("title")
    @classmethod
    def _normalize(cls, v: str) -> str:
        v = " ".join(v.split()).strip(" \"'`.,:;!?-")
        if not v:
            raise ValueError("empty title after normalization")
        return v
