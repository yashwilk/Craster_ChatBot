"""LLM service with per-call retries and circular model fallback."""

import asyncio
import logging
from typing import Any, Callable, List, Optional, Type, TypeVar, Union, overload

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import BaseMessage
from openai import APIError, APITimeoutError, OpenAIError, RateLimitError
from pydantic import BaseModel
from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import logger
from app.services.llm.registry import LLMRegistry

T = TypeVar("T", bound=BaseModel)


class LLMService:
    """Wraps LLM calls with retries, circular fallback, and a total timeout budget."""

    def __init__(self):
        self._llm: Any = None
        self._current_model_index: int = 0
        self._bound_tools: List = []

        all_names = LLMRegistry.get_all_names()
        try:
            self._current_model_index = all_names.index(settings.DEFAULT_LLM_MODEL)
            self._llm = LLMRegistry.get(settings.DEFAULT_LLM_MODEL)
        except Exception:
            self._current_model_index = 0
            self._llm = LLMRegistry.LLMS[0]["llm"]
            logger.warning("default_model_not_found_using_first", requested=settings.DEFAULT_LLM_MODEL)

    @overload
    async def call(
        self,
        messages: LanguageModelInput,
        model_name: Optional[str] = ...,
        response_format: None = ...,
        **model_kwargs: Any,
    ) -> BaseMessage: ...
    @overload
    async def call(
        self,
        messages: LanguageModelInput,
        model_name: Optional[str] = ...,
        *,
        response_format: Type[T],
        **model_kwargs: Any,
    ) -> T: ...

    async def call(
        self,
        messages: LanguageModelInput,
        model_name: Optional[str] = None,
        response_format: Optional[Type[BaseModel]] = None,
        **model_kwargs: Any,
    ) -> Union[BaseMessage, BaseModel]:
        """Call the LLM with retries + fallback, bounded by a total timeout."""
        try:
            return await asyncio.wait_for(
                self._call_with_fallback(messages, model_name, response_format, model_kwargs),
                timeout=settings.LLM_TOTAL_TIMEOUT,
            )
        except asyncio.TimeoutError as err:
            raise RuntimeError(f"llm call timed out after {settings.LLM_TOTAL_TIMEOUT}s total budget") from err

    def get_llm(self) -> Any:
        """Return the current tool-bound default model instance."""
        return self._llm

    def bind_tools(self, tools: List) -> "LLMService":
        """Bind tools onto the default agent model."""
        if self._llm:
            self._bound_tools = tools
            self._llm = self._llm.bind_tools(tools)
        return self

    @retry(
        stop=stop_after_attempt(settings.MAX_LLM_CALL_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _invoke_with_retry(self, llm: Any, messages: LanguageModelInput) -> Any:
        try:
            return await llm.ainvoke(messages)
        except (RateLimitError, APITimeoutError, APIError):
            raise
        except OpenAIError as e:
            logger.error("llm_call_failed", error_type=type(e).__name__, error=str(e))
            raise

    def _switch_to_next_model(self) -> bool:
        try:
            next_index = (self._current_model_index + 1) % len(LLMRegistry.LLMS)
            next_entry = LLMRegistry.get_model_at_index(next_index)
            self._current_model_index = next_index
            self._llm = next_entry["llm"]
            if self._bound_tools:
                self._llm = self._llm.bind_tools(self._bound_tools)
            logger.warning("model_switched", new_model=next_entry["name"])
            return True
        except Exception as e:
            logger.error("model_switch_failed", error=str(e))
            return False

    async def _call_with_fallback(
        self, messages, model_name, response_format, model_kwargs
    ) -> Union[BaseMessage, BaseModel]:
        def _override_target(idx: int) -> Any:
            base = LLMRegistry.get(LLMRegistry.LLMS[idx]["name"], **model_kwargs)
            return base.with_structured_output(response_format) if response_format else base

        def _default_target(_: int) -> Any:
            return self._llm

        def _default_advance(_: int) -> Optional[int]:
            return self._current_model_index if self._switch_to_next_model() else None

        if model_name or response_format or model_kwargs:
            all_names = LLMRegistry.get_all_names()
            if model_name and model_name not in all_names:
                raise ValueError(f"model '{model_name}' not found. available: {', '.join(all_names)}")
            start = all_names.index(model_name) if model_name else self._current_model_index
            total = len(LLMRegistry.LLMS)
            get_target: Callable[[int], Any] = _override_target

            def _override_advance(idx: int) -> Optional[int]:
                return (idx + 1) % total

            advance: Callable[[int], Optional[int]] = _override_advance
        else:
            start = self._current_model_index
            get_target = _default_target
            advance = _default_advance

        return await self._fallback_loop(messages, start, get_target, advance)

    async def _fallback_loop(self, messages, start, get_target, advance) -> Any:
        total = len(LLMRegistry.LLMS)
        current = start
        models_tried = 0
        last_error: Optional[Exception] = None

        for models_tried in range(1, total + 1):
            current_name = LLMRegistry.LLMS[current]["name"]
            try:
                return await self._invoke_with_retry(get_target(current), messages)
            except OpenAIError as e:
                last_error = e
                logger.error("llm_call_failed_after_retries", model=current_name, models_tried=models_tried)
                if models_tried >= total:
                    break
                next_idx = advance(current)
                if next_idx is None:
                    break
                current = next_idx

        raise RuntimeError(f"failed to get response after trying {models_tried} models. last error: {last_error}")


llm_service = LLMService()
