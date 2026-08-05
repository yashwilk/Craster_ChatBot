"""Chat endpoints: send a message, stream a reply, fetch/clear history."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.v1.auth import get_current_session
from app.core.config import settings
from app.core.langgraph.graph import LangGraphAgent
from app.core.limiter import limiter
from app.core.logging import logger
from app.core.metrics import llm_stream_duration_seconds
from app.models.session import Session
from app.schemas.chat import ChatRequest, ChatResponse, StreamResponse
from app.services.session_naming import maybe_name_session

router = APIRouter()
agent = LangGraphAgent()


@router.post("/chat", response_model=ChatResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["chat"][0])
async def chat(request: Request, chat_request: ChatRequest, session: Session = Depends(get_current_session)):
    """Send a message and get the full reply back."""
    try:
        if settings.SESSION_NAMING_ENABLED:
            maybe_name_session(session.id, session.name, chat_request.messages)
        result = await agent.get_response(
            chat_request.messages, session.id, user_id=str(session.user_id), username=session.username
        )
        return ChatResponse(messages=result)
    except Exception as e:
        logger.exception("chat_request_failed", session_id=session.id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/chat/stream")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["chat_stream"][0])
async def chat_stream(request: Request, chat_request: ChatRequest, session: Session = Depends(get_current_session)):
    """Send a message and stream the reply back as server-sent events."""
    if settings.SESSION_NAMING_ENABLED:
        maybe_name_session(session.id, session.name, chat_request.messages)

    async def event_generator():
        try:
            with llm_stream_duration_seconds.labels(model=agent.llm_service.get_llm().get_name()).time():
                async for chunk in agent.get_stream_response(
                    chat_request.messages, session.id, user_id=str(session.user_id), username=session.username
                ):
                    yield f"data: {json.dumps(StreamResponse(content=chunk, done=False).model_dump(mode='json'))}\n\n"
            yield f"data: {json.dumps(StreamResponse(content='', done=True).model_dump(mode='json'))}\n\n"
        except Exception as e:
            logger.exception("stream_chat_request_failed", session_id=session.id, error=str(e))
            yield f"data: {json.dumps(StreamResponse(content=str(e), done=True).model_dump(mode='json'))}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/messages", response_model=ChatResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["messages"][0])
async def get_session_messages(request: Request, session: Session = Depends(get_current_session)):
    """Fetch all messages for the current session."""
    try:
        return ChatResponse(messages=await agent.get_chat_history(session.id))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/messages")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["messages"][0])
async def clear_chat_history(request: Request, session: Session = Depends(get_current_session)):
    """Clear all messages for the current session."""
    try:
        await agent.clear_chat_history(session.id)
        return {"message": "Chat history cleared successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
