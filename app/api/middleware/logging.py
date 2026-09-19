"""
Request/Response logging middleware.

Logs every request with:
- Method, path, status code, duration
- A unique request_id (for tracing across logs)
- User ID (if authenticated)
"""

import time
import uuid

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = structlog.get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs all HTTP requests with timing and request ID."""

    SKIP_PATHS = {"/health", "/ready", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip health checks
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        request_id = str(uuid.uuid4())[:8]
        start = time.perf_counter()

        # Bind request context to all log messages in this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        # Attach request_id to request state for downstream use
        request.state.request_id = request_id

        logger.info(
            "request_started",
            client=request.client.host if request.client else "unknown",
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error("request_unhandled_error", error=str(exc), exc_info=True)
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        logger.info(
            "request_completed",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        # Inject request_id into response header for client-side debugging
        response.headers["X-Request-ID"] = request_id
        return response
