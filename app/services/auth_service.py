"""
Google OAuth 2.0 service.

Handles:
- Generating OAuth authorization URLs
- Exchanging authorization codes for tokens
- Refreshing expired tokens
- Fetching user profile from Google
- Storing/loading encrypted tokens in MongoDB
"""

import urllib.parse
from datetime import datetime, timezone

import httpx
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build, Resource

from app.config import settings
from app.core.exceptions import OAuthTokenMissingError, UserNotFoundError
from app.core.logging import get_logger
from app.core.security import decrypt_token, encrypt_token
from app.db.models import OAuthToken, User

logger = get_logger(__name__)

GOOGLE_AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


# ── OAuth URL Generation ──────────────────────────────────────────────────────

def get_authorization_url(state: str) -> str:
    """Generate the Google OAuth2 authorization URL."""
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(settings.GOOGLE_OAUTH_SCOPES),
        "state": state,
        "access_type": "offline",      # Required for refresh token
        "prompt": "consent",           # Force consent to always get refresh token
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTH_BASE}?{urllib.parse.urlencode(params)}"


# ── Token Exchange ────────────────────────────────────────────────────────────

async def exchange_code_for_tokens(code: str) -> dict:
    """Exchange an authorization code for access + refresh tokens."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
        return response.json()


async def get_user_profile(access_token: str) -> dict:
    """Fetch the user's Google profile using their access token."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


# ── User Upsert ───────────────────────────────────────────────────────────────

async def upsert_user(profile: dict) -> User:
    """Create or update a user from their Google profile."""
    google_id = profile["sub"]
    existing = await User.find_one(User.google_id == google_id)

    if existing:
        existing.email = profile.get("email", existing.email)
        existing.name = profile.get("name", existing.name)
        existing.picture_url = profile.get("picture", existing.picture_url)
        existing.last_login_at = datetime.now(timezone.utc)
        await existing.save()
        logger.info("user_updated", user_id=existing.id, email=existing.email)
        return existing

    user = User(
        google_id=google_id,
        email=profile.get("email", ""),
        name=profile.get("name", ""),
        picture_url=profile.get("picture", ""),
    )
    await user.insert()
    logger.info("user_created", user_id=user.id, email=user.email)
    return user


async def save_oauth_tokens(user_id: str, token_data: dict) -> None:
    """Encrypt and persist OAuth tokens for a user."""
    expiry = None
    if "expires_in" in token_data:
        from datetime import timedelta
        expiry = datetime.now(timezone.utc) + timedelta(seconds=int(token_data["expires_in"]))

    existing = await OAuthToken.find_one(OAuthToken.user_id == user_id)

    if existing:
        existing.access_token_enc = encrypt_token(token_data["access_token"])
        if "refresh_token" in token_data:
            existing.refresh_token_enc = encrypt_token(token_data["refresh_token"])
        existing.token_expiry = expiry
        existing.scopes = token_data.get("scope", "").split()
        existing.updated_at = datetime.now(timezone.utc)
        await existing.save()
    else:
        oauth = OAuthToken(
            user_id=user_id,
            access_token_enc=encrypt_token(token_data["access_token"]),
            refresh_token_enc=encrypt_token(token_data.get("refresh_token", "")),
            token_expiry=expiry,
            scopes=token_data.get("scope", "").split(),
        )
        await oauth.insert()

    logger.info("oauth_tokens_saved", user_id=user_id)


# ── Calendar Service Builder ──────────────────────────────────────────────────

async def get_calendar_service(user_id: str) -> Resource:
    """
    Build an authenticated Google Calendar service for a user.
    Auto-refreshes expired tokens.
    """
    token_doc = await OAuthToken.find_one(OAuthToken.user_id == user_id)
    if not token_doc:
        raise OAuthTokenMissingError()

    access_token = decrypt_token(token_doc.access_token_enc)
    refresh_token = decrypt_token(token_doc.refresh_token_enc) if token_doc.refresh_token_enc else None

    credentials = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=GOOGLE_TOKEN_URL,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=settings.GOOGLE_OAUTH_SCOPES,
    )

    # Refresh if expired
    if credentials.expired and credentials.refresh_token:
        logger.info("oauth_token_refreshing", user_id=user_id)
        credentials.refresh(GoogleRequest())

        # Save refreshed tokens
        await save_oauth_tokens(user_id, {
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "expires_in": 3600,
            "scope": " ".join(settings.GOOGLE_OAUTH_SCOPES),
        })

    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


async def get_user_by_id(user_id: str) -> User:
    """Fetch a user by internal ID."""
    user = await User.get(user_id)
    if not user:
        raise UserNotFoundError(user_id)
    return user
