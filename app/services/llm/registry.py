"""Registry of pre-initialized LLM instances."""

from typing import Any, Dict, List

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.core.config import settings

_TOKEN_LIMIT: Dict[str, Any] = {"max_completion_tokens": settings.MAX_TOKENS}
_API_KEY = SecretStr(settings.OPENAI_API_KEY)


class LLMRegistry:
    """Ordered list of available models; order defines circular fallback order."""

    LLMS: List[Dict[str, Any]] = [
        {
            "name": "gpt-5-mini",
            "llm": ChatOpenAI(
                model="gpt-5-mini", api_key=_API_KEY, model_kwargs=_TOKEN_LIMIT, reasoning={"effort": "low"}
            ),
        },
        {
            "name": "gpt-5",
            "llm": ChatOpenAI(
                model="gpt-5", api_key=_API_KEY, model_kwargs=_TOKEN_LIMIT, reasoning={"effort": "medium"}
            ),
        },
        {
            "name": "gpt-5-nano",
            "llm": ChatOpenAI(
                model="gpt-5-nano", api_key=_API_KEY, model_kwargs=_TOKEN_LIMIT, reasoning={"effort": "low"}
            ),
        },
    ]

    @classmethod
    def get(cls, model_name: str, **kwargs) -> BaseChatModel:
        """Return the shared instance, or a fresh one if kwargs override defaults."""
        entry = next((e for e in cls.LLMS if e["name"] == model_name), None)
        if not entry:
            available = ", ".join(e["name"] for e in cls.LLMS)
            raise ValueError(f"model '{model_name}' not found. available: {available}")
        if kwargs:
            return ChatOpenAI(model=model_name, api_key=_API_KEY, **kwargs)
        return entry["llm"]

    @classmethod
    def get_all_names(cls) -> List[str]:
        """Return every registered model name, in order."""
        return [e["name"] for e in cls.LLMS]

    @classmethod
    def get_model_at_index(cls, index: int) -> Dict[str, Any]:
        """Return the model entry at index, wrapping to 0 if out of range."""
        if 0 <= index < len(cls.LLMS):
            return cls.LLMS[index]
        return cls.LLMS[0]
