"""Registration, login, and session management endpoints."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import bind_context, logger
from app.models.session import Session
from app.models.user import User
from app.schemas.auth import SessionResponse, TokenResponse, UserCreate, UserResponse
from app.services.database import DatabaseService
from app.utils.auth import create_access_token, verify_token
from app.utils.sanitization import sanitize_email, sanitize_string, validate_password_strength


router = APIRouter()
security = HTTPBearer()
db_service = DatabaseService()


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    """FastAPI dependency: resolve the bearer token to a User row."""
    try:
        token = sanitize_string(credentials.credentials)
        user_id = verify_token(token)
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        user = await db_service.get_user(int(user_id))
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        bind_context(user_id=user.id)
        return user
    except ValueError as ve:
        raise HTTPException(status_code=422, detail="Invalid token format") from ve


async def get_current_session(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Session:
    """FastAPI dependency: resolve the bearer token to a chat Session row."""
    try:
        token = sanitize_string(credentials.credentials)
        session_id = verify_token(token)
        if session_id is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        session_id = sanitize_string(session_id)
        session = await db_service.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        bind_context(user_id=session.user_id)
        return session
    except ValueError as ve:
        raise HTTPException(status_code=422, detail="Invalid token format") from ve


@router.post("/register", response_model=UserResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["register"][0])
async def register_user(request: Request, user_data: UserCreate):
    """Create a new user account."""
    try:
        sanitized_email = sanitize_email(user_data.email)
        password = user_data.password.get_secret_value()
        validate_password_strength(password)

        if await db_service.get_user_by_email(sanitized_email):
            raise HTTPException(status_code=400, detail="Email already registered")

        sanitized_username = sanitize_string(user_data.username) if user_data.username else None
        user = await db_service.create_user(
            email=sanitized_email, password=User.hash_password(password), username=sanitized_username
        )
        token = create_access_token(str(user.id))
        return UserResponse(id=user.id, email=user.email, username=user.username, token=token)
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve)) from ve


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["login"][0])
async def login(
    request: Request, email: str = Form(...), password: str = Form(...), grant_type: str = Form(default="password")
):
    """Exchange email/password for an access token."""
    email = sanitize_string(email)
    password = sanitize_string(password)
    if sanitize_string(grant_type) != "password":
        raise HTTPException(status_code=400, detail="Unsupported grant type. Must be 'password'")

    user = await db_service.get_user_by_email(email)
    if not user or not user.verify_password(password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token.access_token, token_type="bearer", expires_at=token.expires_at)


@router.post("/session", response_model=SessionResponse)
async def create_session(user: User = Depends(get_current_user)):
    """Create a new chat session for the authenticated user."""
    session_id = str(uuid.uuid4())
    session = await db_service.create_session(session_id, user.id, username=user.username)
    token = create_access_token(session_id)
    logger.info("session_created", session_id=session_id, user_id=user.id)
    return SessionResponse(session_id=session_id, name=session.name, token=token)


@router.delete("/session/{session_id}")
async def delete_session(session_id: str, current_session: Session = Depends(get_current_session)):
    """Delete a chat session (must belong to the authenticated session)."""
    sanitized_session_id = sanitize_string(session_id)
    if sanitized_session_id != sanitize_string(current_session.id):
        raise HTTPException(status_code=403, detail="Cannot delete other sessions")
    await db_service.delete_session(sanitized_session_id)
    logger.info("session_deleted", session_id=session_id)


@router.patch("/session/{session_id}/name", response_model=SessionResponse)
async def update_session_name(
    session_id: str, name: str = Form(...), current_session: Session = Depends(get_current_session)
):
    """Rename a chat session (must belong to the authenticated session)."""
    sanitized_session_id = sanitize_string(session_id)
    if sanitized_session_id != sanitize_string(current_session.id):
        raise HTTPException(status_code=403, detail="Cannot modify other sessions")
    session = await db_service.update_session_name(sanitized_session_id, sanitize_string(name))
    token = create_access_token(sanitized_session_id)
    return SessionResponse(session_id=sanitized_session_id, name=session.name, token=token)


@router.get("/sessions", response_model=List[SessionResponse])
async def get_user_sessions(user: User = Depends(get_current_user)):
    """List all sessions for the authenticated user."""
    sessions = await db_service.get_user_sessions(user.id)
    return [
        SessionResponse(
            session_id=sanitize_string(s.id), name=sanitize_string(s.name), token=create_access_token(s.id)
        )
        for s in sessions
    ]
