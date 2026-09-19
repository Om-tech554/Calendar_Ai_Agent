"""
Custom exception hierarchy for the Calendar Agent.

All exceptions map to specific HTTP status codes and error codes.
"""

from fastapi import HTTPException, status


class CalendarAgentError(Exception):
    """Base exception for all Calendar Agent errors."""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


# ── Auth Exceptions ────────────────────────────────────────────────────────────

class AuthError(CalendarAgentError):
    """Authentication/authorization failure."""

    def __init__(self, message: str = "Authentication failed", code: str = "AUTH_ERROR") -> None:
        super().__init__(message, code)


class TokenExpiredError(AuthError):
    """JWT or OAuth token has expired."""

    def __init__(self) -> None:
        super().__init__("Token has expired. Please log in again.", "TOKEN_EXPIRED")


class InvalidTokenError(AuthError):
    """JWT token is invalid or malformed."""

    def __init__(self) -> None:
        super().__init__("Invalid authentication token.", "INVALID_TOKEN")


class UserNotFoundError(AuthError):
    """User does not exist in the database."""

    def __init__(self, user_id: str = "") -> None:
        msg = f"User '{user_id}' not found." if user_id else "User not found."
        super().__init__(msg, "USER_NOT_FOUND")


class OAuthTokenMissingError(AuthError):
    """User has not connected their Google Calendar."""

    def __init__(self) -> None:
        super().__init__(
            "Google Calendar not connected. Please authenticate via /auth/login.",
            "OAUTH_TOKEN_MISSING",
        )


# ── Calendar Exceptions ────────────────────────────────────────────────────────

class CalendarError(CalendarAgentError):
    """Google Calendar API error."""

    def __init__(self, message: str, code: str = "CALENDAR_ERROR") -> None:
        super().__init__(message, code)


class EventNotFoundError(CalendarError):
    """Calendar event does not exist."""

    def __init__(self, event_id: str) -> None:
        super().__init__(f"Event '{event_id}' not found.", "EVENT_NOT_FOUND")


class CalendarPermissionError(CalendarError):
    """Insufficient permissions for calendar operation."""

    def __init__(self) -> None:
        super().__init__(
            "Insufficient permissions to access this calendar.", "CALENDAR_PERMISSION"
        )


class CalendarRateLimitError(CalendarError):
    """Google Calendar API rate limit exceeded."""

    def __init__(self) -> None:
        super().__init__(
            "Google Calendar API rate limit exceeded. Please try again later.",
            "CALENDAR_RATE_LIMIT",
        )


class EventConflictError(CalendarError):
    """Scheduling conflict detected."""

    def __init__(self, conflicting_event: str = "") -> None:
        msg = f"Time conflict with: {conflicting_event}" if conflicting_event else "Scheduling conflict detected."
        super().__init__(msg, "EVENT_CONFLICT")


# ── Agent Exceptions ───────────────────────────────────────────────────────────

class AgentError(CalendarAgentError):
    """LLM agent error."""

    def __init__(self, message: str = "Agent processing failed.", code: str = "AGENT_ERROR") -> None:
        super().__init__(message, code)


class AgentTimeoutError(AgentError):
    """Agent took too long to respond."""

    def __init__(self) -> None:
        super().__init__("Agent response timed out. Please try again.", "AGENT_TIMEOUT")


# ── Database Exceptions ────────────────────────────────────────────────────────

class DatabaseError(CalendarAgentError):
    """Database operation failure."""

    def __init__(self, message: str = "Database error occurred.") -> None:
        super().__init__(message, "DB_ERROR")


# ── HTTP Exception Mappers ─────────────────────────────────────────────────────

EXCEPTION_TO_HTTP: dict[type[CalendarAgentError], int] = {
    AuthError: status.HTTP_401_UNAUTHORIZED,
    TokenExpiredError: status.HTTP_401_UNAUTHORIZED,
    InvalidTokenError: status.HTTP_401_UNAUTHORIZED,
    UserNotFoundError: status.HTTP_404_NOT_FOUND,
    OAuthTokenMissingError: status.HTTP_401_UNAUTHORIZED,
    CalendarError: status.HTTP_502_BAD_GATEWAY,
    EventNotFoundError: status.HTTP_404_NOT_FOUND,
    CalendarPermissionError: status.HTTP_403_FORBIDDEN,
    CalendarRateLimitError: status.HTTP_429_TOO_MANY_REQUESTS,
    EventConflictError: status.HTTP_409_CONFLICT,
    AgentError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    AgentTimeoutError: status.HTTP_504_GATEWAY_TIMEOUT,
    DatabaseError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def to_http_exception(exc: CalendarAgentError) -> HTTPException:
    """Convert a domain exception to an HTTPException."""
    status_code = EXCEPTION_TO_HTTP.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
    return HTTPException(
        status_code=status_code,
        detail={"error": exc.code, "message": exc.message},
    )
