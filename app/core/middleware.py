"""Custom ASGI middleware for metrics, logging context, and profiling.

Metrics: request count and request duration.
Logging context: attaches identifiers to logs.
Profiling: investigates slow requests and memory usage.
"""

import json
import time
import tracemalloc
from typing import Callable

from asgi_correlation_id import correlation_id
from fastapi import Request
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import settings
from app.core.logging import bind_context, clear_context, logger
from app.core.metrics import http_request_duration_seconds, http_requests_total

try:
    from pyinstrument import Profiler
    from pyinstrument.renderers import JSONRenderer

    PYINSTRUMENT_AVAILABLE = True
except ImportError:
    Profiler = None
    JSONRenderer = None
    PYINSTRUMENT_AVAILABLE = False


class MetricsMiddleware(BaseHTTPMiddleware):
    """Records HTTP request count/duration metrics."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.time() - start_time
            http_requests_total.labels(method=request.method, endpoint=request.url.path, status=status_code).inc()
            http_request_duration_seconds.labels(method=request.method, endpoint=request.url.path).observe(duration)


class LoggingContextMiddleware(BaseHTTPMiddleware):
    """Binds session_id/user_id (from the bearer token) into structlog context."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            clear_context()
            auth_header = request.headers.get("authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
                try:
                    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
                    if payload.get("sub"):
                        bind_context(session_id=payload["sub"])
                except JWTError:
                    pass
            response = await call_next(request)
            if hasattr(request.state, "user_id"):
                bind_context(user_id=request.state.user_id)
            return response
        finally:
            clear_context()


class ProfilingMiddleware(BaseHTTPMiddleware):
    """DEBUG-only per-request profiler. Saves a JSON flamegraph + memory
    report to PROFILING_DIR when a request exceeds PROFILING_THRESHOLD_SECONDS.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not PYINSTRUMENT_AVAILABLE:
            return await call_next(request)

        tracemalloc.start()
        cpu_start = time.process_time()
        profiler = Profiler(async_mode="enabled")
        with profiler:
            response = await call_next(request)

        cpu_ms = round((time.process_time() - cpu_start) * 1000, 2)
        mem_current_kb, mem_peak_kb = (v // 1024 for v in tracemalloc.get_traced_memory())
        snapshot = tracemalloc.take_snapshot()
        tracemalloc.stop()

        wall_ms = round((profiler.last_session.duration if profiler.last_session else 0.0) * 1000, 2)

        if wall_ms / 1000 >= settings.PROFILING_THRESHOLD_SECONDS:
            raw_id = correlation_id.get() or "unknown"
            settings.PROFILING_DIR.mkdir(parents=True, exist_ok=True)
            filepath = settings.PROFILING_DIR / f"{raw_id}.json"

            excluded = ("tracemalloc", "pyinstrument", "<frozen", "logging/__init__")
            top_allocs = [
                {
                    "file": str(stat.traceback[0].filename),
                    "line": stat.traceback[0].lineno,
                    "size_kb": round(stat.size / 1024, 2),
                    "count": stat.count,
                }
                for stat in snapshot.statistics("lineno")
                if not any(ex in str(stat.traceback[0].filename) for ex in excluded)
            ]
            report = {
                "request_id": raw_id,
                "endpoint": f"{request.method} {request.url.path}",
                "wall_time_ms": wall_ms,
                "cpu_time_ms": cpu_ms,
                "io_wait_ms": round(wall_ms - cpu_ms, 2),
                "memory_peak_kb": mem_peak_kb,
                "memory_allocated_kb": mem_current_kb,
                "top_memory_allocators": top_allocs[:20],
                "call_tree": json.loads(profiler.output(renderer=JSONRenderer())),
            }
            filepath.write_text(json.dumps(report, indent=2))
            logger.debug("slow_request_profile_saved", path=str(filepath), wall_time_ms=wall_ms)

        return response
