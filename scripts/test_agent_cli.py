"""
Quick CLI test script — run the agent from the terminal without the web UI.
Useful for testing your setup before starting the server.

Usage:
    python scripts/test_agent_cli.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from datetime import datetime, timezone
from app.agent.agent import run_agent
from app.services.auth_service import get_calendar_service


async def main():
    user_id = input("Enter your MongoDB user_id (from DB after first login): ").strip()
    if not user_id:
        print("❌ No user_id provided.")
        return

    print("\n🔑 Fetching your Google Calendar service...")
    try:
        svc = await get_calendar_service(user_id)
        print("✅ Calendar connected!\n")
    except Exception as e:
        print(f"❌ Failed to get calendar: {e}")
        return

    print("📅 CalAI CLI — type 'quit' to exit\n")
    print("-" * 50)

    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            break
        if not user_input:
            continue

        print("\nCalAI: ", end="", flush=True)
        try:
            result = await run_agent(
                calendar_svc=svc,
                user_input=user_input,
                user_name="User",
                chat_history=[],
                timezone_name="Asia/Kolkata",
            )
            print(result["output"])
        except Exception as e:
            print(f"❌ Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
