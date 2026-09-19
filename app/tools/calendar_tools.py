"""
LangChain tool factory for Google Calendar.

Tools are built as closures that capture the user's calendar service,
ensuring each agent invocation uses the correct user's credentials.
"""

import json
from datetime import datetime, timezone
from typing import Any

from googleapiclient.discovery import Resource
from langchain_core.tools import tool

from app.core.logging import get_logger
from app.services import calendar_service as cal

logger = get_logger(__name__)


def _format_event(event: dict[str, Any]) -> str:
    """Format a Google Calendar event dict as readable text."""
    title = event.get("summary", "Untitled")
    start = event["start"].get("dateTime") or event["start"].get("date", "")
    end = event["end"].get("dateTime") or event["end"].get("date", "")
    location = event.get("location", "")
    description = event.get("description", "")
    event_id = event.get("id", "")

    parts = [
        f"📅 **{title}**",
        f"   ID: `{event_id}`",
        f"   Start: {start}",
        f"   End:   {end}",
    ]
    if location:
        parts.append(f"   📍 Location: {location}")
    if description:
        parts.append(f"   📝 Notes: {description[:100]}{'...' if len(description) > 100 else ''}")
    return "\n".join(parts)


def build_calendar_tools(calendar_svc: Resource) -> list:
    """
    Build LangChain tools injected with the user's Google Calendar service.

    Returns a list of tools ready to pass to the LangChain agent.
    """

    @tool
    async def list_upcoming_events(days: int = 7, search_query: str = "") -> str:
        """
        List upcoming calendar events.

        Args:
            days: Number of days ahead to look (default: 7, max: 90)
            search_query: Optional keyword to filter events by title/description
        """
        days = min(max(1, days), 90)  # Clamp to [1, 90]
        query = search_query if search_query.strip() else None

        events = await cal.list_events(
            calendar_svc, max_results=15, days_ahead=days, query=query
        )
        if not events:
            return f"No events found in the next {days} day(s)."

        lines = [f"Found {len(events)} event(s) in the next {days} day(s):\n"]
        lines.extend(_format_event(e) for e in events)
        return "\n\n".join(lines)

    @tool
    async def create_calendar_event(
        title: str,
        start_datetime: str,
        end_datetime: str,
        description: str = "",
        location: str = "",
        attendees: str = "",
    ) -> str:
        """
        Create a new calendar event.

        Args:
            title: Event title/summary
            start_datetime: Start time in ISO 8601 format (e.g., 2026-09-20T14:00:00)
            end_datetime: End time in ISO 8601 format (e.g., 2026-09-20T15:00:00)
            description: Optional event description/notes
            location: Optional physical or virtual location
            attendees: Comma-separated email addresses of attendees (optional)
        """
        attendee_list = [e.strip() for e in attendees.split(",") if e.strip()] if attendees else []

        event = await cal.create_event(
            calendar_svc,
            title=title,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            description=description,
            location=location,
            attendees=attendee_list,
        )
        return (
            f"✅ Event created successfully!\n"
            f"   Title: {event['summary']}\n"
            f"   Start: {event['start'].get('dateTime', '')}\n"
            f"   End:   {event['end'].get('dateTime', '')}\n"
            f"   ID: `{event['id']}`\n"
            f"   Link: {event.get('htmlLink', '')}"
        )

    @tool
    async def update_calendar_event(
        event_id: str,
        title: str = "",
        start_datetime: str = "",
        end_datetime: str = "",
        description: str = "",
        location: str = "",
    ) -> str:
        """
        Update an existing calendar event by its ID.

        Args:
            event_id: The event ID (from list_upcoming_events)
            title: New title (leave empty to keep current)
            start_datetime: New start time ISO 8601 (leave empty to keep current)
            end_datetime: New end time ISO 8601 (leave empty to keep current)
            description: New description (leave empty to keep current)
            location: New location (leave empty to keep current)
        """
        updated = await cal.update_event(
            calendar_svc,
            event_id=event_id,
            title=title or None,
            start_datetime=start_datetime or None,
            end_datetime=end_datetime or None,
            description=description or None,
            location=location or None,
        )
        return (
            f"✅ Event updated!\n"
            f"   Title: {updated.get('summary', '')}\n"
            f"   Start: {updated['start'].get('dateTime', '')}\n"
            f"   End:   {updated['end'].get('dateTime', '')}"
        )

    @tool
    async def delete_calendar_event(event_id: str, confirmed: bool = False) -> str:
        """
        Delete a calendar event by ID. Always ask the user to confirm before calling this.

        Args:
            event_id: The event ID to delete
            confirmed: Must be True — only call this after explicit user confirmation
        """
        if not confirmed:
            return (
                "⚠️ Deletion not confirmed. Please confirm you want to delete this event "
                f"(ID: {event_id}) before proceeding."
            )
        result = await cal.delete_event(calendar_svc, event_id)
        return f"🗑️ {result}"

    @tool
    async def find_free_time_slots(
        date: str,
        duration_minutes: int = 60,
    ) -> str:
        """
        Find available free time slots on a specific date.

        Args:
            date: Date to check in YYYY-MM-DD format (e.g., 2026-09-20)
            duration_minutes: Duration of needed slot in minutes (default: 60)
        """
        slots = await cal.find_free_slots(
            calendar_svc,
            date=date,
            duration_minutes=duration_minutes,
        )
        if not slots:
            return f"No free slots found on {date} for {duration_minutes} minutes."

        lines = [f"Free {duration_minutes}-minute slots on {date}:"]
        for i, slot in enumerate(slots[:5], 1):  # Show max 5
            lines.append(f"  {i}. {slot['start']} → {slot['end']}")
        return "\n".join(lines)

    @tool
    def get_current_datetime() -> str:
        """Get the current date and time. Use this when you need to know what 'today', 'now', or 'tomorrow' means."""
        now = datetime.now(timezone.utc)
        return (
            f"Current UTC time: {now.strftime('%A, %B %d, %Y at %H:%M:%S UTC')}\n"
            f"ISO format: {now.isoformat()}"
        )

    return [
        list_upcoming_events,
        create_calendar_event,
        update_calendar_event,
        delete_calendar_event,
        find_free_time_slots,
        get_current_datetime,
    ]
