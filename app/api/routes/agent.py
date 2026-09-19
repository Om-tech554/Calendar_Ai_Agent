"""
Agent chat routes.

POST /agent/chat                   — Send a message to the agent
GET  /agent/sessions               — List user's chat sessions
GET  /agent/sessions/{session_id}  — Get messages in a session
DELETE /agent/sessions/{session_id} — Delete a session
"""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.agent.agent import run_agent
from app.agent.memory import get_or_create_session, load_session_history, save_message
from app.api.middleware.rate_limit import limiter
from app.config import settings
from app.core.exceptions import CalendarAgentError, to_http_exception
from app.core.logging import get_logger
from app.db.models import ChatMessage, ChatSession, User
from app.dependencies import CurrentUser
from app.services.auth_service import get_calendar_service

router = APIRouter(prefix="/agent", tags=["Agent"])
logger = get_logger(__name__)


# ── Request / Response Schemas ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="User's message")
    session_id: str | None = Field(None, description="Session ID (omit to start new session)")
    timezone: str = Field("Asia/Kolkata", description="User's timezone")


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    session_title: str
    user_message_id: str | None = None
    assistant_message_id: str | None = None


class SessionSummary(BaseModel):
    id: str
    title: str
    message_count: int
    updated_at: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    timestamp: str


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse, summary="Chat with the calendar agent")
@limiter.limit(f"{settings.RATE_LIMIT_PER_MINUTE}/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    current_user: User = CurrentUser,
) -> ChatResponse:
    """
    Send a message to the Calendar Agent.
    The agent has access to the user's Google Calendar via their OAuth tokens.
    """
    # Get or create session
    session = await get_or_create_session(current_user.id, body.session_id)

    # Load conversation history
    history = await load_session_history(session.id)

    # Build user's Google Calendar service
    try:
        calendar_svc = await get_calendar_service(current_user.id)
    except CalendarAgentError as exc:
        raise to_http_exception(exc)

    # Save user message
    user_msg = await save_message(session.id, current_user.id, "user", body.message)

    # Run agent
    try:
        result = await run_agent(
            calendar_svc=calendar_svc,
            user_input=body.message,
            user_name=current_user.name,
            chat_history=history,
            timezone_name=body.timezone,
        )
    except CalendarAgentError as exc:
        raise to_http_exception(exc)
    except Exception as exc:
        logger.error("agent_unexpected_error", error=str(exc), user_id=current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "AGENT_ERROR", "message": "An unexpected error occurred."},
        )

    raw_reply = result.get("output", "I'm sorry, I couldn't process your request.")
    if isinstance(raw_reply, list):
        text_parts = [
            p.get("text", str(p)) if isinstance(p, dict) else str(p)
            for p in raw_reply
        ]
        reply = "\n".join(text_parts)
    else:
        reply = str(raw_reply)

    # Save agent reply
    agent_msg = await save_message(
        session.id,
        current_user.id,
        "assistant",
        reply,
        tool_calls=result.get("intermediate_steps", []),
    )

    # Reload session for updated title
    session = await ChatSession.get(session.id)

    user_msg_id = str(user_msg.id) if (user_msg and getattr(user_msg, "id", None) and isinstance(user_msg.id, str)) else None
    agent_msg_id = str(agent_msg.id) if (agent_msg and getattr(agent_msg, "id", None) and isinstance(agent_msg.id, str)) else None

    return ChatResponse(
        reply=reply,
        session_id=session.id,
        session_title=session.title if session else "Chat",
        user_message_id=user_msg_id,
        assistant_message_id=agent_msg_id,
    )


@router.get("/sessions", response_model=list[SessionSummary], summary="List chat sessions")
async def list_sessions(current_user: User = CurrentUser) -> list[SessionSummary]:
    """Return the user's most recent 20 chat sessions."""
    sessions = (
        await ChatSession.find(
            ChatSession.user_id == current_user.id,
            ChatSession.is_active == True,
        )
        .sort("-updated_at")
        .limit(20)
        .to_list()
    )
    return [
        SessionSummary(
            id=s.id,
            title=s.title,
            message_count=s.message_count,
            updated_at=s.updated_at.isoformat(),
        )
        for s in sessions
    ]


@router.get(
    "/sessions/{session_id}",
    response_model=list[MessageOut],
    summary="Get messages in a session",
)
async def get_session_messages(
    session_id: str,
    current_user: User = CurrentUser,
) -> list[MessageOut]:
    """Return all messages in a chat session (must belong to the current user)."""
    # Verify ownership
    session = await ChatSession.find_one({
        "_id": session_id,
        "user_id": current_user.id,
    })
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    messages = (
        await ChatMessage.find(ChatMessage.session_id == session_id)
        .sort("+timestamp")
        .to_list()
    )
    return [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            timestamp=m.timestamp.isoformat(),
        )
        for m in messages
    ]


@router.delete("/sessions/{session_id}", summary="Delete a chat session")
async def delete_session(
    session_id: str,
    current_user: User = CurrentUser,
) -> dict:
    """Delete a chat session and all its messages."""
    session = await ChatSession.find_one({
        "_id": session_id,
        "user_id": current_user.id,
    })
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    session.is_active = False
    await session.save()
    # Delete associated messages
    await ChatMessage.find({"session_id": session_id, "user_id": current_user.id}).delete()
    return {"message": "Session deleted."}


@router.delete("/messages/{message_id}", summary="Delete a single chat message")
async def delete_message(
    message_id: str,
    current_user: User = CurrentUser,
) -> dict:
    """Delete an individual message belonging to the current user."""
    msg = await ChatMessage.find_one({
        "_id": message_id,
        "user_id": current_user.id,
    })
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found.")

    session_id = msg.session_id
    await msg.delete()

    # Decrement session message count if applicable
    session = await ChatSession.get(session_id)
    if session and session.message_count > 0:
        session.message_count = max(0, session.message_count - 1)
        await session.save()

    return {"message": "Message deleted."}
