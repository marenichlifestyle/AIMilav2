from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.supabase_repo import ChatAppToken, SupabaseRepo


logger = logging.getLogger(__name__)


def _normalize_access_token(value: str) -> str:
    # ChatApp expects a raw access token in Authorization header, no Bearer.
    # Be tolerant to accidental surrounding quotes in stored values.
    return value.strip().strip('"').strip("'").strip()


@dataclass(slots=True)
class ChatAppSendResult:
    success: bool
    status_code: int | None
    error_code: str | None
    refresh_attempted: bool
    refresh_succeeded: bool
    retried: bool
    token_source_column: str | None
    has_refresh_token: bool
    access_token_len: int
    license_id: str
    messenger_type: str


class ChatAppClient:
    def __init__(self, supabase_repo: SupabaseRepo) -> None:
        self.supabase_repo = supabase_repo

    def _extract_error_code(self, response: httpx.Response) -> str | None:
        try:
            payload = response.json()
        except Exception:
            return None
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            code = payload["error"].get("code")
            if code:
                return str(code)
        return None

    async def _post_text_message(
        self,
        *,
        token: str,
        chat_id: str,
        text: str,
        messenger: str,
        license_value: str,
    ) -> httpx.Response:
        url = (
            "https://api.chatapp.online/v1/licenses/"
            f"{license_value}/messengers/{messenger}/chats/{chat_id}/messages/text"
        )
        headers = {
            "Authorization": _normalize_access_token(token),
            "Lang": "ru",
            "Content-Type": "application/json",
        }
        body = {
            "text": text,
            "parseMode": "markdown",
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            return await client.post(url, headers=headers, json=body)

    async def send_text_detailed(
        self,
        chat_id: str,
        text: str,
        messenger_type: str | None = None,
        license_id: str | None = None,
    ) -> ChatAppSendResult:
        messenger = (messenger_type or settings.chatapp_default_messenger or "telegram").strip() or "telegram"
        license_value = (license_id or settings.chatapp_default_license_id or "68179").strip() or "68179"

        token = await self.supabase_repo.get_chatapp_token()
        if token is None:
            logger.error("Cannot send ChatApp message: access token not found")
            return ChatAppSendResult(
                success=False,
                status_code=None,
                error_code="token_not_found",
                refresh_attempted=False,
                refresh_succeeded=False,
                retried=False,
                token_source_column=None,
                has_refresh_token=False,
                access_token_len=0,
                license_id=license_value,
                messenger_type=messenger,
            )

        access_token = _normalize_access_token(token.access_token)
        refresh_present = bool((token.refresh_token or "").strip())
        logger.info(
            "ChatApp token debug: access_col=%s has_refresh=%s access_len=%s license_id=%s messenger_type=%s",
            token.access_column,
            refresh_present,
            len(access_token),
            license_value,
            messenger,
        )

        try:
            first_response = await self._post_text_message(
                token=access_token,
                chat_id=chat_id,
                text=text,
                messenger=messenger,
                license_value=license_value,
            )
        except Exception as exc:
            logger.error("ChatApp send failed with exception: %s", exc)
            return ChatAppSendResult(
                success=False,
                status_code=None,
                error_code="request_exception",
                refresh_attempted=False,
                refresh_succeeded=False,
                retried=False,
                token_source_column=token.access_column,
                has_refresh_token=refresh_present,
                access_token_len=len(access_token),
                license_id=license_value,
                messenger_type=messenger,
            )

        if first_response.status_code < 400:
            return ChatAppSendResult(
                success=True,
                status_code=first_response.status_code,
                error_code=None,
                refresh_attempted=False,
                refresh_succeeded=False,
                retried=False,
                token_source_column=token.access_column,
                has_refresh_token=refresh_present,
                access_token_len=len(access_token),
                license_id=license_value,
                messenger_type=messenger,
            )

        first_error_code = self._extract_error_code(first_response)
        if first_response.status_code == 403 and first_error_code == "ApiInvalidTokenError":
            logger.warning("ChatApp access token is invalid; attempting tokens.refresh")

            refreshed_token, refresh_error = await self.supabase_repo.refresh_chatapp_tokens(token)
            if refreshed_token is None:
                logger.error("ChatApp tokens.refresh failed: %s", refresh_error)
                return ChatAppSendResult(
                    success=False,
                    status_code=first_response.status_code,
                    error_code=refresh_error or first_error_code,
                    refresh_attempted=True,
                    refresh_succeeded=False,
                    retried=False,
                    token_source_column=token.access_column,
                    has_refresh_token=refresh_present,
                    access_token_len=len(access_token),
                    license_id=license_value,
                    messenger_type=messenger,
                )

            new_access = _normalize_access_token(refreshed_token.access_token)
            try:
                second_response = await self._post_text_message(
                    token=new_access,
                    chat_id=chat_id,
                    text=text,
                    messenger=messenger,
                    license_value=license_value,
                )
            except Exception as exc:
                logger.error("ChatApp retry send failed with exception: %s", exc)
                return ChatAppSendResult(
                    success=False,
                    status_code=None,
                    error_code="retry_request_exception",
                    refresh_attempted=True,
                    refresh_succeeded=True,
                    retried=True,
                    token_source_column=refreshed_token.access_column,
                    has_refresh_token=bool((refreshed_token.refresh_token or "").strip()),
                    access_token_len=len(new_access),
                    license_id=license_value,
                    messenger_type=messenger,
                )

            if second_response.status_code < 400:
                return ChatAppSendResult(
                    success=True,
                    status_code=second_response.status_code,
                    error_code=None,
                    refresh_attempted=True,
                    refresh_succeeded=True,
                    retried=True,
                    token_source_column=refreshed_token.access_column,
                    has_refresh_token=bool((refreshed_token.refresh_token or "").strip()),
                    access_token_len=len(new_access),
                    license_id=license_value,
                    messenger_type=messenger,
                )

            second_error_code = self._extract_error_code(second_response)
            logger.error(
                "ChatApp send retry failed: status=%s error_code=%s body=%s",
                second_response.status_code,
                second_error_code,
                second_response.text,
            )
            return ChatAppSendResult(
                success=False,
                status_code=second_response.status_code,
                error_code=second_error_code,
                refresh_attempted=True,
                refresh_succeeded=True,
                retried=True,
                token_source_column=refreshed_token.access_column,
                has_refresh_token=bool((refreshed_token.refresh_token or "").strip()),
                access_token_len=len(new_access),
                license_id=license_value,
                messenger_type=messenger,
            )

        logger.error(
            "ChatApp send failed: status=%s error_code=%s body=%s",
            first_response.status_code,
            first_error_code,
            first_response.text,
        )
        return ChatAppSendResult(
            success=False,
            status_code=first_response.status_code,
            error_code=first_error_code,
            refresh_attempted=False,
            refresh_succeeded=False,
            retried=False,
            token_source_column=token.access_column,
            has_refresh_token=refresh_present,
            access_token_len=len(access_token),
            license_id=license_value,
            messenger_type=messenger,
        )

    async def send_text(
        self,
        chat_id: str,
        text: str,
        messenger_type: str | None = None,
        license_id: str | None = None,
    ) -> bool:
        result = await self.send_text_detailed(
            chat_id=chat_id,
            text=text,
            messenger_type=messenger_type,
            license_id=license_id,
        )
        return result.success
