from __future__ import annotations

import logging

import httpx

from app.config import settings


logger = logging.getLogger(__name__)


class TelegramClient:
    async def send_manager_message(self, text: str) -> bool:
        if not settings.telegram_bot_token:
            logger.error("TELEGRAM_BOT_TOKEN is not configured")
            return False

        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": settings.telegram_manager_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code >= 400:
                    logger.error("Telegram send failed: status=%s body=%s", resp.status_code, resp.text)
                    return False
            return True
        except Exception as exc:
            logger.error("Telegram send failed with exception: %s", exc)
            return False
