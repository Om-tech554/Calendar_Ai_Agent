"""Integration tests for the Agent API routes."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """GET /health should return 200."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_chat_requires_auth(client):
    """POST /agent/chat without token should return 401."""
    resp = await client.post("/agent/chat", json={"message": "hello"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sessions_requires_auth(client):
    """GET /agent/sessions without token should return 401."""
    resp = await client.get("/agent/sessions")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_me_requires_auth(client):
    """GET /auth/me without token should return 401."""
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_login_redirects(client):
    """GET /auth/login should redirect to Google OAuth."""
    resp = await client.get("/auth/login", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "accounts.google.com" in resp.headers.get("location", "")


@pytest.mark.asyncio
async def test_chat_with_auth(client, sample_user, sample_jwt, mock_calendar_service):
    """POST /agent/chat with valid JWT should invoke the agent."""
    from app.dependencies import get_current_user
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: sample_user
    try:
        with patch("app.api.routes.agent.get_calendar_service", new_callable=AsyncMock) as mock_cal, \
             patch("app.api.routes.agent.get_or_create_session", new_callable=AsyncMock) as mock_session, \
             patch("app.api.routes.agent.load_session_history", new_callable=AsyncMock) as mock_history, \
             patch("app.api.routes.agent.save_message", new_callable=AsyncMock) as mock_save, \
             patch("app.api.routes.agent.run_agent", new_callable=AsyncMock) as mock_agent, \
             patch("app.api.routes.agent.ChatSession.find_one", new_callable=AsyncMock) as mock_find:

            # Setup mocks
            mock_cal.return_value = mock_calendar_service
            mock_save.return_value = MagicMock(id="msg_001")
            session_mock = MagicMock()
            session_mock.id = "session_001"
            session_mock.title = "Test session"
            mock_session.return_value = session_mock
            mock_history.return_value = []
            mock_agent.return_value = {"output": "You have 1 meeting.", "intermediate_steps": []}
            mock_find.return_value = session_mock

            resp = await client.post(
                "/agent/chat",
                json={"message": "What's on my calendar?"},
                headers={"Authorization": f"Bearer {sample_jwt}"},
            )

            assert resp.status_code == 200
            data = resp.json()
            assert "reply" in data
            assert data["reply"] == "You have 1 meeting."
            assert "session_id" in data
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_delete_message_requires_auth(client):
    """DELETE /agent/messages/{id} without token should return 401."""
    resp = await client.delete("/agent/messages/msg_123")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_message_success(client, sample_user, sample_jwt):
    """DELETE /agent/messages/{id} successfully deletes the message."""
    from app.dependencies import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: sample_user
    try:
        mock_msg = MagicMock()
        mock_msg.id = "msg_001"
        mock_msg.session_id = "sess_001"
        mock_msg.delete = AsyncMock()

        mock_session = MagicMock()
        mock_session.message_count = 3
        mock_session.save = AsyncMock()

        with patch("app.db.models.ChatMessage.find_one", new_callable=AsyncMock) as mock_find_msg, \
             patch("app.db.models.ChatSession.get", new_callable=AsyncMock) as mock_get_sess:
            mock_find_msg.return_value = mock_msg
            mock_get_sess.return_value = mock_session

            resp = await client.delete(
                "/agent/messages/msg_001",
                headers={"Authorization": f"Bearer {sample_jwt}"},
            )

            assert resp.status_code == 200
            assert resp.json()["message"] == "Message deleted."
            mock_msg.delete.assert_awaited_once()
            assert mock_session.message_count == 2
            mock_session.save.assert_awaited_once()
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_delete_session_success(client, sample_user, sample_jwt):
    """DELETE /agent/sessions/{id} deletes the session and associated messages."""
    from app.dependencies import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: sample_user
    try:
        mock_session = MagicMock()
        mock_session.id = "sess_001"
        mock_session.save = AsyncMock()

        msg_find_mock = AsyncMock()
        msg_find_mock.delete.return_value = None

        with patch("app.db.models.ChatSession.find_one", new_callable=AsyncMock) as mock_find_sess, \
             patch("app.db.models.ChatMessage.find") as mock_find_msg:
            mock_find_sess.return_value = mock_session
            mock_find_msg.return_value = msg_find_mock

            resp = await client.delete(
                "/agent/sessions/sess_001",
                headers={"Authorization": f"Bearer {sample_jwt}"},
            )

            assert resp.status_code == 200
            assert resp.json()["message"] == "Session deleted."
            assert mock_session.is_active is False
            mock_session.save.assert_awaited_once()
            msg_find_mock.delete.assert_awaited_once()
    finally:
        app.dependency_overrides.pop(get_current_user, None)
