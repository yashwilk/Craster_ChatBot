"""Rate limiting via slowapi, backed by Valkey when configured (multi-instance safe)."""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.logging import logger

_storage_uri = None
if settings.VALKEY_HOST:
    _password_part = f":{settings.VALKEY_PASSWORD}@" if settings.VALKEY_PASSWORD else ""
    _storage_uri = f"redis://{_password_part}{settings.VALKEY_HOST}:{settings.VALKEY_PORT}/{settings.VALKEY_DB}"
    logger.info("rate_limiter_using_valkey", host=settings.VALKEY_HOST)

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=settings.RATE_LIMIT_DEFAULT,
    storage_uri=_storage_uri,
)
