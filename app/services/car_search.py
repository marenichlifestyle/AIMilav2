from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from typing import Any

from app.supabase_repo import SupabaseRepo


logger = logging.getLogger(__name__)


COLUMN_ALIASES: dict[str, list[str]] = {
    "brand": ["brand", "Brand"],
    "model": ["model", "Model"],
    "pseudo_model": ["pseudoModel", "pseudo_model", "pseudomodel"],
    "year": ["year", "Year"],
    "mileage": ["mileage", "Mileage"],
    "equipment": ["equipment", "Equipment", "trim"],
    "body_type": ["bodyType", "body_type", "BodyType"],
    "generation": ["generation", "Generation"],
    "drive": ["drive", "Drive"],
    "engine": ["engine", "Engine"],
    "power": ["power", "Power"],
    "color": ["color", "Color"],
    "sale_status": ["saleStatus", "sale_status", "SaleStatus"],
    "description": ["publicationDescription", "description", "PublicationDescription"],
    "price": ["sellingPrice", "selling_price", "price", "Price"],
    "url": ["dealerSitePublicationUrl", "dealer_site_publication_url", "url"],
}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_lower(value: Any) -> str:
    return _as_text(value).lower()


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)

    raw = str(value).replace("\u00a0", " ").strip()
    if not raw:
        return None
    raw = raw.lower().replace(",", ".")

    multiplier = 1
    if "млн" in raw or "million" in raw:
        multiplier = 1_000_000
    elif "тыс" in raw or raw.endswith("к"):
        multiplier = 1_000

    digits = re.sub(r"[^\d.]", "", raw)
    if not digits:
        return None

    try:
        if "." in digits:
            return int(float(digits) * multiplier)
        return int(digits) * multiplier
    except ValueError:
        return None


def _pick(row: dict[str, Any], canonical_key: str) -> Any:
    for candidate in COLUMN_ALIASES.get(canonical_key, []):
        if candidate in row and row.get(candidate) is not None:
            return row.get(candidate)
    return None


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[\w\-]+", text.lower()) if len(t) > 1]


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_as_text(v) for v in value if _as_text(v)]
    as_text = _as_text(value)
    if not as_text:
        return []
    return [part.strip() for part in re.split(r"[,;]", as_text) if part.strip()]


def _truncate_text(text: str, limit: int = 200) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


@dataclass(slots=True)
class CanonicalCar:
    key: str
    brand: str
    model: str
    pseudo_model: str
    year: int | None
    mileage: int | None
    equipment: str
    body_type: str
    generation: str
    drive: str
    engine: str
    power: int | None
    color: str
    sale_status: str
    description: str
    price: int | None
    url: str
    raw: dict[str, Any]


class CarSearchService:
    def __init__(self, supabase_repo: SupabaseRepo) -> None:
        self.supabase_repo = supabase_repo

    async def search(self, query_text: str | None, criteria: dict[str, Any] | None) -> dict[str, Any]:
        parsed = self._build_criteria(query_text or "", criteria or {})
        logger.info("car_search criteria: %s", json.dumps(parsed, ensure_ascii=False))

        rows = await self.supabase_repo.search_cars_raw(parsed)
        if not rows:
            return {
                "found": False,
                "reason": "База автомобилей недоступна или не вернула данные",
                "should_escalate": True,
            }

        cars = [self._canonicalize(row) for row in rows]
        cars = [c for c in cars if c is not None]

        if not cars:
            return {
                "found": False,
                "reason": "Получены пустые записи по автомобилям",
                "should_escalate": True,
            }

        best, relaxed = self._find_best(cars, parsed, query_text or "")
        logger.info("car_search results: %s (relaxed=%s)", len(best), relaxed)

        if not best:
            return {
                "found": False,
                "reason": "Подходящие автомобили не найдены",
                "should_escalate": True,
            }

        result_cars = []
        for item, score in best[:5]:
            result_cars.append(
                {
                    "brand": item.brand,
                    "model": item.model,
                    "year": item.year,
                    "mileage": item.mileage,
                    "price": item.price,
                    "color": item.color,
                    "engine": item.engine,
                    "drive": item.drive,
                    "power": item.power,
                    "equipment": item.equipment,
                    "description_short": _truncate_text(item.description, 180),
                    "url": item.url,
                    "score": round(score, 4),
                }
            )

        return {
            "found": True,
            "relaxed": relaxed,
            "query_understood": parsed,
            "cars": result_cars,
        }

    def _build_criteria(self, query_text: str, provided: dict[str, Any]) -> dict[str, Any]:
        parsed = {
            "brand": _as_text(provided.get("brand")),
            "model": _as_text(provided.get("model")),
            "year_min": _as_int(provided.get("year_min")),
            "year_max": _as_int(provided.get("year_max")),
            "budget_min": _as_int(provided.get("budget_min")),
            "budget_max": _as_int(provided.get("budget_max")),
            "mileage_max": _as_int(provided.get("mileage_max")),
            "color": _as_text(provided.get("color")),
            "engine": _as_text(provided.get("engine")),
            "drive": _as_text(provided.get("drive")),
            "body_type": _as_text(provided.get("body_type")),
            "power_min": _as_int(provided.get("power_min")),
            "must_have": _normalize_string_list(provided.get("must_have")),
            "nice_to_have": _normalize_string_list(provided.get("nice_to_have")),
        }

        extracted = self._extract_from_text(query_text)
        for key, value in extracted.items():
            if key not in parsed:
                continue
            if parsed[key] in (None, "", []):
                parsed[key] = value

        if parsed["year_min"] and parsed["year_max"] and parsed["year_min"] > parsed["year_max"]:
            parsed["year_min"], parsed["year_max"] = parsed["year_max"], parsed["year_min"]
        if parsed["budget_min"] and parsed["budget_max"] and parsed["budget_min"] > parsed["budget_max"]:
            parsed["budget_min"], parsed["budget_max"] = parsed["budget_max"], parsed["budget_min"]

        return parsed

    def _extract_from_text(self, text: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        lower = text.lower()

        years = [int(v) for v in re.findall(r"\b(19\d{2}|20\d{2})\b", lower)]
        if len(years) >= 2:
            result["year_min"] = min(years)
            result["year_max"] = max(years)
        elif len(years) == 1:
            year = years[0]
            if any(marker in lower for marker in ["после", "от ", "не старше"]):
                result["year_min"] = year
            elif any(marker in lower for marker in ["до ", "не позже", "максимум"]):
                result["year_max"] = year

        max_budget_match = re.search(
            r"(?:до|не\s+более|макс(?:имум)?)\s*([\d\s,.]+)\s*(млн|миллион|тыс|к)?",
            lower,
        )
        if max_budget_match:
            number = _as_int("".join(max_budget_match.groups(default="")))
            if number:
                result["budget_max"] = number

        range_budget_match = re.search(
            r"от\s*([\d\s,.]+)\s*(млн|миллион|тыс|к)?\s*до\s*([\d\s,.]+)\s*(млн|миллион|тыс|к)?",
            lower,
        )
        if range_budget_match:
            from_raw = f"{range_budget_match.group(1)} {range_budget_match.group(2) or ''}"
            to_raw = f"{range_budget_match.group(3)} {range_budget_match.group(4) or ''}"
            budget_min = _as_int(from_raw)
            budget_max = _as_int(to_raw)
            if budget_min:
                result["budget_min"] = budget_min
            if budget_max:
                result["budget_max"] = budget_max

        mileage_match = re.search(r"(?:до|не\s+больше)\s*([\d\s,.]+)\s*(?:км|тыс)\s*проб", lower)
        if mileage_match:
            mileage = _as_int(mileage_match.group(1))
            if mileage:
                if "тыс" in mileage_match.group(0):
                    mileage *= 1000
                result["mileage_max"] = mileage

        return result

    def _canonicalize(self, row: dict[str, Any]) -> CanonicalCar | None:
        brand = _as_text(_pick(row, "brand"))
        model = _as_text(_pick(row, "model"))
        if not brand and not model:
            return None

        price = _as_int(_pick(row, "price"))
        year = _as_int(_pick(row, "year"))
        mileage = _as_int(_pick(row, "mileage"))
        power = _as_int(_pick(row, "power"))

        pseudo_model = _as_text(_pick(row, "pseudo_model"))
        equipment = _as_text(_pick(row, "equipment"))
        body_type = _as_text(_pick(row, "body_type"))
        generation = _as_text(_pick(row, "generation"))
        drive = _as_text(_pick(row, "drive"))
        engine = _as_text(_pick(row, "engine"))
        color = _as_text(_pick(row, "color"))
        sale_status = _as_text(_pick(row, "sale_status"))
        description = _as_text(_pick(row, "description"))
        url = _as_text(_pick(row, "url"))

        key_parts = [brand.lower(), model.lower(), str(year or ""), str(mileage or ""), str(price or ""), url]
        key = "|".join(key_parts)

        return CanonicalCar(
            key=key,
            brand=brand,
            model=model,
            pseudo_model=pseudo_model,
            year=year,
            mileage=mileage,
            equipment=equipment,
            body_type=body_type,
            generation=generation,
            drive=drive,
            engine=engine,
            power=power,
            color=color,
            sale_status=sale_status,
            description=description,
            price=price,
            url=url,
            raw=row,
        )

    def _find_best(
        self,
        cars: list[CanonicalCar],
        criteria: dict[str, Any],
        query_text: str,
    ) -> tuple[list[tuple[CanonicalCar, float]], bool]:
        for relax_level in range(5):
            candidates = [car for car in cars if self._passes(car, criteria, relax_level)]
            text_candidates = self._text_matches(cars, query_text, criteria)

            merged: dict[str, CanonicalCar] = {car.key: car for car in candidates}
            for car in text_candidates:
                if not self._matches_core_identity(car, criteria):
                    continue
                merged.setdefault(car.key, car)

            scored: list[tuple[CanonicalCar, float]] = []
            for car in merged.values():
                score = self._score(car, criteria, query_text)
                scored.append((car, score))

            scored.sort(key=lambda pair: pair[1], reverse=True)
            strong = [item for item in scored if item[1] >= 0.15]
            if strong:
                return strong, relax_level > 0

        return [], True

    def _matches_core_identity(self, car: CanonicalCar, criteria: dict[str, Any]) -> bool:
        brand = _as_lower(criteria.get("brand"))
        model = _as_lower(criteria.get("model"))

        if brand and brand not in _as_lower(car.brand):
            return False
        if model:
            model_hay = " ".join([car.model, car.pseudo_model, car.generation]).lower()
            if model not in model_hay:
                return False
        return True

    def _passes(self, car: CanonicalCar, criteria: dict[str, Any], relax_level: int) -> bool:
        if not self._matches_core_identity(car, criteria):
            return False

        color = _as_lower(criteria.get("color"))
        engine = _as_lower(criteria.get("engine"))
        drive = _as_lower(criteria.get("drive"))
        body_type = _as_lower(criteria.get("body_type"))
        year_min = criteria.get("year_min")
        year_max = criteria.get("year_max")
        budget_max = criteria.get("budget_max")

        if relax_level < 3 and car.sale_status:
            if car.sale_status.lower() != "onsale":
                return False

        if relax_level < 2:
            if year_min and car.year and car.year < year_min:
                return False
            if year_max and car.year and car.year > year_max:
                return False

        effective_budget_max = budget_max
        if budget_max and relax_level >= 3:
            effective_budget_max = math.floor(budget_max * 1.15)

        if relax_level < 4 and effective_budget_max and car.price and car.price > effective_budget_max:
            return False

        if relax_level < 1 and color and color not in _as_lower(car.color):
            return False

        if engine and engine not in _as_lower(car.engine):
            return False
        if drive and drive not in _as_lower(car.drive):
            return False
        if body_type and body_type not in _as_lower(car.body_type):
            return False

        mileage_max = criteria.get("mileage_max")
        if mileage_max and car.mileage and car.mileage > mileage_max and relax_level < 3:
            return False

        power_min = criteria.get("power_min")
        if power_min and car.power and car.power < power_min and relax_level < 3:
            return False

        return True

    def _text_matches(self, cars: list[CanonicalCar], query_text: str, criteria: dict[str, Any]) -> list[CanonicalCar]:
        query_tokens = _tokenize(query_text)
        if not query_tokens:
            query_tokens = _tokenize(" ".join(criteria.get("must_have", []) + criteria.get("nice_to_have", [])))

        if not query_tokens:
            return []

        result: list[CanonicalCar] = []
        for car in cars:
            haystack = " ".join(
                [
                    car.brand,
                    car.model,
                    car.pseudo_model,
                    car.generation,
                    car.description,
                    car.equipment,
                ]
            ).lower()
            matches = sum(1 for token in query_tokens if token in haystack)
            if matches >= max(1, min(2, len(query_tokens))):
                result.append(car)
        return result

    def _score(self, car: CanonicalCar, criteria: dict[str, Any], query_text: str) -> float:
        score = 0.0

        brand = _as_lower(criteria.get("brand"))
        model = _as_lower(criteria.get("model"))
        color = _as_lower(criteria.get("color"))
        engine = _as_lower(criteria.get("engine"))
        drive = _as_lower(criteria.get("drive"))
        body_type = _as_lower(criteria.get("body_type"))

        if brand:
            if brand == _as_lower(car.brand):
                score += 0.22
            elif brand in _as_lower(car.brand):
                score += 0.12

        if model:
            model_hay = " ".join([car.model, car.pseudo_model, car.generation]).lower()
            if model == car.model.lower():
                score += 0.2
            elif model in model_hay:
                score += 0.12

        year_min = criteria.get("year_min")
        year_max = criteria.get("year_max")
        if car.year:
            if year_min and car.year >= year_min:
                score += 0.06
            if year_max and car.year <= year_max:
                score += 0.06

        budget_min = criteria.get("budget_min")
        budget_max = criteria.get("budget_max")
        if car.price:
            if budget_min and car.price >= budget_min:
                score += 0.03
            if budget_max:
                if car.price <= budget_max:
                    score += 0.15
                elif car.price <= int(budget_max * 1.1):
                    score += 0.03
                else:
                    score -= 0.2

        mileage_max = criteria.get("mileage_max")
        if car.mileage is not None:
            if mileage_max and car.mileage <= mileage_max:
                score += 0.08
            score += max(0.0, 0.05 - (car.mileage / 4_000_000))

        if color and color in _as_lower(car.color):
            score += 0.05
        if engine and engine in _as_lower(car.engine):
            score += 0.05
        if drive and drive in _as_lower(car.drive):
            score += 0.05
        if body_type and body_type in _as_lower(car.body_type):
            score += 0.03

        power_min = criteria.get("power_min")
        if power_min and car.power:
            if car.power >= power_min:
                score += 0.05
            else:
                score -= 0.05

        haystack = " ".join([car.description, car.equipment, car.generation, car.model, car.brand]).lower()
        query_tokens = _tokenize(query_text)
        if query_tokens:
            overlap = sum(1 for token in query_tokens if token in haystack)
            score += min(overlap * 0.02, 0.1)

        for token in criteria.get("must_have", []):
            if token and token.lower() in haystack:
                score += 0.03
        for token in criteria.get("nice_to_have", []):
            if token and token.lower() in haystack:
                score += 0.015

        if car.url:
            score += 0.06
        else:
            score -= 0.1

        if car.sale_status:
            if car.sale_status.lower() == "onsale":
                score += 0.05
            else:
                score -= 0.2

        return score
