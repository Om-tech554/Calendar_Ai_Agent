"""Unit tests for the calendar service layer."""

import pytest
from unittest.mock import MagicMock
from googleapiclient.errors import HttpError
from httplib2 import Response as HttpResponse

from app.services import calendar_service as cal
from app.core.exceptions import EventNotFoundError, CalendarPermissionError, CalendarRateLimitError


def make_http_error(status: int) -> HttpError:
    """Helper to create a mock HttpError with a given status."""
    resp = HttpResponse({"status": str(status)})
    resp.status = status
    return HttpError(resp=resp, content=b"error")


@pytest.fixture
def svc(mock_calendar_service):
    return mock_calendar_service


@pytest.mark.asyncio
async def test_list_events_returns_events(svc):
    """list_events should return a list of event dicts."""
    events = await cal.list_events(svc, max_results=5, days_ahead=7)
    assert isinstance(events, list)
    assert len(events) == 1
    assert events[0]["summary"] == "Team Standup"


@pytest.mark.asyncio
async def test_list_events_empty(svc):
    """list_events returns empty list when no events."""
    svc.events().list.return_value.execute.return_value = {"items": []}
    events = await cal.list_events(svc)
    assert events == []


@pytest.mark.asyncio
async def test_create_event_success(svc):
    """create_event should call insert and return the created event."""
    # No conflicts
    svc.events().list.return_value.execute.return_value = {"items": []}

    event = await cal.create_event(
        svc,
        title="Test Meeting",
        start_datetime="2026-09-20T14:00:00",
        end_datetime="2026-09-20T15:00:00",
    )
    assert event["id"] == "new_event_001"
    assert event["summary"] == "Test Event"


@pytest.mark.asyncio
async def test_delete_event_success(svc):
    """delete_event should call the delete API."""
    svc.events().delete.return_value.execute.return_value = None
    result = await cal.delete_event(svc, "event_001")
    assert "deleted" in result.lower()
    svc.events().delete.assert_called_once_with(calendarId="primary", eventId="event_001")


@pytest.mark.asyncio
async def test_delete_event_not_found(svc):
    """delete_event raises EventNotFoundError on 404."""
    svc.events().delete.return_value.execute.side_effect = make_http_error(404)
    with pytest.raises(EventNotFoundError):
        await cal.delete_event(svc, "nonexistent_event")


@pytest.mark.asyncio
async def test_list_events_permission_error(svc):
    """list_events raises CalendarPermissionError on 403."""
    svc.events().list.return_value.execute.side_effect = make_http_error(403)
    with pytest.raises(CalendarPermissionError):
        await cal.list_events(svc)


@pytest.mark.asyncio
async def test_list_events_rate_limit(svc):
    """list_events raises CalendarRateLimitError on 429."""
    svc.events().list.return_value.execute.side_effect = make_http_error(429)
    with pytest.raises(CalendarRateLimitError):
        await cal.list_events(svc)
