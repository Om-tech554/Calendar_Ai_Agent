"""
MongoDB document models using Beanie ODM.

Collections:
- users           → User profiles
- oauth_tokens    → Encrypted Google OAuth tokens (per user)
- chat_sessions   → Conversation sessions
- chat_messages   → Individual messages in sessions
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from beanie import Document, Indexed
from pydantic import Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


# ── User ──────────────────────────────────────────────────────────────────────

class User(Document):
    """Represents a logged-in user (authenticated via Google OAuth)."""

    id: str = Field(default_factory=new_id)                     # Our internal ID
    google_id: Indexed(str, unique=True) = ""                   # Google sub claim  # type: ignore[valid-type]
    email: Indexed(str, unique=True) = ""                       # type: ignore[valid-type]
    name: str = ""
    picture_url: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    last_login_at: datetime = Field(default_factory=utcnow)
    role: str = "user"                                          # "admin" | "user"
    is_active: bool = True

    class Settings:
        name = "users"
        indexes = [
            [("google_id", 1)],
            [("email", 1)],
        ]


# ── OAuth Token ───────────────────────────────────────────────────────────────

class OAuthToken(Document):
    """Stores encrypted Google OAuth tokens per user."""

    id: str = Field(default_factory=new_id)
    user_id: Indexed(str, unique=True) = ""                     # type: ignore[valid-type]
    access_token_enc: str = ""                                  # Fernet encrypted
    refresh_token_enc: str = ""                                 # Fernet encrypted
    token_expiry: Optional[datetime] = None
    scopes: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "oauth_tokens"
        indexes = [
            [("user_id", 1)],
        ]


# ── Chat Session ──────────────────────────────────────────────────────────────

class ChatSession(Document):
    """A conversation session between a user and the agent."""

    id: str = Field(default_factory=new_id)
    user_id: Indexed(str) = ""                                  # type: ignore[valid-type]
    title: str = "New Chat"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    message_count: int = 0
    is_active: bool = True

    class Settings:
        name = "chat_sessions"
        indexes = [
            [("user_id", 1), ("updated_at", -1)],
        ]


# ── Chat Message ──────────────────────────────────────────────────────────────

class ChatMessage(Document):
    """An individual message within a chat session."""

    id: str = Field(default_factory=new_id)
    session_id: Indexed(str) = ""                               # type: ignore[valid-type]
    user_id: Indexed(str) = ""                                  # type: ignore[valid-type]
    role: str = "user"                                          # "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list[dict] = Field(default_factory=list)        # LLM tool call records
    timestamp: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "chat_messages"
        indexes = [
            [("session_id", 1), ("timestamp", 1)],
        ]
