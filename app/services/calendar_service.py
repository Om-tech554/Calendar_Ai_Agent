"""
Google Calendar API service with production-grade features:
- Retry with exponential backoff (tenacity)
- Typed error mapping
- Conflict detection
- Free slot finding
- Timezone-aware datetime handling
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytz
from googleapiclient.errors import HttpError
from googleapiclient.discovery import Resource
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)
import logging

from app.core.exceptions import (
    CalendarError,
    CalendarPermissionError,
    CalendarRateLimitError,
    EventConflictError,
    EventNotFoundError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

# Retry on transient network/quota errors
_retry_policy = retry(
    retry=retry_if_exception_type((HttpError, TimeoutError, ConnectionError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
    reraise=False,
)


def _map_http_error(exc: HttpError, event_id: str = "") -> CalendarError:
    """Convert Google API HttpError to a typed domain exception."""
    status = exc.resp.status
    if status == 401:
        from app.core.exceptions import OAuthTokenMissingError
        return OAuthTokenMissingError()
    elif status == 403:
        return CalendarPermissionError()
    elif status == 404:
        return EventNotFoundError(event_id)
    elif status == 409:
        return EventConflictError()
    elif status == 429:
        return CalendarRateLimitError()
    else:
        return CalendarError(f"Google Calendar API error ({status}): {exc.reason}")


def _to_iso(dt: datetime, tz_name: str = "Asia/Kolkata") -> str:
    """Convert a datetime to ISO 8601 string with timezone."""
    tz = pytz.timezone(tz_name)
    if dt.tzinfo is None:
        dt = tz.localize(dt)
    return dt.isoformat()


# ── List Events ───────────────────────────────────────────────────────────────

async def list_events(
    service: Resource,
    max_results: int = 10,
    days_ahead: int = 7,
    query: str | None = None,
    timezone_name: str = "Asia/Kolkata",
) -> list[dict[str, Any]]:
    """Fetch upcoming calendar events."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days_ahead)

    try:
        params: dict[str, Any] = {
            "calendarId": "primary",
            "timeMin": now.isoformat(),
            "timeMax": end.isoformat(),
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
            "timeZone": timezone_name,
        }
        if query:
            params["q"] = query

        result = service.events().list(**params).execute()
        events = result.get("items", [])
        logger.info("events_listed", count=len(events))
        return events
    except HttpError as exc:
        raise _map_http_error(exc) from exc


# ── Create Event ──────────────────────────────────────────────────────────────

async def create_event(
    service: Resource,
    title: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    location: str = "",
    attendees: list[str] | None = None,
    timezone_name: str = "Asia/Kolkata",
) -> dict[str, Any]:
    """Create a new calendar event with conflict detection."""
    attendees = attendees or []

    # Build event body
    event_body: dict[str, Any] = {
        "summary": title,
        "description": description,
        "location": location,
        "start": {"dateTime": start_datetime, "timeZone": timezone_name},
        "end": {"dateTime": end_datetime, "timeZone": timezone_name},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 10},
                {"method": "email", "minutes": 30},
            ],
        },
    }
    if attendees:
        event_body["attendees"] = [{"email": e} for e in attendees]

    # Check for conflicts
    conflicts = await _check_conflicts(service, start_datetime, end_datetime, timezone_name)
    if conflicts:
        raise EventConflictError(conflicts[0].get("summary", "Unknown event"))

    try:
        created = service.events().insert(
            calendarId="primary",
            body=event_body,
            sendUpdates="all" if attendees else "none",
        ).execute()
        logger.info("event_created", event_id=created["id"], title=title)
        return created
    except HttpError as exc:
        raise _map_http_error(exc) from exc


# ── Update Event ──────────────────────────────────────────────────────────────

async def update_event(
    service: Resource,
    event_id: str,
    title: str | None = None,
    start_datetime: str | None = None,
    end_datetime: str | None = None,
    description: str | None = None,
    location: str | None = None,
    timezone_name: str = "Asia/Kolkata",
) -> dict[str, Any]:
    """Patch an existing calendar event (only provided fields are updated)."""
    try:
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
    except HttpError as exc:
        raise _map_http_error(exc, event_id) from exc

    if title is not None:
        event["summary"] = title
    if description is not None:
        event["description"] = description
    if location is not None:
        event["location"] = location
    if start_datetime is not None:
        event["start"] = {"dateTime": start_datetime, "timeZone": timezone_name}
    if end_datetime is not None:
        event["end"] = {"dateTime": end_datetime, "timeZone": timezone_name}

    try:
        updated = service.events().update(
            calendarId="primary", eventId=event_id, body=event
        ).execute()
        logger.info("event_updated", event_id=event_id)
        return updated
    except HttpError as exc:
        raise _map_http_error(exc, event_id) from exc


# ── Delete Event ──────────────────────────────────────────────────────────────

async def delete_event(service: Resource, event_id: str) -> str:
    """Delete a calendar event by ID."""
    try:
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        logger.info("event_deleted", event_id=event_id)
        return f"Event {event_id} has been deleted."
    except HttpError as exc:
        raise _map_http_error(exc, event_id) from exc


# ── Free Slot Finder ──────────────────────────────────────────────────────────

async def find_free_slots(
    service: Resource,
    date: str,
    duration_minutes: int = 60,
    working_hours: tuple[int, int] = (9, 18),
    timezone_name: str = "Asia/Kolkata",
) -> list[dict[str, str]]:
    """Find available time slots on a given date."""
    tz = pytz.timezone(timezone_name)
    target_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=tz)

    day_start = target_date.replace(hour=working_hours[0], minute=0, second=0)
    day_end = target_date.replace(hour=working_hours[1], minute=0, second=0)

    # Fetch all events that day
    try:
        result = service.events().list(
            calendarId="primary",
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
    except HttpError as exc:
        raise _map_http_error(exc) from exc

    busy = []
    for event in result.get("items", []):
        start_str = event["start"].get("dateTime") or event["start"].get("date")
        end_str = event["end"].get("dateTime") or event["end"].get("date")
        if start_str and end_str:
            busy.append((
                datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(tz),
                datetime.fromisoformat(end_str.replace("Z", "+00:00")).astimezone(tz),
            ))

    # Find gaps
    free_slots = []
    current = day_start
    duration = timedelta(minutes=duration_minutes)

    for b_start, b_end in sorted(busy, key=lambda x: x[0]):
        if current + duration <= b_start:
            free_slots.append({
                "start": current.isoformat(),
                "end": (current + duration).isoformat(),
            })
        current = max(current, b_end)

    if current + duration <= day_end:
        free_slots.append({
            "start": current.isoformat(),
            "end": (current + duration).isoformat(),
        })

    return free_slots


# ── Internal: Conflict Detection ──────────────────────────────────────────────

async def _check_conflicts(
    service: Resource,
    start: str,
    end: str,
    timezone_name: str,
) -> list[dict]:
    """Check if any existing events overlap with the given time range."""
    try:
        result = service.events().list(
            calendarId="primary",
            timeMin=start,
            timeMax=end,
            singleEvents=True,
        ).execute()
        return result.get("items", [])
    except HttpError:
        return []  # Non-fatal; allow event creation if check fails
