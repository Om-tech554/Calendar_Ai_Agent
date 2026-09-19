"""
Per-user conversation memory backed by MongoDB.

Loads the last N messages from a session and converts them to
LangChain message format for the agent.
"""

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.core.logging import get_logger
from app.db.models import ChatMessage, ChatSession

logger = get_logger(__name__)

MAX_HISTORY_MESSAGES = 20  # Max messages to load for context window


async def load_session_history(session_id: str) -> list[BaseMessage]:
    """
    Load recent messages from a chat session and convert to LangChain format.
    Returns a list of HumanMessage/AIMessage objects.
    """
    messages = (
        await ChatMessage.find(
            ChatMessage.session_id == session_id
        )
        .sort("-timestamp")
        .limit(MAX_HISTORY_MESSAGES)
        .to_list()
    )
    # Reverse so messages are chronological (oldest to newest) for LLM context
    messages.reverse()

    lc_messages: list[BaseMessage] = []
    for msg in messages:
        if msg.role == "user":
            lc_messages.append(HumanMessage(content=msg.content))
        elif msg.role == "assistant":
            lc_messages.append(AIMessage(content=msg.content))

    return lc_messages


def _normalize_content(content: Any) -> str:
    """Ensure message content is always a clean string (handles LangChain content blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and "text" in p:
                parts.append(str(p["text"]))
            elif isinstance(p, str):
                parts.append(p)
            else:
                parts.append(str(p))
        return "\n".join(parts)
    return str(content) if content is not None else ""


def _normalize_tool_calls(tool_calls: Any) -> list[dict]:
    """Ensure tool_calls is always a list of valid dicts."""
    if not tool_calls:
        return []
    res: list[dict] = []
    for item in tool_calls:
        if isinstance(item, dict):
            res.append(item)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            action, observation = item[0], item[1]
            res.append({
                "tool": getattr(action, "tool", str(action)),
                "input": str(getattr(action, "tool_input", "")),
                "output": str(observation),
            })
        else:
            res.append({"action": str(item)})
    return res


async def save_message(
    session_id: str,
    user_id: str,
    role: str,
    content: Any,
    tool_calls: Any = None,
) -> ChatMessage:
    """Persist a message to MongoDB and update session metadata."""
    from datetime import datetime, timezone

    clean_content = _normalize_content(content)
    clean_tool_calls = _normalize_tool_calls(tool_calls)

    msg = ChatMessage(
        session_id=session_id,
        user_id=user_id,
        role=role,
        content=clean_content,
        tool_calls=clean_tool_calls,
    )
    await msg.insert()

    # Update session updated_at and message count
    session = await ChatSession.get(session_id)
    if session:
        session.updated_at = datetime.now(timezone.utc)
        session.message_count += 1
        # Auto-generate session title from first user message
        if session.message_count == 1 and role == "user":
            session.title = content[:60] + ("..." if len(content) > 60 else "")
        await session.save()

    return msg


async def get_or_create_session(user_id: str, session_id: str | None = None) -> ChatSession:
    """Get an existing session or create a new one."""
    if session_id:
        session = await ChatSession.find_one({
            "_id": session_id,
            "user_id": user_id,
            "is_active": True,
        })
        if session:
            return session

    # Create new session
    session = ChatSession(user_id=user_id)
    await session.insert()
    logger.info("session_created", session_id=session.id, user_id=user_id)
    return session
