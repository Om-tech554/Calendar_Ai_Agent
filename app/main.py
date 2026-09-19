"""
FastAPI application entry point.

Configures:
- Lifespan (startup/shutdown hooks)
- CORS
- Static file serving (Chat UI)
- Middleware (logging, rate limiting)
- Exception handlers
- API routers
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from app.api.middleware.logging import RequestLoggingMiddleware
from app.api.middleware.rate_limit import limiter
from app.api.routes import admin, agent, auth, health
from app.config import settings
from app.core.exceptions import CalendarAgentError, to_http_exception
from app.core.logging import get_logger, setup_logging
from app.db.database import connect_db, disconnect_db

# Setup logging before anything else
setup_logging()
logger = get_logger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info(
        "app_starting",
        env=settings.APP_ENV,
        model=settings.LLM_MODEL,
    )
    await connect_db()
    logger.info("app_ready", host=settings.APP_HOST, port=settings.APP_PORT)
    yield
    logger.info("app_shutting_down")
    await disconnect_db()
    logger.info("app_stopped")


# ── App Instance ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="📅 Calendar Agent API",
    description="Production-ready AI Calendar Agent powered by Gemini + Google Calendar",
    version="1.0.0",
    docs_url="/docs" if not settings.is_production else None,  # Disable Swagger in prod
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)

# ── State for SlowAPI ─────────────────────────────────────────────────────────
app.state.limiter = limiter


# ── CORS ──────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Custom Middleware ─────────────────────────────────────────────────────────

app.add_middleware(RequestLoggingMiddleware)


# ── Exception Handlers ────────────────────────────────────────────────────────

@app.exception_handler(CalendarAgentError)
async def domain_exception_handler(request: Request, exc: CalendarAgentError) -> JSONResponse:
    http_exc = to_http_exception(exc)
    return JSONResponse(status_code=http_exc.status_code, content={"detail": http_exc.detail})


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "detail": {
                "error": "RATE_LIMIT_EXCEEDED",
                "message": f"Too many requests. Limit: {settings.RATE_LIMIT_PER_MINUTE}/minute.",
            }
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_exception", error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": {"error": "INTERNAL_ERROR", "message": "An unexpected error occurred."}},
    )


# ── API Routers ───────────────────────────────────────────────────────────────

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(agent.router)
app.include_router(admin.router)


# ── Static Files (Chat & Admin UI) ────────────────────────────────────────────

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_ui() -> FileResponse:
        """Serve the Chat UI."""
        return FileResponse(str(STATIC_DIR / "index.html"))

    @app.get("/admin", include_in_schema=False)
    async def serve_admin_ui() -> FileResponse:
        """Serve the Admin Dashboard UI."""
        return FileResponse(str(STATIC_DIR / "admin.html"))

    @app.get("/privacy", include_in_schema=False)
    async def serve_privacy() -> FileResponse:
        """Serve the Privacy Policy page."""
        return FileResponse(str(STATIC_DIR / "privacy.html"))

    @app.get("/terms", include_in_schema=False)
    async def serve_terms() -> FileResponse:
        """Serve the Terms of Service page."""
        return FileResponse(str(STATIC_DIR / "terms.html"))
