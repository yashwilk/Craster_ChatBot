"""Auth request/response schemas."""

import re
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, SecretStr, field_validator

from app.schemas.base import BaseResponse


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class TokenResponse(BaseResponse):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=8, max_length=64)
    username: str | None = Field(default=None, max_length=50)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: SecretStr) -> SecretStr:
        password = v.get_secret_value()
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", password):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", password):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"[0-9]", password):
            raise ValueError("Password must contain at least one number")
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            raise ValueError("Password must contain at least one special character")
        return v


class UserResponse(BaseResponse):
    id: int
    email: str
    username: str | None = None
    token: Token


class SessionResponse(BaseResponse):
    session_id: str
    name: str = Field(default="", max_length=100)
    token: Token

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        return re.sub(r'[<>{}\[\]()\'"`]', "", v)
