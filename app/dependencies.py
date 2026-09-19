"""
FastAPI dependency injection helpers.

Provides:
- get_current_user_id: Extract and validate JWT from Authorization header
- get_current_user: Full User document from DB
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import to_http_exception
from app.core.exceptions import AuthError, InvalidTokenError, TokenExpiredError
from app.core.security import get_user_id_from_token
from app.db.models import User
from app.services.auth_service import get_user_by_id

# Bearer token scheme (reads Authorization: Bearer <token>)
_bearer = HTTPBearer(auto_error=False)


async def get_current_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """
    Extract the user_id from the JWT Bearer token.
    Injects user_id into request.state for rate-limiting middleware.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "AUTH_REQUIRED", "message": "Authentication required."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = get_user_id_from_token(credentials.credentials)
        request.state.user_id = user_id  # For rate limiter
        return user_id
    except (TokenExpiredError, InvalidTokenError, AuthError) as exc:
        raise to_http_exception(exc)


async def get_current_user(
    user_id: str = Depends(get_current_user_id),
) -> User:
    """Get the full User document for the current authenticated user."""
    try:
        return await get_user_by_id(user_id)
    except Exception as exc:
        from app.core.exceptions import CalendarAgentError
        if isinstance(exc, CalendarAgentError):
            raise to_http_exception(exc)
        raise HTTPException(status_code=500, detail="Failed to fetch user")


def is_admin_user(user: User) -> bool:
    """Check if a user has admin privileges either via ADMIN_EMAILS config or database role."""
    from app.config import settings
    admin_emails = [e.lower().strip() for e in settings.ADMIN_EMAILS]
    return user.email.lower().strip() in admin_emails or getattr(user, "role", "user") == "admin"


async def get_current_admin_user(
    user: User = Depends(get_current_user),
) -> User:
    """Verify that the current user is an administrator."""
    if not is_admin_user(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "ADMIN_REQUIRED", "message": "Admin privileges required to access this resource."},
        )
    return user


# Type alias for cleaner route signatures
CurrentUser = Depends(get_current_user)
CurrentUserId = Depends(get_current_user_id)
CurrentAdminUser = Depends(get_current_admin_user)
