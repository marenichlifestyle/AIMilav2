from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError

from app import repositories
from app.chatapp_client import ChatAppClient
from app.config import settings
from app.db import SessionLocal
from app.openai_service import OpenAIService, is_technical_json_text
from app.services.car_search import CarSearchService
from app.services.manager import ManagerService
from app.services.media import detect_file_type, download_media


logger = logging.getLogger(__name__)
TECHNICAL_JSON_FALLBACK_TEXT = "Передам вопрос ответственному менеджеру, он даст точный ответ по наличию и условиям."


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_get(payload: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in payload:
            return payload.get(key)
    return None


def extract_chatapp_payload(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("body") if isinstance(payload.get("body"), dict) else payload

    sender = _safe_get(source, ["sender", "from", "from_type"])
    id_chat = _safe_get(source, ["id_chat", "idChat", "chat_id", "chatId"])
    username = _safe_get(source, ["username", "userName", "login"])
    name = _safe_get(source, ["name", "full_name", "fullName"])
    message = _safe_get(source, ["message", "text", "caption", "file_or_message", "fileOrMessage"])
    dt = _safe_get(source, ["datetime", "date", "timestamp", "time"])
    file_in_message = _safe_get(source, ["file_in_message", "fileInMessage", "has_file", "hasFile"])
    file_link = _safe_get(source, ["file_link", "fileLink", "file_url", "fileUrl", "url"])
    messenger_type = _safe_get(source, ["messenger_type", "messenger", "messengerType"])
    license_id = _safe_get(source, ["license_id", "license", "licenseId"])

    return {
        "sender": sender,
        "id_chat": _clean_text(id_chat),
        "username": _clean_text(username) or None,
        "name": _clean_text(name) or None,
        "message": _clean_text(message),
        "datetime": _clean_text(dt),
        "file_in_message": file_in_message,
        "file_link": _clean_text(file_link),
        "messenger_type": _clean_text(messenger_type) or settings.chatapp_default_messenger,
        "license_id": _clean_text(license_id) or settings.chatapp_default_license_id,
        "source_payload": source if isinstance(source, dict) else payload,
    }


def is_client_sender(sender: Any) -> bool:
    if sender is None:
        return True

    text = str(sender).strip().lower()
    if text in {"", "none", "null", "nil", "client", "customer", "lead", "user"}:
        return True

    blocked_tokens = {"employee", "manager", "system", "bot", "assistant", "operator", "admin"}
    if text in blocked_tokens:
        return False
    if any(token in text for token in blocked_tokens):
        return False

    return True


def _message_has_file(file_in_message: Any, file_link: str) -> bool:
    if file_link:
        return True
    if isinstance(file_in_message, bool):
        return file_in_message
    normalized = str(file_in_message).strip().lower()
    return normalized in {"1", "true", "yes", "y", "file", "has_file"}


def should_force_manager_escalation(text: str) -> bool:
    lower = text.lower()
    triggers = [
        "менеджер",
        "человек",
        "позвон",
        "звонок",
        "приех",
        "встрет",
        "купить",
        "оформ",
        "оплат",
        "договор",
        "документ",
        "счет",
        "счёт",
        "vin",
        "трейд",
        "обмен",
        "выкуп",
        "комисси",
        "жалоб",
        "срочно",
        "vip",
    ]
    return any(token in lower for token in triggers)


class WebhookProcessor:
    def __init__(
        self,
        openai_service: OpenAIService,
        car_search_service: CarSearchService,
        manager_service: ManagerService,
        chatapp_client: ChatAppClient,
    ) -> None:
        self.openai_service = openai_service
        self.car_search_service = car_search_service
        self.manager_service = manager_service
        self.chatapp_client = chatapp_client

    async def handle_webhook(self, payload: dict[str, Any]) -> None:
        try:
            parsed = extract_chatapp_payload(payload)
            chat_id = parsed["id_chat"]
            if not chat_id:
                logger.error("Webhook payload missing id_chat")
                return

            sender = parsed.get("sender")
            if not is_client_sender(sender):
                logger.info("Ignored non-client sender for chat_id=%s sender=%s", chat_id, sender)
                return

            message_has_file = _message_has_file(parsed.get("file_in_message"), parsed.get("file_link", ""))
            file_type = detect_file_type(parsed.get("file_link"), parsed.get("source_payload")) if message_has_file else "text"
            if message_has_file and file_type == "text":
                file_type = "other_file"

            logger.info("Incoming webhook chat_id=%s type=%s", chat_id, file_type)

            client_id: uuid.UUID | None = None
            acquired = False

            async with SessionLocal() as session:
                client = await repositories.get_or_create_client(
                    session=session,
                    chatapp_chat_id=chat_id,
                    username=parsed.get("username"),
                    name=parsed.get("name"),
                    messenger_type=parsed.get("messenger_type") or settings.chatapp_default_messenger,
                )

                await repositories.create_message(
                    session=session,
                    client_id=client.id,
                    direction="incoming",
                    text=parsed.get("message") or None,
                    file_url=parsed.get("file_link") or None,
                    file_type=file_type,
                    raw_payload=payload,
                    processed=False,
                )

                await session.commit()
                client_id = client.id

                acquired = await repositories.try_acquire_processing(session, client.id)
                await session.commit()

            if acquired and client_id:
                asyncio.create_task(self.process_client_after_delay(client_id))
            elif client_id:
                logger.info(
                    "Client already processing, queued incoming only client_id=%s chat_id=%s",
                    client_id,
                    chat_id,
                )
        except IntegrityError as exc:
            logger.error("Database integrity error in webhook handler: %s", exc)
        except Exception as exc:
            logger.exception("Unexpected webhook handler error: %s", exc)

    async def process_client_after_delay(self, client_id: uuid.UUID) -> None:
        delay_seconds = max(1, settings.processing_delay_seconds)
        chat_id_for_logs = "unknown"

        try:
            while True:
                logger.info(
                    "Batch wait started client_id=%s chat_id=%s wait_seconds=%s",
                    client_id,
                    chat_id_for_logs,
                    delay_seconds,
                )
                await asyncio.sleep(delay_seconds)

                has_new_batch = False

                async with SessionLocal() as session:
                    try:
                        client = await repositories.get_client_by_id(session, client_id)
                        if client is None:
                            logger.warning("Client not found for batch processing client_id=%s", client_id)
                            break

                        chat_id_for_logs = client.chatapp_chat_id
                        incoming_messages = await repositories.get_unprocessed_incoming_messages(session, client_id)
                        batch_count = len(incoming_messages)
                        if batch_count == 0:
                            logger.info(
                                "No unprocessed messages for client_id=%s chat_id=%s",
                                client_id,
                                chat_id_for_logs,
                            )
                            break

                        logger.info(
                            "Processing batch client_id=%s chat_id=%s messages_in_batch=%s wait_seconds=%s",
                            client_id,
                            chat_id_for_logs,
                            batch_count,
                            delay_seconds,
                        )

                        await self._process_incoming_batch(
                            session=session,
                            client=client,
                            incoming_messages=incoming_messages,
                        )
                        await session.commit()
                    except Exception as exc:
                        logger.exception("Failed processing client batch client_id=%s: %s", client_id, exc)
                        await session.rollback()

                    try:
                        remaining = await repositories.get_unprocessed_incoming_messages(session, client_id)
                        has_new_batch = len(remaining) > 0
                        logger.info(
                            "Batch processed client_id=%s chat_id=%s has_new_batch=%s remaining_unprocessed=%s",
                            client_id,
                            chat_id_for_logs,
                            has_new_batch,
                            len(remaining),
                        )
                    except Exception as exc:
                        logger.error(
                            "Failed to check remaining queue client_id=%s chat_id=%s: %s",
                            client_id,
                            chat_id_for_logs,
                            exc,
                        )
                        has_new_batch = False

                if has_new_batch:
                    continue
                break
        finally:
            async with SessionLocal() as session:
                try:
                    released = await repositories.try_release_processing_if_queue_empty(session, client_id)
                    if not released:
                        remaining = await repositories.get_unprocessed_incoming_messages(session, client_id)
                        logger.warning(
                            "Keeping processing=true due to pending queue client_id=%s chat_id=%s remaining=%s",
                            client_id,
                            chat_id_for_logs,
                            len(remaining),
                        )
                        await repositories.set_client_processing(session, client_id, True)
                        await session.commit()
                        asyncio.create_task(self.process_client_after_delay(client_id))
                        return

                    await session.commit()
                    logger.info(
                        "Processing lock released client_id=%s chat_id=%s queue_is_empty=true",
                        client_id,
                        chat_id_for_logs,
                    )
                except Exception as exc:
                    logger.error("Failed to reset processing flag client_id=%s: %s", client_id, exc)
                    await session.rollback()
                    try:
                        await repositories.set_client_processing(session, client_id, False)
                        await session.commit()
                    except Exception as inner_exc:
                        logger.error(
                            "Secondary attempt to reset processing flag failed client_id=%s: %s",
                            client_id,
                            inner_exc,
                        )

    async def _process_incoming_batch(
        self,
        session: Any,
        client: Any,
        incoming_messages: list[Any],
    ) -> None:
        client_id = client.id
        batch_message_ids = [msg.id for msg in incoming_messages]

        other_file_messages = [msg for msg in incoming_messages if msg.file_type == "other_file"]
        if other_file_messages:
            summary = self._build_summary_for_manager(incoming_messages)
            await self.manager_service.escalate(
                session,
                client,
                reason="Получен неподдерживаемый файл",
                summary=summary,
            )
            fallback_text = "Передам файл ответственному менеджеру, он посмотрит и вернётся с точным ответом."
            await repositories.create_message(
                session=session,
                client_id=client_id,
                direction="outgoing",
                text=fallback_text,
                file_url=None,
                file_type="text",
                raw_payload={"source": "other_file_fallback"},
                processed=True,
            )
            await self._send_text_to_chatapp_with_token_escalation(
                session=session,
                client=client,
                text=fallback_text,
            )
            await repositories.mark_messages_processed(session, batch_message_ids)
            return

        combined_text = await self._compose_user_text(incoming_messages)
        if not combined_text.strip():
            combined_text = "Клиент отправил пустое сообщение без текста"

        if should_force_manager_escalation(combined_text):
            await self.manager_service.escalate(
                session=session,
                client=client,
                reason="Клиент запросил перевод на менеджера/оформление",
                summary=self._build_summary_for_manager(incoming_messages),
            )
            manager_reply = "Передаю Ваш запрос ответственному менеджеру, он свяжется с Вами в ближайшее время."
            await repositories.create_message(
                session=session,
                client_id=client_id,
                direction="outgoing",
                text=manager_reply,
                file_url=None,
                file_type="text",
                raw_payload={"source": "forced_manager_escalation"},
                processed=True,
            )
            await self._send_text_to_chatapp_with_token_escalation(
                session=session,
                client=client,
                text=manager_reply,
            )
            await repositories.mark_messages_processed(session, batch_message_ids)
            return

        async def _car_search_tool(args: dict[str, Any]) -> dict[str, Any]:
            query = _clean_text(args.get("query")) or combined_text
            criteria = args.get("criteria") if isinstance(args.get("criteria"), dict) else {}
            if not criteria:
                criteria = {k: v for k, v in args.items() if k != "query"}
            return await self.car_search_service.search(query_text=query, criteria=criteria)

        async def _manager_tool(args: dict[str, Any]) -> dict[str, Any]:
            reason = _clean_text(args.get("reason")) or "Запрошен менеджер"
            summary = _clean_text(args.get("summary")) or self._build_summary_for_manager(incoming_messages)
            return await self.manager_service.escalate(session, client, reason=reason, summary=summary)

        generated_text = ""
        new_response_id: str | None = client.last_openai_response_id

        try:
            if not self.openai_service.ready:
                raise RuntimeError("OpenAI client is not configured")
            generated_text, new_response_id = await self.openai_service.generate_response(
                user_text=combined_text,
                previous_response_id=client.last_openai_response_id,
                tool_handlers={
                    "car_search": _car_search_tool,
                    "get_manager": _manager_tool,
                },
            )
        except Exception as exc:
            logger.error("OpenAI generation failed for client %s: %s", client.chatapp_chat_id, exc)
            await self.manager_service.escalate(
                session,
                client,
                reason="Техническая ошибка OpenAI",
                summary=str(exc),
            )
            generated_text = "Извините, сейчас подключу менеджера, чтобы ответить максимально точно."

        generated_text = await self._ensure_client_safe_generated_text(
            session=session,
            client=client,
            generated_text=generated_text,
            incoming_messages=incoming_messages,
        )

        await repositories.create_message(
            session=session,
            client_id=client_id,
            direction="outgoing",
            text=generated_text,
            file_url=None,
            file_type="text",
            raw_payload={"source": "openai"},
            processed=True,
        )

        await self._send_text_to_chatapp_with_token_escalation(
            session=session,
            client=client,
            text=generated_text,
        )

        await repositories.mark_messages_processed(session, batch_message_ids)
        await repositories.set_client_last_response_id(session, client_id, new_response_id)

    async def _ensure_client_safe_generated_text(
        self,
        session: Any,
        client: Any,
        generated_text: str,
        incoming_messages: list[Any],
    ) -> str:
        stripped = (generated_text or "").strip()
        if stripped and not is_technical_json_text(stripped) and not stripped.startswith(("{", "[")):
            return stripped

        if stripped:
            logger.error(
                "Blocked JSON-like OpenAI output before ChatApp send chat_id=%s text_len=%s",
                client.chatapp_chat_id,
                len(stripped),
            )
            await self.manager_service.escalate(
                session,
                client,
                reason="OpenAI вернул технический JSON вместо клиентского ответа",
                summary=self._build_summary_for_manager(incoming_messages),
            )
            return TECHNICAL_JSON_FALLBACK_TEXT

        return "Спасибо за сообщение. Передаю запрос менеджеру, чтобы дать точный ответ."

    async def _compose_user_text(self, incoming_messages: list[Any]) -> str:
        parts: list[str] = []
        for msg in incoming_messages:
            text = (msg.text or "").strip()
            if msg.file_type == "voice" and msg.file_url:
                media_bytes, _ = await download_media(msg.file_url, settings.max_media_bytes)
                transcript = ""
                if media_bytes:
                    transcript = await self.openai_service.transcribe_voice(media_bytes)
                if transcript:
                    text = f"{text}\nГолосовое сообщение: {transcript}".strip()
                else:
                    text = f"{text}\nГолосовое сообщение: [не удалось распознать]".strip()
            elif msg.file_type == "image" and msg.file_url:
                media_bytes, content_type = await download_media(msg.file_url, settings.max_media_bytes)
                description = ""
                if media_bytes:
                    description = await self.openai_service.analyze_image(media_bytes, mime_type=content_type)
                if description:
                    text = f"{text}\nОписание изображения: {description}".strip()
                else:
                    text = f"{text}\nИзображение: [не удалось проанализировать]".strip()

            dt = ""
            if isinstance(msg.raw_payload, dict):
                source = msg.raw_payload.get("body") if isinstance(msg.raw_payload.get("body"), dict) else msg.raw_payload
                if isinstance(source, dict):
                    raw_dt = source.get("datetime") or source.get("date") or source.get("timestamp")
                    if raw_dt:
                        dt = str(raw_dt).strip()
            if not dt and msg.created_at:
                dt = msg.created_at.isoformat()

            parts.append(f"[{dt}] {text}".strip())

        return "\n".join(part for part in parts if part)

    async def _send_text_to_chatapp_with_token_escalation(
        self,
        session: Any,
        client: Any,
        text: str,
    ) -> bool:
        result = await self.chatapp_client.send_text_detailed(
            chat_id=client.chatapp_chat_id,
            text=text,
            messenger_type=client.messenger_type,
        )
        if result.success:
            return True

        logger.error(
            "Failed to send outgoing message to ChatApp for chat_id=%s status=%s error_code=%s retried=%s",
            client.chatapp_chat_id,
            result.status_code,
            result.error_code,
            result.retried,
        )

        if result.refresh_attempted and not result.refresh_succeeded:
            await self.manager_service.escalate(
                session=session,
                client=client,
                reason="Техническая ошибка ChatApp токена",
                summary=(
                    "Не удалось обновить ChatApp access token через tokens.refresh. "
                    f"error_code={result.error_code or 'unknown'} status={result.status_code}"
                ),
            )

        return False

    def _build_summary_for_manager(self, incoming_messages: list[Any]) -> str:
        summaries = []
        for msg in incoming_messages[-5:]:
            text = (msg.text or "").strip()
            if not text:
                text = f"[{msg.file_type or 'unknown'}]"
            summaries.append(text)
        return " | ".join(summaries)[:700]
