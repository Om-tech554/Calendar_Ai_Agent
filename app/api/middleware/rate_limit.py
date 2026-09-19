"""
Sliding-window rate limiter using SlowAPI (backed by in-memory storage).

For production at scale, swap the default MemoryStorage for Redis:
    from slowapi.util import get_remote_address
    from slowapi import Limiter
    limiter = Limiter(key_func=get_user_id, storage_uri="redis://localhost:6379")
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings


def _get_user_id_or_ip(request: Request) -> str:
    """
    Rate-limit key: use authenticated user_id if available, otherwise fall back to IP.
    """
    # JWT user_id is injected into request.state by the auth dependency
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return get_remote_address(request)


# Global limiter instance — imported and registered in main.py
limiter = Limiter(
    key_func=_get_user_id_or_ip,
    default_limits=[f"{settings.RATE_LIMIT_PER_MINUTE}/minute"],
)
