"""
Core LangChain agent builder.

Architecture:
- Gemini 2.0 Flash as the LLM backbone
- Tool-calling agent pattern
- Per-user calendar service injected via tool closures
- MongoDB-backed conversation memory
- LangSmith tracing (when LANGCHAIN_API_KEY is set)
"""

import asyncio
from datetime import datetime, timezone

from googleapiclient.discovery import Resource
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_google_genai import ChatGoogleGenerativeAI

from app.agent.prompts import CALENDAR_AGENT_SYSTEM_PROMPT
from app.config import settings
from app.core.exceptions import AgentError, AgentTimeoutError
from app.core.logging import get_logger
from app.tools.calendar_tools import build_calendar_tools

logger = get_logger(__name__)

# Agent timeout in seconds
AGENT_TIMEOUT = 60


def _build_llm() -> ChatGoogleGenerativeAI:
    """Build the Gemini LLM instance."""
    return ChatGoogleGenerativeAI(
        model=settings.LLM_MODEL,
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_TOKENS,
        convert_system_message_to_human=True,  # Gemini quirk
    )


def _build_prompt() -> ChatPromptTemplate:
    """Build the agent prompt template."""
    return ChatPromptTemplate.from_messages([
        ("system", CALENDAR_AGENT_SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])


def build_agent_executor(calendar_svc: Resource) -> AgentExecutor:
    """
    Build a fully configured AgentExecutor for a specific user's calendar.

    Args:
        calendar_svc: Authenticated Google Calendar service for the user

    Returns:
        Ready-to-invoke AgentExecutor
    """
    llm = _build_llm()
    tools = build_calendar_tools(calendar_svc)
    prompt = _build_prompt()

    agent = create_tool_calling_agent(llm, tools, prompt)

    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=settings.is_development,
        max_iterations=10,
        max_execution_time=AGENT_TIMEOUT,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )


async def run_agent(
    calendar_svc: Resource,
    user_input: str,
    user_name: str,
    chat_history: list[BaseMessage],
    timezone_name: str = "Asia/Kolkata",
) -> dict:
    """
    Run the calendar agent for a single turn.

    Args:
        calendar_svc: User's authenticated Google Calendar service
        user_input: The user's message
        user_name: Display name for personalization
        chat_history: Previous messages (LangChain format)
        timezone_name: User's timezone

    Returns:
        dict with 'output' (str) and 'intermediate_steps' (list)
    """
    executor = build_agent_executor(calendar_svc)

    current_time = datetime.now(timezone.utc).strftime("%A, %B %d, %Y at %H:%M UTC")

    try:
        result = await asyncio.wait_for(
            executor.ainvoke({
                "input": user_input,
                "chat_history": chat_history,
                "current_time": current_time,
                "user_name": user_name or "there",
                "timezone": timezone_name,
            }),
            timeout=AGENT_TIMEOUT,
        )
        logger.info(
            "agent_completed",
            user_name=user_name,
            steps=len(result.get("intermediate_steps", [])),
        )
        return result

    except asyncio.TimeoutError as exc:
        logger.error("agent_timeout", user_input=user_input[:100])
        raise AgentTimeoutError() from exc
    except Exception as exc:
        logger.error("agent_error", error=str(exc), user_input=user_input[:100])
        raise AgentError(f"Agent failed: {exc!s}") from exc
