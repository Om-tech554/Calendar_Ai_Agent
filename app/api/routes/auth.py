"""
OAuth 2.0 authentication routes.

GET  /auth/login      — Redirect to Google OAuth consent screen
GET  /auth/callback   — Handle Google's redirect, create session, return JWT
GET  /auth/me         — Get current user profile
POST /auth/logout     — Invalidate session (client clears token)
"""

import secrets

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.core.logging import get_logger
from app.core.security import create_access_token
from app.dependencies import CurrentUser
from app.db.models import User
from app.services.auth_service import (
    exchange_code_for_tokens,
    get_authorization_url,
    get_user_profile,
    save_oauth_tokens,
    upsert_user,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = get_logger(__name__)

# In-memory state store (use Redis for multi-instance production deployments)
_oauth_states: dict[str, bool] = {}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_name: str
    user_email: str
    user_picture: str


class UserProfile(BaseModel):
    id: str
    name: str
    email: str
    picture_url: str
    role: str = "user"
    is_admin: bool = False


@router.get("/login", summary="Start Google OAuth flow")
async def login(request: Request) -> RedirectResponse:
    """Generate Google OAuth URL and redirect the user to it."""
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = True  # CSRF protection

    auth_url = get_authorization_url(state)
    logger.info("oauth_login_started")
    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


@router.get("/callback", summary="Handle Google OAuth callback")
async def callback(
    code: str = Query(..., description="Authorization code from Google"),
    state: str = Query(..., description="CSRF state token"),
    error: str | None = Query(None),
) -> TokenResponse:
    """
    Exchange authorization code for tokens, create/update user, return JWT.
    """
    # Handle OAuth errors (e.g., user denied access)
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "OAUTH_DENIED", "message": f"Google OAuth error: {error}"},
        )

    # Validate CSRF state
    if state not in _oauth_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_STATE", "message": "Invalid OAuth state. Please try again."},
        )
    del _oauth_states[state]

    # Exchange code for tokens
    try:
        token_data = await exchange_code_for_tokens(code)
    except Exception as exc:
        logger.error("token_exchange_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "TOKEN_EXCHANGE_FAILED", "message": "Failed to exchange code for tokens."},
        )

    # Get user profile from Google
    profile = await get_user_profile(token_data["access_token"])

    # Upsert user in MongoDB
    user = await upsert_user(profile)

    # Save encrypted OAuth tokens
    await save_oauth_tokens(user.id, token_data)

    # Issue our own JWT
    jwt_token = create_access_token({"sub": user.id, "email": user.email})

    logger.info("user_authenticated", user_id=user.id, email=user.email)

    # Redirect to frontend with token in URL param (JS picks it up and stores in localStorage)
    return RedirectResponse(
        url=f"/?token={jwt_token}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/me", response_model=UserProfile, summary="Get current user profile")
async def get_me(current_user: User = CurrentUser) -> UserProfile:
    """Return the authenticated user's profile."""
    from app.dependencies import is_admin_user
    is_admin = is_admin_user(current_user)
    effective_role = "admin" if is_admin else getattr(current_user, "role", "user")
    return UserProfile(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        picture_url=current_user.picture_url,
        role=effective_role,
        is_admin=is_admin,
    )


@router.post("/logout", summary="Logout (client should clear token)")
async def logout(current_user: User = CurrentUser) -> dict:
    """
    Logout endpoint. Since we use stateless JWTs, the client must clear
    the token. For token revocation, implement a blocklist with Redis.
    """
    logger.info("user_logged_out", user_id=current_user.id)
    return {"message": "Logged out successfully. Please clear your token."}
