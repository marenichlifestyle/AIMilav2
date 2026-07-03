from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app import repositories
from app.config import settings
from app.models import Client
from app.telegram_client import TelegramClient


logger = logging.getLogger(__name__)


class ManagerService:
    def __init__(self, telegram_client: TelegramClient) -> None:
        self.telegram_client = telegram_client

    async def escalate(
        self,
        session: AsyncSession,
        client: Client,
        reason: str,
        summary: str,
        pause_ai: bool = True,
    ) -> dict:
        safe_reason = (reason or "Требуется помощь менеджера").strip()
        safe_summary = (summary or "Нет подробного описания").strip()

        await repositories.create_manager_escalation(
            session=session,
            client_id=client.id,
            reason=safe_reason,
            summary=safe_summary,
        )
        if pause_ai:
            await repositories.pause_client_ai(session=session, client_id=client.id, reason=safe_reason)
            client.ai_state = repositories.AI_STATE_MANAGER_HANDOFF
            client.ai_paused_reason = safe_reason
            client.last_openai_response_id = None
            client.processing = False

        dialog_link = (
            f"https://dialogs.pro/dialogs/{settings.chatapp_default_license_id}/"
            f"telegram/{client.chatapp_chat_id}"
        )

        text = (
            "<b>Клиент переведен на менеджера</b>\n"
            f"Имя: {client.name or '-'}\n"
            f"Username: {client.username or '-'}\n"
            f"ChatApp chat_id: <code>{client.chatapp_chat_id}</code>\n"
            f"Причина: {safe_reason}\n"
            f"Резюме: {safe_summary}\n"
            f"Диалог: {dialog_link}"
        )

        logger.info("Calling get_manager for chat_id=%s reason=%s", client.chatapp_chat_id, safe_reason)
        await self.telegram_client.send_manager_message(text)

        return {
            "ok": True,
            "reason": safe_reason,
            "summary": safe_summary,
        }
