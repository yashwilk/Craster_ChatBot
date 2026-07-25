"""Structured logging setup using structlog."""

import logging
import sys
from contextvars import ContextVar
from typing import Any, Dict, Optional

import structlog
from asgi_correlation_id import correlation_id

from app.core.config import settings

settings.LOG_DIR.mkdir(parents=True, exist_ok=True)

_request_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar("request_context", default=None)


def bind_context(**kwargs: Any) -> None:
    """Bind key/value pairs to the current request's logging context."""
    current = _request_context.get() or {}
    _request_context.set({**current, **kwargs})


def clear_context() -> None:
    """Clear the logging context for the current request."""
    _request_context.set(None)


def get_context() -> Dict[str, Any]:
    """Return the current logging context dict."""
    return _request_context.get() or {}


def _add_context(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    event_dict.update(get_context())
    return event_dict


def _add_request_id(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    request_id = correlation_id.get()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict


def setup_logging() -> None:
    """Configure structlog: pretty console in dev, JSON in staging/prod."""
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO
    logging.basicConfig(format="%(message)s", level=log_level, handlers=[logging.StreamHandler(sys.stdout)])

    shared_processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        _add_context,
        _add_request_id,
        lambda _, __, ed: {**ed, "environment": settings.ENVIRONMENT.value},
    ]

    renderer = (
        structlog.dev.ConsoleRenderer() if settings.LOG_FORMAT == "console" else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


setup_logging()
logger = structlog.get_logger()
logger.info("logging_initialized", environment=settings.ENVIRONMENT.value, log_format=settings.LOG_FORMAT)
