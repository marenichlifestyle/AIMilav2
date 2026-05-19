from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request

from app.chatapp_client import ChatAppClient
from app.config import settings
from app.db import init_db
from app.logging_setup import configure_logging
from app.openai_service import OpenAIService
from app.services.car_search import CarSearchService
from app.services.manager import ManagerService
from app.services.webhook_processor import WebhookProcessor
from app.supabase_repo import SupabaseRepo
from app.telegram_client import TelegramClient


configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ChatApp Mila Replacement",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

supabase_repo = SupabaseRepo()
openai_service = OpenAIService()
telegram_client = TelegramClient()
chatapp_client = ChatAppClient(supabase_repo=supabase_repo)
car_search_service = CarSearchService(supabase_repo=supabase_repo)
manager_service = ManagerService(telegram_client=telegram_client)
webhook_processor = WebhookProcessor(
    openai_service=openai_service,
    car_search_service=car_search_service,
    manager_service=manager_service,
    chatapp_client=chatapp_client,
)


@app.on_event("startup")
async def on_startup() -> None:
    await init_db()
    logger.info("Service started")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _handle_chatapp_request(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            logger.error("Invalid webhook payload type: %s", type(payload))
            return {"ok": True}
    except Exception as exc:
        logger.error("Failed to parse webhook JSON: %s", exc)
        return {"ok": True}

    try:
        await webhook_processor.handle_webhook(payload)
    except Exception as exc:
        logger.exception("Webhook processing failed unexpectedly: %s", exc)

    return {"ok": True}


@app.post(settings.webhook_path)
async def chatapp_webhook(request: Request) -> dict[str, Any]:
    return await _handle_chatapp_request(request)


@app.post(f"{settings.webhook_path}" + "{path_suffix:path}")
async def chatapp_webhook_with_suffix(request: Request, path_suffix: str) -> dict[str, Any]:
    # ChatApp occasionally sends malformed webhook paths where HTML/noise is appended after /webhook/chatapp.
    # We still accept the request and process JSON body to avoid losing client messages.
    logger.warning("Webhook path has unexpected suffix: %s", path_suffix[:400])
    return await _handle_chatapp_request(request)
