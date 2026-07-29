"""Message trimming and LLM content normalization helpers."""

import tiktoken
from langchain_core.messages import BaseMessage
from langchain_core.messages import trim_messages as _trim_messages

from app.core.config import settings
from app.core.logging import logger
from app.schemas import Message

try:
    _TIKTOKEN_ENCODING = tiktoken.encoding_for_model(settings.DEFAULT_LLM_MODEL)
except KeyError:
    _TIKTOKEN_ENCODING = tiktoken.get_encoding("cl100k_base")


def _count_tokens_tiktoken(messages: list) -> int:
    """Count tokens locally with tiktoken (no API round-trip)."""
    num_tokens = 0
    for message in messages:
        num_tokens += 4
        if isinstance(message, dict):
            for _, value in message.items():
                if isinstance(value, str):
                    num_tokens += len(_TIKTOKEN_ENCODING.encode(value))
        elif isinstance(message, BaseMessage):
            content = message.content
            if isinstance(content, str):
                num_tokens += len(_TIKTOKEN_ENCODING.encode(content))
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, str):
                        num_tokens += len(_TIKTOKEN_ENCODING.encode(block))
                    elif isinstance(block, dict) and "text" in block:
                        num_tokens += len(_TIKTOKEN_ENCODING.encode(block["text"]))
    return num_tokens + 2


def dump_messages(messages: list[Message]) -> list[dict]:
    """Convert Message models to plain dicts for the LLM."""
    return [m.model_dump() for m in messages]


def extract_text_content(content: str | list) -> str:
    """Extract plain text from either a plain string or a structured content-block list."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


def process_llm_response(response: BaseMessage) -> BaseMessage:
    """Normalize response.content to a plain string regardless of provider format."""
    if isinstance(response.content, list):
        response.content = extract_text_content(response.content)
    return response


def prepare_messages(messages: list[Message], system_prompt: str) -> list[Message]:
    """Trim history to fit the token budget and prepend the system prompt."""
    try:
        trimmed = _trim_messages(
            dump_messages(messages),
            strategy="last",
            token_counter=_count_tokens_tiktoken,
            max_tokens=settings.MAX_TOKENS,
            start_on="human",
            include_system=False,
            allow_partial=False,
        )
    except ValueError as e:
        if "Unrecognized content block type" in str(e):
            logger.warning("token_counting_failed_skipping_trim", error=str(e))
            trimmed = messages
        else:
            raise
    return [Message(role="system", content=system_prompt)] + trimmed
