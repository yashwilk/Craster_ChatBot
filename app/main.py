"""Application entry point."""

from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from asgi_correlation_id import CorrelationIdMiddleware

from app.api.v1.api import api_router
from app.api.v1.chatbot import agent
from app.core.cache import cache_service
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import logger
from app.core.metrics import setup_metrics
from app.core.middleware import LoggingContextMiddleware, MetricsMiddleware, ProfilingMiddleware
from app.core.observability import langfuse_init
from app.services.database import database_service
from app.services.memory import memory_service

load_dotenv()
langfuse_init()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm cache, graph, and memory connections at startup; clean up on shutdown."""
    logger.info("application_startup", project_name=settings.PROJECT_NAME, environment=settings.ENVIRONMENT.value)

    try:
        await cache_service.initialize()
    except Exception as e:
        logger.exception("cache_initialization_failed", error=str(e))

    try:
        await agent.create_graph()
        logger.info("graph_pre_warmed")
    except Exception as e:
        logger.exception("graph_pre_warm_failed", error=str(e))

    try:
        await memory_service.initialize()
    except Exception as e:
        logger.exception("memory_service_pre_warm_failed", error=str(e))

    yield

    await cache_service.close()
    if agent._connection_pool:
        await agent._connection_pool.close()
    logger.info("application_shutdown")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

setup_metrics(app)
app.add_middleware(LoggingContextMiddleware)
app.add_middleware(MetricsMiddleware)
if settings.DEBUG:
    app.add_middleware(ProfilingMiddleware)
app.add_middleware(CorrelationIdMiddleware)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return a friendlier 422 payload for validation errors."""
    formatted_errors = [
        {"field": " -> ".join(str(p) for p in error["loc"] if p != "body"), "message": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": "Validation error", "errors": formatted_errors})


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["root"][0])
async def root(request: Request):
    """Basic API info."""
    return {"name": settings.PROJECT_NAME, "version": settings.VERSION, "status": "healthy", "swagger_url": "/docs"}


@app.get("/health")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["health"][0])
async def health_check(request: Request) -> JSONResponse:
    """Report DB health; returns 503 so load balancers can drop unhealthy instances."""
    db_healthy = await database_service.health_check()
    return JSONResponse(
        content={
            "status": "healthy" if db_healthy else "degraded",
            "components": {"api": "healthy", "database": "healthy" if db_healthy else "unhealthy"},
            "timestamp": datetime.now().isoformat(),
        },
        status_code=status.HTTP_200_OK if db_healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
