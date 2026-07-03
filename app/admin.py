from __future__ import annotations

import argparse
import asyncio
import sys

from app import repositories
from app.db import SessionLocal


async def _pause_client(chat_id: str, reason: str) -> int:
    async with SessionLocal() as session:
        client = await repositories.get_client_by_chat_id(session, chat_id)
        if client is None:
            print(f"Client not found: {chat_id}")
            return 1
        await repositories.pause_client_ai(session, client.id, reason=reason)
        await session.commit()
        print(f"AI paused for {chat_id}: manager_handoff")
        return 0


async def _resume_client(chat_id: str, clear_context: bool) -> int:
    async with SessionLocal() as session:
        client = await repositories.get_client_by_chat_id(session, chat_id)
        if client is None:
            print(f"Client not found: {chat_id}")
            return 1
        await repositories.resume_client_ai(session, client.id, clear_context=clear_context)
        await session.commit()
        suffix = "context cleared" if clear_context else "context kept"
        print(f"AI resumed for {chat_id}: active, {suffix}")
        return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AIMilav2 admin tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    resume = subparsers.add_parser("resume-client", help="Enable AI replies for a ChatApp client")
    resume.add_argument("--chat-id", required=True, help="ChatApp chat_id")
    resume.add_argument(
        "--clear-context",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Clear previous OpenAI response context before resuming",
    )

    pause = subparsers.add_parser("pause-client", help="Disable AI replies for a ChatApp client")
    pause.add_argument("--chat-id", required=True, help="ChatApp chat_id")
    pause.add_argument("--reason", required=True, help="Reason stored in clients.ai_paused_reason")

    return parser


async def _main() -> int:
    args = _build_parser().parse_args()
    if args.command == "resume-client":
        return await _resume_client(args.chat_id, clear_context=args.clear_context)
    if args.command == "pause-client":
        return await _pause_client(args.chat_id, reason=args.reason)
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
