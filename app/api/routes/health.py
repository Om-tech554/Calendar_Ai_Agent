"""
Health check routes.

GET /health  — Liveness probe (is the app running?)
GET /ready   — Readiness probe (is the DB connected?)
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.db.database import ping_db

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    env: str
    version: str = "1.0.0"


class ReadyResponse(BaseModel):
    status: str
    database: str


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
async def health() -> HealthResponse:
    """Returns 200 if the app is alive."""
    return HealthResponse(status="ok", env=settings.APP_ENV)


@router.get("/ready", response_model=ReadyResponse, summary="Readiness check")
async def ready() -> ReadyResponse:
    """Returns 200 if the app and all dependencies are ready."""
    db_ok = await ping_db()
    return ReadyResponse(
        status="ready" if db_ok else "degraded",
        database="connected" if db_ok else "unreachable",
    )
