from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app.config import settings


logger = logging.getLogger(__name__)


ACCESS_TOKEN_KEYS = ["accessToken", "access_token", "token", "AccessToken"]
REFRESH_TOKEN_KEYS = ["refreshToken", "refresh_token", "RefreshToken"]
ACCESS_TOKEN_END_TIME_KEYS = [
    "accessTokenEndTime",
    "access_token_end_time",
    "access_token_expire_at",
]
REFRESH_TOKEN_END_TIME_KEYS = [
    "refreshTokenEndTime",
    "refresh_token_end_time",
    "refresh_token_expire_at",
]
ROW_IDENTIFIER_KEYS = ["id", "uuid", "token_id", "tokenId"]


@dataclass(slots=True)
class ChatAppToken:
    access_token: str
    refresh_token: str | None
    access_token_end_time: str | None
    refresh_token_end_time: str | None
    access_column: str
    refresh_column: str | None
    access_end_time_column: str | None
    refresh_end_time_column: str | None
    row_identifier_column: str | None
    row_identifier_value: Any
    raw_row: dict[str, Any]


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _first_present_with_key(row: dict[str, Any], keys: list[str]) -> tuple[str | None, Any]:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return key, row.get(key)
    return None, None


def _find_existing_key(row: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        if key in row:
            return key
    return None


def _is_row_active(row: dict[str, Any]) -> bool:
    status_key, status_value = _first_present_with_key(row, ["status", "Status"])
    if status_key is not None and status_value is not None:
        status = str(status_value).strip().lower()
        if status in {"active", "enabled", "ok"}:
            return True
        if status in {"inactive", "disabled", "revoked"}:
            return False

    for key in ["active", "is_active", "isActive", "enabled", "isEnabled"]:
        if key not in row:
            continue
        raw = row.get(key)
        if isinstance(raw, bool):
            return raw
        normalized = str(raw).strip().lower()
        if normalized in {"1", "true", "yes", "y"}:
            return True
        if normalized in {"0", "false", "no", "n"}:
            return False

    return True


def _to_timestamp(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return 0.0

    if text.isdigit():
        try:
            return float(int(text))
        except ValueError:
            return 0.0

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.timestamp()
    except ValueError:
        return 0.0


def _row_recency_score(row: dict[str, Any]) -> float:
    for key in [
        "updated_at",
        "updatedAt",
        "created_at",
        "createdAt",
        "accessTokenEndTime",
        "refreshTokenEndTime",
        "access_token_end_time",
        "refresh_token_end_time",
        "id",
    ]:
        if key in row and row.get(key) not in (None, ""):
            score = _to_timestamp(row.get(key))
            if score > 0:
                return score
    return 0.0


def _token_row_sort_key(row: dict[str, Any]) -> tuple[int, int, int, float]:
    access_key, access_value = _first_present_with_key(row, ACCESS_TOKEN_KEYS)
    refresh_key, refresh_value = _first_present_with_key(row, REFRESH_TOKEN_KEYS)
    has_access = bool(_clean_text(access_value)) and access_key is not None
    has_refresh = bool(_clean_text(refresh_value)) and refresh_key is not None
    is_active = _is_row_active(row)
    recency = _row_recency_score(row)
    return (1 if has_access else 0, 1 if has_refresh else 0, 1 if is_active else 0, recency)


def _build_eq_expression(value: Any) -> str:
    return f"eq.{str(value)}"


class SupabaseRepo:
    def __init__(self) -> None:
        self.base_url = settings.supabase_url
        self.service_key = settings.supabase_service_role_key
        self.token_table = settings.chatapp_token_table
        self.cars_table = settings.chatapp_cars_table

    @property
    def ready(self) -> bool:
        return bool(self.base_url and self.service_key)

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Accept-Profile": "public",
            "Content-Profile": "public",
        }

    def _table_path(self, table_name: str) -> str:
        return urllib.parse.quote(table_name, safe="")

    async def _get_rows(self, table_name: str, params: list[tuple[str, str]]) -> list[dict[str, Any]]:
        if not self.ready:
            logger.error("Supabase credentials are not configured")
            return []

        clean_name = table_name.strip()
        stripped = clean_name.strip('"')
        candidates = [clean_name]
        if clean_name != stripped:
            candidates.append(stripped)
        else:
            candidates.append(f'"{clean_name}"')

        checked: set[str] = set()
        async with httpx.AsyncClient(timeout=20.0) as client:
            for candidate in candidates:
                if not candidate or candidate in checked:
                    continue
                checked.add(candidate)
                url = f"{self.base_url}/rest/v1/{self._table_path(candidate)}"
                try:
                    resp = await client.get(url, headers=self._headers(), params=params)
                    resp.raise_for_status()
                    payload = resp.json()
                    if isinstance(payload, list):
                        return [row for row in payload if isinstance(row, dict)]
                    return []
                except Exception as exc:
                    logger.warning("Supabase GET failed for table candidate %s: %s", candidate, exc)

        logger.error("Supabase GET failed for table %s after all fallbacks", table_name)
        return []

    def _extract_row_identifier(self, row: dict[str, Any]) -> tuple[str | None, Any]:
        for key in ROW_IDENTIFIER_KEYS:
            if key in row and row.get(key) not in (None, ""):
                return key, row.get(key)
        return None, None

    async def get_chatapp_token(self) -> ChatAppToken | None:
        rows = await self._get_rows(self.token_table, [("select", "*"), ("limit", "200")])
        if not rows:
            logger.error("No rows found in Supabase token table: %s", self.token_table)
            return None

        sorted_rows = sorted(rows, key=_token_row_sort_key, reverse=True)
        rows_with_both = [
            row
            for row in sorted_rows
            if _clean_text(_first_present_with_key(row, ACCESS_TOKEN_KEYS)[1])
            and _clean_text(_first_present_with_key(row, REFRESH_TOKEN_KEYS)[1])
        ]
        candidate_rows = rows_with_both or [
            row
            for row in sorted_rows
            if _clean_text(_first_present_with_key(row, ACCESS_TOKEN_KEYS)[1])
        ]

        if not candidate_rows:
            logger.error(
                "Could not find usable ChatApp token row in table %s. Access columns checked: %s",
                self.token_table,
                ", ".join(ACCESS_TOKEN_KEYS),
            )
            return None

        row = candidate_rows[0]
        access_key, access_value = _first_present_with_key(row, ACCESS_TOKEN_KEYS)
        refresh_key, refresh_value = _first_present_with_key(row, REFRESH_TOKEN_KEYS)
        access_end_key, access_end_value = _first_present_with_key(row, ACCESS_TOKEN_END_TIME_KEYS)
        refresh_end_key, refresh_end_value = _first_present_with_key(row, REFRESH_TOKEN_END_TIME_KEYS)
        row_id_col, row_id_val = self._extract_row_identifier(row)

        if access_key is None:
            logger.error("Selected token row has no access token column in table %s", self.token_table)
            return None

        access_token = _clean_text(access_value)
        refresh_token = _clean_text(refresh_value) if refresh_value is not None else None

        return ChatAppToken(
            access_token=access_token,
            refresh_token=refresh_token or None,
            access_token_end_time=_clean_text(access_end_value) or None,
            refresh_token_end_time=_clean_text(refresh_end_value) or None,
            access_column=access_key,
            refresh_column=refresh_key,
            access_end_time_column=access_end_key,
            refresh_end_time_column=refresh_end_key,
            row_identifier_column=row_id_col,
            row_identifier_value=row_id_val,
            raw_row=row,
        )

    async def update_chatapp_tokens(
        self,
        current_token: ChatAppToken,
        new_access_token: str,
        new_refresh_token: str | None,
        access_token_end_time: Any | None = None,
        refresh_token_end_time: Any | None = None,
    ) -> bool:
        if not self.ready:
            logger.error("Cannot update ChatApp tokens: Supabase credentials are not configured")
            return False

        access_value = _clean_text(new_access_token)
        refresh_value = _clean_text(new_refresh_token) if new_refresh_token is not None else ""
        if not access_value:
            logger.error("Cannot update ChatApp tokens: new access token is empty")
            return False

        payload: dict[str, Any] = {current_token.access_column: access_value}

        refresh_column = current_token.refresh_column or _find_existing_key(current_token.raw_row, REFRESH_TOKEN_KEYS)
        if refresh_column and refresh_value:
            payload[refresh_column] = refresh_value

        access_end_column = current_token.access_end_time_column or _find_existing_key(
            current_token.raw_row,
            ACCESS_TOKEN_END_TIME_KEYS,
        )
        if access_end_column and access_token_end_time not in (None, ""):
            payload[access_end_column] = access_token_end_time

        refresh_end_column = current_token.refresh_end_time_column or _find_existing_key(
            current_token.raw_row,
            REFRESH_TOKEN_END_TIME_KEYS,
        )
        if refresh_end_column and refresh_token_end_time not in (None, ""):
            payload[refresh_end_column] = refresh_token_end_time

        url = f"{self.base_url}/rest/v1/{self._table_path(self.token_table)}"

        params: list[tuple[str, str]] = [("select", "*")]
        if current_token.row_identifier_column and current_token.row_identifier_value not in (None, ""):
            params.append(
                (
                    current_token.row_identifier_column,
                    f"eq.{current_token.row_identifier_value}",
                )
            )
        else:
            if current_token.access_column and current_token.access_token:
                params.append((current_token.access_column, _build_eq_expression(current_token.access_token)))

            order_fields = [name for name in ["updated_at", "created_at", "id"] if name in current_token.raw_row]
            if order_fields:
                params.append(("order", ",".join(f"{name}.desc" for name in order_fields)))

        headers = self._headers() | {"Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.patch(url, headers=headers, params=params, json=payload)
                resp.raise_for_status()
            return True
        except Exception as exc:
            logger.error("Failed to update ChatApp token row in Supabase: %s", exc)
            return False

    async def refresh_chatapp_tokens(self, current_token: ChatAppToken) -> tuple[ChatAppToken | None, str | None]:
        refresh_token = _clean_text(current_token.refresh_token)
        if not refresh_token:
            logger.error("Cannot refresh ChatApp token: refresh token is missing")
            return None, "refresh_token_missing"

        refresh_url = "https://api.chatapp.online/v1/tokens/refresh"
        headers = {
            "Refresh": refresh_token,
            "Lang": "ru",
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(refresh_url, headers=headers)
        except Exception as exc:
            logger.error("ChatApp tokens.refresh request failed: %s", exc)
            return None, "refresh_request_failed"

        try:
            payload = resp.json()
        except Exception:
            payload = {}

        if resp.status_code >= 400:
            error_code = None
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                error_code = payload["error"].get("code")
            logger.error("ChatApp tokens.refresh failed: status=%s error_code=%s", resp.status_code, error_code)
            return None, str(error_code or "refresh_http_error")

        data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
        if not isinstance(data, dict):
            logger.error("ChatApp tokens.refresh returned invalid payload")
            return None, "refresh_invalid_payload"

        new_access = _clean_text(
            data.get("accessToken")
            or data.get("access_token")
            or data.get("token")
        )
        new_refresh = _clean_text(
            data.get("refreshToken")
            or data.get("refresh_token")
            or current_token.refresh_token
        )
        access_end = data.get("accessTokenEndTime") or data.get("access_token_end_time")
        refresh_end = data.get("refreshTokenEndTime") or data.get("refresh_token_end_time")

        if not new_access:
            logger.error("ChatApp tokens.refresh returned empty access token")
            return None, "refresh_missing_access"

        updated = await self.update_chatapp_tokens(
            current_token=current_token,
            new_access_token=new_access,
            new_refresh_token=new_refresh or None,
            access_token_end_time=access_end,
            refresh_token_end_time=refresh_end,
        )
        if not updated:
            return None, "supabase_update_failed"

        # Re-read the selected row to keep runtime behavior aligned with DB state.
        token = await self.get_chatapp_token()
        if token is None:
            return None, "supabase_reload_failed"

        return token, None

    async def make_chatapp_tokens(self, current_token: ChatAppToken) -> tuple[ChatAppToken | None, str | None]:
        email = _clean_text(settings.chatapp_auth_email)
        password = _clean_text(settings.chatapp_auth_password)
        app_id = _clean_text(settings.chatapp_app_id)

        if not settings.chatapp_enable_tokens_make_fallback:
            logger.error("ChatApp tokens.make fallback is disabled")
            return None, "tokens_make_disabled"
        if not email or not password or not app_id:
            logger.error(
                "Cannot call ChatApp tokens.make: credentials are incomplete email_set=%s password_set=%s app_id_set=%s",
                bool(email),
                bool(password),
                bool(app_id),
            )
            return None, "tokens_make_credentials_missing"

        make_url = "https://api.chatapp.online/v1/tokens"
        headers = {
            "Lang": "ru",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = {
            "email": email,
            "password": password,
            "appId": app_id,
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(make_url, headers=headers, json=body)
        except Exception as exc:
            logger.error("ChatApp tokens.make request failed: %s", exc)
            return None, "tokens_make_request_failed"

        try:
            payload = resp.json()
        except Exception:
            payload = {}

        if resp.status_code >= 400:
            error_code = None
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                error_code = payload["error"].get("code")
            logger.error("ChatApp tokens.make failed: status=%s error_code=%s", resp.status_code, error_code)
            return None, str(error_code or "tokens_make_http_error")

        data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
        if not isinstance(data, dict):
            logger.error("ChatApp tokens.make returned invalid payload")
            return None, "tokens_make_invalid_payload"

        new_access = _clean_text(
            data.get("accessToken")
            or data.get("access_token")
            or data.get("token")
        )
        new_refresh = _clean_text(
            data.get("refreshToken")
            or data.get("refresh_token")
        )
        access_end = data.get("accessTokenEndTime") or data.get("access_token_end_time")
        refresh_end = data.get("refreshTokenEndTime") or data.get("refresh_token_end_time")

        if not new_access or not new_refresh:
            logger.error(
                "ChatApp tokens.make returned incomplete tokens access_len=%s refresh_present=%s",
                len(new_access),
                bool(new_refresh),
            )
            return None, "tokens_make_incomplete_tokens"

        updated = await self.update_chatapp_tokens(
            current_token=current_token,
            new_access_token=new_access,
            new_refresh_token=new_refresh,
            access_token_end_time=access_end,
            refresh_token_end_time=refresh_end,
        )
        if not updated:
            return None, "supabase_update_failed"

        logger.info(
            "ChatApp tokens.make succeeded and saved token_len=%s refresh_len=%s has_access_end=%s has_refresh_end=%s",
            len(new_access),
            len(new_refresh),
            access_end not in (None, ""),
            refresh_end not in (None, ""),
        )

        token = await self.get_chatapp_token()
        if token is None:
            return None, "supabase_reload_failed"

        return token, None

    async def search_cars_raw(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        def _build_params(include_status: bool, include_numeric: bool, include_brand: bool) -> list[tuple[str, str]]:
            params: list[tuple[str, str]] = [("select", "*"), ("limit", "700")]

            if include_status:
                params.append(("saleStatus", "eq.onsale"))

            if include_brand:
                brand = _clean_text(filters.get("brand"))
                if brand:
                    params.append(("brand", f"ilike.*{brand}*"))

            if include_numeric:
                if filters.get("year_min") is not None:
                    params.append(("year", f"gte.{int(filters['year_min'])}"))
                if filters.get("year_max") is not None:
                    params.append(("year", f"lte.{int(filters['year_max'])}"))
                if filters.get("budget_min") is not None:
                    params.append(("sellingPrice", f"gte.{int(filters['budget_min'])}"))
                if filters.get("budget_max") is not None:
                    params.append(("sellingPrice", f"lte.{int(filters['budget_max'])}"))
                if filters.get("mileage_max") is not None:
                    params.append(("mileage", f"lte.{int(filters['mileage_max'])}"))
                if filters.get("power_min") is not None:
                    params.append(("power", f"gte.{int(filters['power_min'])}"))

            return params

        attempts = [
            _build_params(include_status=True, include_numeric=True, include_brand=True),
            _build_params(include_status=True, include_numeric=False, include_brand=True),
            _build_params(include_status=True, include_numeric=True, include_brand=False),
            [("select", "*"), ("saleStatus", "eq.onsale"), ("limit", "700")],
            [("select", "*"), ("limit", "700")],
        ]

        for idx, params in enumerate(attempts, start=1):
            rows = await self._get_rows(self.cars_table, params)
            if rows:
                if idx > 1:
                    logger.info("Supabase cars query succeeded on fallback attempt %s", idx)
                return rows
        return []

    async def maybe_get_cars_sample(self, limit: int = 5) -> list[dict[str, Any]]:
        params: list[tuple[str, str]] = [
            ("select", "brand,model,year,sellingPrice,dealerSitePublicationUrl"),
            ("limit", str(limit)),
        ]
        return await self._get_rows(self.cars_table, params)
