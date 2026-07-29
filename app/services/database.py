"""Database service for Users and Sessions."""

from typing import List, Optional
from urllib.parse import quote_plus

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool
from sqlmodel import Session, col, create_engine, select

from app.core.config import Environment, settings
from app.core.logging import logger
from app.models.session import Session as ChatSession
from app.models.user import User


class DatabaseService:
    """CRUD operations for Users and chat Sessions."""

    def __init__(self):
        try:
            connection_url = (
                f"postgresql://{quote_plus(settings.POSTGRES_USER)}:{quote_plus(settings.POSTGRES_PASSWORD)}"
                f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            )
            self.engine = create_engine(
                connection_url,
                pool_pre_ping=True,
                poolclass=QueuePool,
                pool_size=settings.POSTGRES_POOL_SIZE,
                max_overflow=settings.POSTGRES_MAX_OVERFLOW,
                pool_timeout=30,
                pool_recycle=1800,
            )
            logger.info("database_initialized", environment=settings.ENVIRONMENT.value)
        except SQLAlchemyError as e:
            logger.error("database_initialization_error", error=str(e))
            if settings.ENVIRONMENT != Environment.PRODUCTION:
                raise

    async def create_user(self, email: str, password: str, username: str | None = None) -> User:
        """Insert a new user row."""
        with Session(self.engine) as session:
            user = User(email=email, hashed_password=password, username=username)
            session.add(user)
            session.commit()
            session.refresh(user)
            logger.info("user_created", email=email)
            return user

    async def get_user(self, user_id: int) -> Optional[User]:
        """Fetch a user by primary key."""
        with Session(self.engine) as session:
            return session.get(User, user_id)

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Fetch a user by email."""
        with Session(self.engine) as session:
            return session.exec(select(User).where(User.email == email)).first()

    async def create_session(
        self, session_id: str, user_id: int, name: str = "", username: str | None = None
    ) -> ChatSession:
        """Insert a new chat session row."""
        with Session(self.engine) as session:
            chat_session = ChatSession(id=session_id, user_id=user_id, name=name, username=username)
            session.add(chat_session)
            session.commit()
            session.refresh(chat_session)
            logger.info("session_created", session_id=session_id, user_id=user_id)
            return chat_session

    async def delete_session(self, session_id: str) -> bool:
        """Delete a chat session by id."""
        with Session(self.engine) as session:
            chat_session = session.get(ChatSession, session_id)
            if not chat_session:
                return False
            session.delete(chat_session)
            session.commit()
            return True

    async def get_session(self, session_id: str) -> Optional[ChatSession]:
        """Fetch a chat session by id."""
        with Session(self.engine) as session:
            return session.get(ChatSession, session_id)

    async def get_user_sessions(self, user_id: int) -> List[ChatSession]:
        """Fetch all sessions for a user, oldest first."""
        with Session(self.engine) as session:
            stmt = select(ChatSession).where(col(ChatSession.user_id) == user_id).order_by(col(ChatSession.created_at))
            return list(session.exec(stmt).all())

    async def update_session_name(self, session_id: str, name: str) -> ChatSession:
        """Rename a chat session."""
        with Session(self.engine) as session:
            chat_session = session.get(ChatSession, session_id)
            if not chat_session:
                raise HTTPException(status_code=404, detail="Session not found")
            chat_session.name = name
            session.add(chat_session)
            session.commit()
            session.refresh(chat_session)
            return chat_session

    async def health_check(self) -> bool:
        """Return True if the database is reachable."""
        try:
            with Session(self.engine) as session:
                session.exec(select(1)).first()
                return True
        except Exception as e:
            logger.error("database_health_check_failed", error=str(e))
            return False


database_service = DatabaseService()
