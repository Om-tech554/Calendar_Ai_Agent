"""
Shared pytest fixtures for all tests.
"""

import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop scoped to the session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def client():
    """Async test client with mocked DB."""
    with patch("app.db.database.connect_db", new_callable=AsyncMock), \
         patch("app.db.database.disconnect_db", new_callable=AsyncMock):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as ac:
            yield ac


@pytest.fixture
def mock_calendar_service():
    """Mock Google Calendar service."""
    service = MagicMock()
    events_mock = MagicMock()
    events_mock.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "event_001",
                "summary": "Team Standup",
                "start": {"dateTime": "2026-09-20T09:00:00+05:30"},
                "end": {"dateTime": "2026-09-20T09:30:00+05:30"},
            }
        ]
    }
    events_mock.insert.return_value.execute.return_value = {
        "id": "new_event_001",
        "summary": "Test Event",
        "start": {"dateTime": "2026-09-20T14:00:00+05:30"},
        "end": {"dateTime": "2026-09-20T15:00:00+05:30"},
        "htmlLink": "https://calendar.google.com/event?eid=test",
    }
    service.events.return_value = events_mock
    return service


@pytest.fixture
def sample_user():
    """Sample User model instance."""
    from app.db.models import User
    return User.model_construct(
        id="user_test_001",
        google_id="google_sub_001",
        email="test@example.com",
        name="Test User",
        picture_url="https://example.com/avatar.jpg",
    )


@pytest.fixture
def sample_jwt(sample_user):
    """Valid JWT for the sample user."""
    from app.core.security import create_access_token
    return create_access_token({"sub": sample_user.id, "email": sample_user.email})
