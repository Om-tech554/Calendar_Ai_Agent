"""
Integration tests for Admin API endpoints and Authorization Guards.
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.db.models import User
from app.core.security import create_access_token


@pytest.fixture
def non_admin_user():
    """Regular user not in ADMIN_EMAILS."""
    return User.model_construct(
        id="user_reg_001",
        google_id="google_sub_reg",
        email="regular@example.com",
        name="Regular User",
        picture_url="https://example.com/avatar.jpg",
    )


@pytest.fixture
def admin_user():
    """Admin user matching ADMIN_EMAILS."""
    return User.model_construct(
        id="user_admin_001",
        google_id="google_sub_admin",
        email="omichandra536@gmail.com",
        name="Omkar Admin",
        picture_url="https://example.com/admin.jpg",
    )


@pytest.mark.asyncio
async def test_admin_overview_requires_auth(client):
    """GET /api/admin/overview without token should return 401."""
    resp = await client.get("/api/admin/overview")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_overview_forbidden_for_regular_user(client, non_admin_user):
    """GET /api/admin/overview with regular user token should return 403."""
    from app.dependencies import get_current_user
    from app.main import app

    token = create_access_token({"sub": non_admin_user.id, "email": non_admin_user.email})
    app.dependency_overrides[get_current_user] = lambda: non_admin_user
    try:
        resp = await client.get(
            "/api/admin/overview",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        data = resp.json()
        assert data["detail"]["error"] == "ADMIN_REQUIRED"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_admin_overview_success(client, admin_user):
    """GET /api/admin/overview with admin token returns 200 and KPI metrics."""
    from app.dependencies import get_current_user
    from app.main import app

    token = create_access_token({"sub": admin_user.id, "email": admin_user.email})
    app.dependency_overrides[get_current_user] = lambda: admin_user
    try:
        with patch("app.db.models.User.count", new_callable=AsyncMock) as mock_user_count, \
             patch("app.db.models.ChatSession.count", new_callable=AsyncMock) as mock_sess_count, \
             patch("app.db.models.ChatMessage.count", new_callable=AsyncMock) as mock_msg_count, \
             patch("app.db.models.OAuthToken.count", new_callable=AsyncMock) as mock_token_count, \
             patch("app.db.models.User.find") as mock_user_find, \
             patch("app.db.models.ChatMessage.find") as mock_msg_find:

            mock_user_count.return_value = 5
            mock_sess_count.return_value = 10
            mock_msg_count.return_value = 42
            mock_token_count.return_value = 4

            user_query_mock = AsyncMock()
            user_query_mock.count.return_value = 3
            mock_user_find.return_value = user_query_mock

            msg_query_mock = AsyncMock()
            msg_query_mock.count.return_value = 15
            msg_query_mock.to_list.return_value = []
            mock_msg_find.return_value = msg_query_mock

            resp = await client.get(
                "/api/admin/overview",
                headers={"Authorization": f"Bearer {token}"},
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["total_users"] == 5
            assert data["total_messages"] == 42
            assert data["gemini_daily_limit"] == 1500
            assert "gemini_used_percent" in data
            assert "reset_in_seconds" in data
            assert "db_collections" in data
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_admin_quotas_success(client, admin_user):
    """GET /api/admin/quotas returns breakdown for Gemini and Calendar API."""
    from app.dependencies import get_current_user
    from app.main import app

    token = create_access_token({"sub": admin_user.id, "email": admin_user.email})
    app.dependency_overrides[get_current_user] = lambda: admin_user
    try:
        with patch("app.db.models.ChatMessage.find") as mock_msg_find:
            msg_query_mock = AsyncMock()
            msg_query_mock.count.return_value = 10
            msg_query_mock.to_list.return_value = []
            mock_msg_find.return_value = msg_query_mock

            resp = await client.get(
                "/api/admin/quotas",
                headers={"Authorization": f"Bearer {token}"},
            )

            assert resp.status_code == 200
            quotas = resp.json()
            assert len(quotas) >= 2
            gemini_q = next(q for q in quotas if "Gemini" in q["service"])
            assert gemini_q["limit"] == 1500
            assert gemini_q["status"] == "healthy"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_serve_admin_html(client):
    """GET /admin should serve admin.html."""
    resp = await client.get("/admin")
    assert resp.status_code == 200
    assert "Admin Control Center" in resp.text


@pytest.mark.asyncio
async def test_update_user_role_forbidden_for_regular_user(client, non_admin_user):
    """Regular user cannot modify roles (returns 403)."""
    from app.dependencies import get_current_user
    from app.main import app

    token = create_access_token({"sub": non_admin_user.id, "email": non_admin_user.email})
    app.dependency_overrides[get_current_user] = lambda: non_admin_user
    try:
        resp = await client.post(
            "/api/admin/users/some_target_id/role",
            json={"role": "admin"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_update_user_role_self_demotion_forbidden(client, admin_user):
    """Admin cannot modify their own role (prevents self-lockout)."""
    from app.dependencies import get_current_user
    from app.main import app

    token = create_access_token({"sub": admin_user.id, "email": admin_user.email})
    app.dependency_overrides[get_current_user] = lambda: admin_user
    try:
        resp = await client.post(
            f"/api/admin/users/{admin_user.id}/role",
            json={"role": "user"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "SELF_DEMOTION_FORBIDDEN"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_update_user_role_success(client, admin_user, non_admin_user):
    """Admin can promote another user to admin role."""
    from datetime import datetime, timezone
    from app.dependencies import get_current_user
    from app.main import app

    now = datetime.now(timezone.utc)
    mock_target = User.model_construct(
        id="target_user_001",
        google_id="sub_target",
        email="target@example.com",
        name="Target User",
        picture_url="",
        role="user",
        created_at=now,
        last_login_at=now,
        is_active=True,
    )
    token = create_access_token({"sub": admin_user.id, "email": admin_user.email})
    app.dependency_overrides[get_current_user] = lambda: admin_user

    try:
        with patch("app.db.models.User.get", new_callable=AsyncMock) as mock_get, \
             patch.object(User, "save", new_callable=AsyncMock) as mock_save, \
             patch("app.db.models.ChatSession.find") as mock_sess_find, \
             patch("app.db.models.ChatMessage.find") as mock_msg_find, \
             patch("app.db.models.OAuthToken.find_one", new_callable=AsyncMock) as mock_token_find:

            mock_get.return_value = mock_target
            sess_mock = AsyncMock()
            sess_mock.count.return_value = 2
            mock_sess_find.return_value = sess_mock

            msg_mock = AsyncMock()
            msg_mock.count.return_value = 5
            mock_msg_find.return_value = msg_mock

            mock_token_find.return_value = None

            resp = await client.post(
                "/api/admin/users/target_user_001/role",
                json={"role": "admin"},
                headers={"Authorization": f"Bearer {token}"},
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["id"] == "target_user_001"
            assert data["role"] == "admin"
            assert data["is_admin"] is True
            mock_save.assert_awaited_once()
    finally:
        app.dependency_overrides.pop(get_current_user, None)
