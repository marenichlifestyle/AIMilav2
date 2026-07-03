from __future__ import annotations

import base64
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.config import settings
from app.prompt import SYSTEM_PROMPT


logger = logging.getLogger(__name__)


ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
TOOL_ARGUMENT_KEYS = {"query", "criteria", "reason", "summary", "brand", "model", "must_have", "nice_to_have"}


def _get_attr(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _looks_like_json_object_or_array(text: str) -> bool:
    stripped = text.strip()
    return (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    )


def is_technical_json_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped or not _looks_like_json_object_or_array(stripped):
        return False

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return False

    if isinstance(payload, dict):
        return True
    return isinstance(payload, list)


def _is_client_safe_text(text: str) -> bool:
    return bool(text.strip()) and not is_technical_json_text(text)


def _extract_url_citations(chunk: Any) -> list[str]:
    annotations = _get_attr(chunk, "annotations", []) or []
    urls: list[str] = []
    for annotation in annotations:
        if _get_attr(annotation, "type") != "url_citation":
            continue
        url = _get_attr(annotation, "url")
        if isinstance(url, str) and url.strip():
            urls.append(url.strip())
    return urls


def _append_citation_urls(text: str, urls: list[str]) -> str:
    unique_urls = []
    seen = set()
    for url in urls:
        if url in seen or url in text:
            continue
        seen.add(url)
        unique_urls.append(url)

    if not unique_urls:
        return text.strip()
    return f"{text.strip()}\n\nИсточники: " + ", ".join(unique_urls[:3])


def _extract_text_from_response(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and _is_client_safe_text(output_text):
        return output_text.strip()
    if isinstance(output_text, str) and output_text.strip():
        logger.warning("Discarded JSON-like OpenAI output_text before client send")

    output = response.get("output", []) or []
    safe_text_chunks: list[tuple[str, list[str]]] = []

    for item in output:
        if _get_attr(item, "type") != "message":
            continue
        content = _get_attr(item, "content", []) or []
        for chunk in content:
            chunk_type = _get_attr(chunk, "type")
            if chunk_type in {"output_text", "text"}:
                text_value = _get_attr(chunk, "text")
                if not isinstance(text_value, str) or not text_value.strip():
                    continue
                if is_technical_json_text(text_value):
                    logger.warning("Discarded JSON-like OpenAI message chunk before client send")
                    continue
                safe_text_chunks.append((text_value.strip(), _extract_url_citations(chunk)))

    if not safe_text_chunks:
        return ""

    final_text, citation_urls = safe_text_chunks[-1]
    return _append_citation_urls(final_text, citation_urls)


def _build_tools(enable_web_search: bool) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "name": "car_search",
            "description": (
                "Строгий поиск автомобилей в актуальной базе Million Miles/Supabase. "
                "Использовать для любых вопросов о наличии, цене, ссылке, комплектации, модификации, "
                "опциях, тормозах, аудиосистеме, подвеске и характеристиках конкретных автомобилей. "
                "Не придумывать авто, цены или ссылки: клиенту можно показывать только данные из результата. "
                "Web-search допустим только для общего рыночного/технического контекста модели, "
                "но не как источник наличия Million Miles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Оригинальный полный запрос клиента без сокращения"},
                    "criteria": {
                        "type": "object",
                        "properties": {
                            "brand": {"type": "string"},
                            "model": {"type": "string"},
                            "year_min": {"type": "integer"},
                            "year_max": {"type": "integer"},
                            "budget_min": {"type": "integer"},
                            "budget_max": {"type": "integer"},
                            "mileage_max": {"type": "integer"},
                            "color": {"type": "string"},
                            "engine": {"type": "string"},
                            "drive": {"type": "string"},
                            "body_type": {"type": "string"},
                            "power_min": {"type": "integer"},
                            "must_have": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Обязательные модификации/опции: Turbo, GTS, Brabus, ceramic brakes, Burmester, massage и т.д.",
                            },
                            "nice_to_have": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Желательные, но не обязательные опции или характеристики",
                            },
                            "feature_terms": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Ключевые признаки комплектации/опций, например brakes, ceramic, carbon, burmester, massage, ventilation",
                            },
                        },
                        "additionalProperties": True,
                    },
                },
                "additionalProperties": True,
            },
        },
        {
            "type": "function",
            "name": "get_manager",
            "description": (
                "Немедленно передать диалог ответственному менеджеру. "
                "Вызывать обязательно, если клиент просит человека/менеджера/звонок; "
                "готов купить, приехать, оплатить или просит встречу; "
                "нужны точные расчёты, документы, VIN, договор, счёт, сроки; "
                "обсуждается трейд-ин, выкуп, комиссия, обмен; "
                "нет уверенного ответа, нет подходящего авто, пришёл неизвестный файл, "
                "или есть жалоба/срочно/VIP."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["reason", "summary"],
                "additionalProperties": True,
            },
        },
    ]

    if enable_web_search:
        tools.append(
            {
                "type": "web_search",
                "user_location": {
                    "type": "approximate",
                    "country": "RU",
                    "city": "Moscow",
                    "timezone": "Europe/Moscow",
                },
            }
        )

    return tools


class OpenAIService:
    def __init__(self) -> None:
        self.api_key = settings.openai_api_key.strip()
        self.responses_url = "https://api.openai.com/v1/responses"
        self.transcriptions_url = "https://api.openai.com/v1/audio/transcriptions"

    @property
    def ready(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
        }

    async def _post_responses(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.ready:
            raise RuntimeError("OpenAI API key is missing")

        headers = self._headers() | {"Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self.responses_url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise RuntimeError("Invalid OpenAI responses payload")
            return data

    async def transcribe_voice(self, media_bytes: bytes, suffix: str = ".oga") -> str:
        if not self.ready:
            return ""

        filename = f"voice{suffix or '.oga'}"
        files = {
            "file": (filename, media_bytes, "application/octet-stream"),
        }
        data = {
            "model": settings.openai_transcribe_model,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    self.transcriptions_url,
                    headers=self._headers(),
                    data=data,
                    files=files,
                )
                resp.raise_for_status()
                payload = resp.json()
                if isinstance(payload, dict):
                    return str(payload.get("text", "")).strip()
                return ""
        except Exception as exc:
            logger.error("OpenAI transcription failed: %s", exc)
            return ""

    async def analyze_image(self, media_bytes: bytes, mime_type: str | None = None) -> str:
        if not self.ready:
            return ""

        safe_mime = (mime_type or "image/jpeg").split(";")[0].strip() or "image/jpeg"
        encoded = base64.b64encode(media_bytes).decode("utf-8")
        image_url = f"data:{safe_mime};base64,{encoded}"

        payload = {
            "model": settings.openai_model,
            "store": False,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Кратко опишите фото автомобиля или документа для менеджера.",
                        },
                        {
                            "type": "input_image",
                            "image_url": image_url,
                        },
                    ],
                }
            ],
        }

        try:
            response = await self._post_responses(payload)
            return _extract_text_from_response(response)
        except Exception as exc:
            logger.error("OpenAI image analysis failed: %s", exc)
            return ""

    async def generate_response(
        self,
        user_text: str,
        previous_response_id: str | None,
        tool_handlers: dict[str, ToolHandler],
    ) -> tuple[str, str | None]:
        if not self.ready:
            return "", previous_response_id

        tools = _build_tools(settings.openai_enable_web_search)

        input_messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]

        request_payload: dict[str, Any] = {
            "model": settings.openai_model,
            "input": input_messages,
            "tools": tools,
            "tool_choice": "auto",
            "store": True,
        }
        if settings.openai_enable_web_search:
            request_payload["include"] = ["web_search_call.action.sources"]
        if previous_response_id:
            request_payload["previous_response_id"] = previous_response_id

        try:
            response = await self._post_responses(request_payload)
        except httpx.HTTPStatusError as exc:
            if not settings.openai_enable_web_search:
                raise
            logger.error("OpenAI request with web_search failed, retrying without web_search: %s", exc)
            tools = _build_tools(False)
            request_payload["tools"] = tools
            request_payload.pop("include", None)
            response = await self._post_responses(request_payload)
        last_response_id = _get_attr(response, "id", previous_response_id)

        for _ in range(6):
            output = _get_attr(response, "output", []) or []
            tool_calls = [item for item in output if _get_attr(item, "type") == "function_call"]
            if not tool_calls:
                break

            tool_outputs = []
            for call in tool_calls:
                call_name = _get_attr(call, "name", "")
                call_id = _get_attr(call, "call_id", "")
                raw_args = _get_attr(call, "arguments", "{}")

                try:
                    parsed_args = json.loads(raw_args or "{}") if isinstance(raw_args, str) else (raw_args or {})
                    if not isinstance(parsed_args, dict):
                        parsed_args = {}
                except json.JSONDecodeError:
                    parsed_args = {}

                handler = tool_handlers.get(call_name)
                if handler is None:
                    output_payload = {"ok": False, "error": f"Unknown tool: {call_name}"}
                else:
                    try:
                        output_payload = await handler(parsed_args)
                    except Exception as exc:
                        logger.error("Tool %s failed: %s", call_name, exc)
                        output_payload = {"ok": False, "error": f"Tool execution failed: {call_name}"}

                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(output_payload, ensure_ascii=False),
                    }
                )

            followup_payload: dict[str, Any] = {
                "model": settings.openai_model,
                "previous_response_id": _get_attr(response, "id", last_response_id),
                "input": tool_outputs,
                "tools": tools,
                "tool_choice": "auto",
                "store": True,
            }
            if settings.openai_enable_web_search:
                followup_payload["include"] = ["web_search_call.action.sources"]
            response = await self._post_responses(followup_payload)
            last_response_id = _get_attr(response, "id", last_response_id)

        final_text = _extract_text_from_response(response)
        return final_text, last_response_id
