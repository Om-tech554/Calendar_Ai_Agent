"""
Admin dashboard API routes.

Protected by CurrentAdminUser dependency:
- GET /api/admin/overview — Key operational metrics & free-tier quota status
- GET /api/admin/users    — User directory with individual stats & calendar status
- GET /api/admin/quotas   — Detailed Gemini & Google Calendar quota breakdown
- GET /api/admin/activity — Live activity stream of messages and logins
"""

from datetime import datetime, time, timezone, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.config import settings
from app.core.logging import get_logger
from app.db.models import ChatMessage, ChatSession, OAuthToken, User
from app.dependencies import CurrentAdminUser, is_admin_user

router = APIRouter(prefix="/api/admin", tags=["Admin"])
logger = get_logger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────────

class UserRoleUpdate(BaseModel):
    role: Literal["admin", "user"]


class QuotaUsage(BaseModel):
    service: str
    tier: str
    metric: str
    limit: int
    used_today: int
    remaining_today: int
    used_percent: float
    status: str  # "healthy" | "warning" | "critical"
    reset_in_seconds: int
    reset_time_utc: str


class AdminOverview(BaseModel):
    total_users: int
    active_users_today: int
    active_users_7d: int
    total_sessions: int
    total_messages: int
    gemini_requests_today: int
    gemini_daily_limit: int
    gemini_used_percent: float
    gemini_remaining: int
    gemini_rpm_limit: int
    calendar_queries_today: int
    calendar_daily_limit: int
    reset_in_seconds: int
    server_time_utc: str
    app_env: str
    llm_model: str
    db_collections: dict[str, int]


class AdminUserItem(BaseModel):
    id: str
    name: str
    email: str
    picture_url: str
    created_at: str
    last_login_at: str
    is_active: bool
    session_count: int
    message_count: int
    calendar_connected: bool
    role: str = "user"
    is_admin: bool = False
    is_superadmin: bool = False


class AdminActivityItem(BaseModel):
    id: str
    type: str  # "message" | "login" | "session"
    title: str
    detail: str
    timestamp: str
    user_name: str
    user_email: str


# ── Helper Functions ──────────────────────────────────────────────────────────

def _get_utc_today_start() -> datetime:
    """Return midnight UTC of today."""
    now = datetime.now(timezone.utc)
    return datetime.combine(now.date(), time.min, tzinfo=timezone.utc)


def _get_seconds_until_midnight_utc() -> int:
    """Calculate seconds remaining until next midnight UTC (when API quotas reset)."""
    now = datetime.now(timezone.utc)
    tomorrow_midnight = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return max(0, int((tomorrow_midnight - now).total_seconds()))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/overview", response_model=AdminOverview, summary="System overview and quota metrics")
async def get_admin_overview(admin_user: User = CurrentAdminUser) -> AdminOverview:
    """Return high-level KPIs, Gemini free tier consumption, and database counts."""
    today_start = _get_utc_today_start()
    week_start = datetime.now(timezone.utc) - timedelta(days=7)

    # 1. User metrics
    total_users = await User.count()
    active_users_today = await User.find({"last_login_at": {"$gte": today_start}}).count()
    active_users_7d = await User.find({"last_login_at": {"$gte": week_start}}).count()

    # 2. Conversation metrics
    total_sessions = await ChatSession.count()
    total_messages = await ChatMessage.count()

    # 3. Gemini API Usage calculation (each assistant reply is generated via 1+ Gemini turn)
    gemini_requests_today = await ChatMessage.find({
        "role": "assistant",
        "timestamp": {"$gte": today_start},
    }).count()

    # Also count calendar tool calls today
    tool_messages = await ChatMessage.find({
        "role": "assistant",
        "timestamp": {"$gte": today_start},
    }).to_list()
    calendar_queries_today = sum(len(m.tool_calls) for m in tool_messages)

    gemini_limit = settings.GEMINI_FREE_TIER_DAILY_LIMIT
    gemini_pct = round((gemini_requests_today / gemini_limit) * 100, 1) if gemini_limit > 0 else 0.0
    gemini_remaining = max(0, gemini_limit - gemini_requests_today)

    # 4. Collection counts in MongoDB
    oauth_count = await OAuthToken.count()
    db_collections = {
        "users": total_users,
        "chat_sessions": total_sessions,
        "chat_messages": total_messages,
        "oauth_tokens": oauth_count,
    }

    now_utc = datetime.now(timezone.utc)

    return AdminOverview(
        total_users=total_users,
        active_users_today=active_users_today,
        active_users_7d=active_users_7d,
        total_sessions=total_sessions,
        total_messages=total_messages,
        gemini_requests_today=gemini_requests_today,
        gemini_daily_limit=gemini_limit,
        gemini_used_percent=gemini_pct,
        gemini_remaining=gemini_remaining,
        gemini_rpm_limit=15,
        calendar_queries_today=calendar_queries_today,
        calendar_daily_limit=settings.GOOGLE_CALENDAR_DAILY_LIMIT,
        reset_in_seconds=_get_seconds_until_midnight_utc(),
        server_time_utc=now_utc.isoformat(),
        app_env=settings.APP_ENV,
        llm_model=settings.LLM_MODEL,
        db_collections=db_collections,
    )


@router.get("/users", response_model=list[AdminUserItem], summary="List all registered users with metrics")
async def get_admin_users(admin_user: User = CurrentAdminUser) -> list[AdminUserItem]:
    """Return user directory with their usage statistics."""
    superadmins = [e.lower().strip() for e in settings.ADMIN_EMAILS]
    users = await User.find().sort("-last_login_at").limit(100).to_list()
    user_items: list[AdminUserItem] = []

    for u in users:
        sess_count = await ChatSession.find({"user_id": u.id}).count()
        msg_count = await ChatMessage.find({"user_id": u.id, "role": "user"}).count()
        token = await OAuthToken.find_one({"user_id": u.id})
        has_cal = token is not None and any("calendar" in s for s in token.scopes)
        is_admin = is_admin_user(u)
        is_super = u.email.lower().strip() in superadmins

        user_items.append(
            AdminUserItem(
                id=u.id,
                name=u.name or "Unnamed User",
                email=u.email,
                picture_url=u.picture_url or "",
                created_at=u.created_at.isoformat(),
                last_login_at=u.last_login_at.isoformat(),
                is_active=u.is_active,
                session_count=sess_count,
                message_count=msg_count,
                calendar_connected=has_cal,
                role=getattr(u, "role", "user"),
                is_admin=is_admin,
                is_superadmin=is_super,
            )
        )

    return user_items


@router.post("/users/{user_id}/role", response_model=AdminUserItem, summary="Update a user's role (Admin only)")
async def update_user_role(
    user_id: str,
    body: UserRoleUpdate,
    admin_user: User = CurrentAdminUser,
) -> AdminUserItem:
    """
    Promote or demote a user to/from admin role.
    Only authorized administrators can perform this action.
    """
    if admin_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "SELF_DEMOTION_FORBIDDEN", "message": "You cannot modify your own admin role."},
        )

    target_user = await User.get(user_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "USER_NOT_FOUND", "message": "User not found."},
        )

    # Protect environment-configured superadmins from being modified
    superadmins = [e.lower().strip() for e in settings.ADMIN_EMAILS]
    if target_user.email.lower().strip() in superadmins:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "SUPERADMIN_PROTECTED", "message": "Cannot modify role of an environment-configured superadmin."},
        )

    target_user.role = body.role
    await target_user.save()
    logger.info("admin_user_role_changed", admin=admin_user.email, target_user=target_user.email, new_role=body.role)

    sess_count = await ChatSession.find({"user_id": target_user.id}).count()
    msg_count = await ChatMessage.find({"user_id": target_user.id, "role": "user"}).count()
    token = await OAuthToken.find_one({"user_id": target_user.id})
    has_cal = token is not None and any("calendar" in s for s in token.scopes)
    is_admin = is_admin_user(target_user)

    return AdminUserItem(
        id=target_user.id,
        name=target_user.name or "Unnamed User",
        email=target_user.email,
        picture_url=target_user.picture_url or "",
        created_at=target_user.created_at.isoformat(),
        last_login_at=target_user.last_login_at.isoformat(),
        is_active=target_user.is_active,
        session_count=sess_count,
        message_count=msg_count,
        calendar_connected=has_cal,
        role=target_user.role,
        is_admin=is_admin,
        is_superadmin=False,
    )


@router.get("/quotas", response_model=list[QuotaUsage], summary="Detailed API free-tier quotas breakdown")
async def get_admin_quotas(admin_user: User = CurrentAdminUser) -> list[QuotaUsage]:
    """Return detailed quota breakdowns for Gemini AI and Google Calendar APIs."""
    today_start = _get_utc_today_start()
    reset_secs = _get_seconds_until_midnight_utc()
    tomorrow_utc = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d 00:00 UTC")

    # Gemini Daily
    gemini_requests = await ChatMessage.find({
        "role": "assistant",
        "timestamp": {"$gte": today_start},
    }).count()
    gemini_limit = settings.GEMINI_FREE_TIER_DAILY_LIMIT
    gemini_pct = round((gemini_requests / gemini_limit) * 100, 1) if gemini_limit else 0.0

    if gemini_pct >= 85:
        gemini_status = "critical"
    elif gemini_pct >= 60:
        gemini_status = "warning"
    else:
        gemini_status = "healthy"

    # Calendar Queries
    messages_today = await ChatMessage.find({
        "role": "assistant",
        "timestamp": {"$gte": today_start},
    }).to_list()
    calendar_queries = sum(len(m.tool_calls) for m in messages_today)
    cal_limit = settings.GOOGLE_CALENDAR_DAILY_LIMIT
    cal_pct = round((calendar_queries / cal_limit) * 100, 2) if cal_limit else 0.0

    return [
        QuotaUsage(
            service=f"Google Gemini ({settings.LLM_MODEL})",
            tier="Free Tier (Google AI Studio)",
            metric="Requests Per Day (RPD)",
            limit=gemini_limit,
            used_today=gemini_requests,
            remaining_today=max(0, gemini_limit - gemini_requests),
            used_percent=gemini_pct,
            status=gemini_status,
            reset_in_seconds=reset_secs,
            reset_time_utc=tomorrow_utc,
        ),
        QuotaUsage(
            service="Google Calendar API",
            tier="Google Cloud Platform Standard",
            metric="Queries Per Day (QPD)",
            limit=cal_limit,
            used_today=calendar_queries,
            remaining_today=max(0, cal_limit - calendar_queries),
            used_percent=cal_pct,
            status="healthy",
            reset_in_seconds=reset_secs,
            reset_time_utc=tomorrow_utc,
        ),
    ]


@router.get("/activity", response_model=list[AdminActivityItem], summary="Recent system activity stream")
async def get_admin_activity(admin_user: User = CurrentAdminUser) -> list[AdminActivityItem]:
    """Return the most recent messages and interactions."""
    recent_messages = (
        await ChatMessage.find()
        .sort("-timestamp")
        .limit(20)
        .to_list()
    )

    activity: list[AdminActivityItem] = []
    user_cache: dict[str, User] = {}

    for msg in recent_messages:
        if msg.user_id not in user_cache:
            u = await User.get(msg.user_id)
            if u:
                user_cache[msg.user_id] = u

        user = user_cache.get(msg.user_id)
        u_name = user.name if user else "User"
        u_email = user.email if user else "unknown"

        if msg.role == "user":
            type_label = "user_message"
            title = f"{u_name} sent a message"
        else:
            type_label = "agent_reply"
            title = f"Agent responded to {u_name}"

        snippet = msg.content[:100] + ("..." if len(msg.content) > 100 else "")

        activity.append(
            AdminActivityItem(
                id=msg.id,
                type=type_label,
                title=title,
                detail=snippet,
                timestamp=msg.timestamp.isoformat(),
                user_name=u_name,
                user_email=u_email,
            )
        )

    return activity
