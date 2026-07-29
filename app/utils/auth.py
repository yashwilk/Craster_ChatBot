"""JWT creation/verification."""

import re
from datetime import UTC, datetime, timedelta
from typing import Optional

from jose import JWTError, jwt

from app.core.config import settings
from app.core.logging import logger
from app.schemas.auth import Token
from app.utils.sanitization import sanitize_string


def create_access_token(thread_id: str, expires_delta: Optional[timedelta] = None) -> Token:
    """Mint a JWT whose `sub` claim is the given thread/session id."""
    expire = datetime.now(UTC) + (expires_delta or timedelta(days=settings.JWT_ACCESS_TOKEN_EXPIRE_DAYS))
    to_encode = {
        "sub": thread_id,
        "exp": expire,
        "iat": datetime.now(UTC),
        "jti": sanitize_string(f"{thread_id}-{datetime.now(UTC).timestamp()}"),
    }
    encoded = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    logger.info("token_created", thread_id=thread_id, expires_at=expire.isoformat())
    return Token(access_token=encoded, expires_at=expire)


def verify_token(token: str) -> Optional[str]:
    """Decode a JWT and return its `sub` claim, or None if missing/invalid."""
    if not token or not isinstance(token, str):
        raise ValueError("Token must be a non-empty string")
    if not re.match(r"^[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+$", token):
        raise ValueError("Token format is invalid - expected JWT format")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError as e:
        logger.error("token_verification_failed", error=str(e))
        return None
