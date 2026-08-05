"""API v1 router — mounts auth + chatbot sub-routers."""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.chatbot import router as chatbot_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["Auth"])
api_router.include_router(chatbot_router, prefix="/chatbot", tags=["Chatbot"])


@api_router.get("/health")
async def health_check():
    """Lightweight liveness check for the v1 API."""
    return {"status": "healthy", "version": "1.0.0"}
