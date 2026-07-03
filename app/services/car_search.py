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
    "modification": ["modificationName", "modification", "ModificationName", "modification_name"],
    "equipment": ["equipment", "Equipment", "trim", "equipmentName", "EquipmentName", "equipment_name"],
    "stock_state": ["stockState", "stock_state", "StockState"],
    "year": ["year", "Year"],
    "mileage": ["mileage", "Mileage"],
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

STOPWORDS = {
    "а",
    "авто",
    "автомобиль",
    "автомобили",
    "вас",
    "вариант",
    "варианты",
    "где",
    "дайте",
    "добрый",
    "день",
    "есть",
    "интересует",
    "какие",
    "какой",
    "машина",
    "машины",
    "можно",
    "мне",
    "найдите",
    "нужен",
    "нужна",
    "нужны",
    "по",
    "покажите",
    "посмотрите",
    "привет",
    "расскажите",
    "что",
    "у",
    "хочу",
}

MODEL_ALIASES: list[dict[str, Any]] = [
    {
        "markers": ["g class", "g 63", "g63", "g 500", "g500", "g 580", "g580"],
        "brand": "Mercedes-Benz",
        "model": "G-Класс",
    },
    {
        "markers": ["g 63", "g63", "amg g 63", "g class amg", "g klass amg", "g класс amg"],
        "brand": "Mercedes-Benz",
        "model": "G-Класс AMG",
        "must_have": ["63", "AMG"],
    },
    {"markers": ["porsche 911", "porshe 911", "порше 911", "911"], "brand": "Porsche", "model": "911"},
    {"markers": ["911 turbo", "911 turbo s", "турбо 911"], "brand": "Porsche", "model": "911", "must_have": ["Turbo"]},
    {"markers": ["cayenne", "каен", "кайен"], "brand": "Porsche", "model": "Cayenne"},
    {"markers": ["cayenne gts", "каен gts", "кайен gts"], "brand": "Porsche", "model": "Cayenne", "must_have": ["GTS"]},
    {"markers": ["panamera", "панамера"], "brand": "Porsche", "model": "Panamera"},
    {"markers": ["bentayga", "бентайга", "бентэйга"], "brand": "Bentley", "model": "Bentayga"},
    {"markers": ["continental gt", "континенталь gt", "континентал gt"], "brand": "Bentley", "model": "Continental GT"},
    {"markers": ["cullinan", "куллинан", "каллинан"], "brand": "Rolls-Royce", "model": "Cullinan"},
    {"markers": ["spectre", "спектр"], "brand": "Rolls-Royce", "model": "Spectre"},
    {"markers": ["range rover sport", "рейндж ровер спорт", "рендж ровер спорт"], "brand": "Land Rover", "model": "Range Rover Sport"},
    {"markers": ["range rover", "рейндж ровер", "рендж ровер"], "brand": "Land Rover", "model": "Range Rover"},
    {"markers": ["x5", "x 5", "икс 5"], "brand": "BMW", "model": "X5"},
    {"markers": ["x5 m", "x 5 m", "икс 5 м"], "brand": "BMW", "model": "X5 M", "must_have": ["Competition"]},
    {"markers": ["x6", "x 6", "икс 6"], "brand": "BMW", "model": "X6"},
    {"markers": ["x6 m", "x 6 m", "икс 6 м"], "brand": "BMW", "model": "X6 M", "must_have": ["Competition"]},
    {"markers": ["x7", "x 7", "икс 7"], "brand": "BMW", "model": "X7"},
    {"markers": ["urus", "урус"], "brand": "Lamborghini", "model": "Urus"},
    {"markers": ["urus se", "урус se"], "brand": "Lamborghini", "model": "Urus", "must_have": ["SE"]},
    {"markers": ["revuelto", "ревуэльто", "ревуелто"], "brand": "Lamborghini", "model": "Revuelto"},
    {"markers": ["purosangue", "пуросанге", "пуросанг"], "brand": "Ferrari", "model": "Purosangue"},
]

BRAND_ALIASES: dict[str, str] = {
    "мерседес": "mercedes",
    "мерседес бенц": "mercedes benz",
    "мерс": "mercedes",
    "бенц": "benz",
    "порше": "porsche",
    "порш": "porsche",
    "бмв": "bmw",
    "бентли": "bentley",
    "роллс ройс": "rolls royce",
    "ролс ройс": "rolls royce",
    "роллс": "rolls royce",
    "ламборгини": "lamborghini",
    "ламба": "lamborghini",
    "феррари": "ferrari",
    "ленд ровер": "land rover",
    "лэнд ровер": "land rover",
    "астон мартин": "aston martin",
    "макларен": "mclaren",
    "кадиллак": "cadillac",
}

FEATURE_ALIASES: dict[str, list[str]] = {
    "brakes": ["тормоз", "brake", "ccb", "ceramic", "керамическ", "carbon ceramic", "карбон керамичес"],
    "ceramic": ["керамическ", "ceramic", "ccb"],
    "carbon": ["карбон", "carbon", "углерод"],
    "burmester": ["burmester", "бурместер"],
    "bang_olufsen": ["bang olufsen", "b o", "b&o", "olufsen"],
    "massage": ["массаж", "massage"],
    "ventilation": ["вентиляц", "ventilation", "ventilated"],
    "pneumatic": ["пневмо", "пневмат", "air suspension"],
    "night": ["night", "найт"],
    "performance": ["performance", "перформанс"],
}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_lower(value: Any) -> str:
    return _as_text(value).lower()


def _normalize_auto_text(value: Any) -> str:
    text = _as_lower(value)
    replacements = {
        "ё": "е",
        "—": "-",
        "–": "-",
        "‑": "-",
        "класс": "class",
        "гелик": "g class",
        "гелика": "g class",
        "гелики": "g class",
        "геликам": "g class",
        "гелендваген": "g class",
        "гелендвагены": "g class",
        "гелендвагена": "g class",
        "каен": "cayenne",
        "кайен": "cayenne",
        "панамера": "panamera",
        "бентайга": "bentayga",
        "бентэйга": "bentayga",
        "континенталь": "continental",
        "континентал": "continental",
        "куллинан": "cullinan",
        "каллинан": "cullinan",
        "урус": "urus",
        "ревуэльто": "revuelto",
        "ревуелто": "revuelto",
        "пуросанге": "purosangue",
        "пуросанг": "purosangue",
        "турбо": "turbo",
        "купе": "coupe",
    }
    replacements.update(BRAND_ALIASES)
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r"\bг\s*(\d{2,3})\b", r"g \1", text)
    text = re.sub(r"\bg\s*-?\s*(\d{2,3})\b", r"g \1", text)
    text = re.sub(r"\bg\s*-?\s*class\b", "g class", text)
    text = re.sub(r"\bикс\s*(\d)\b", r"x \1", text)
    text = re.sub(r"\bx\s+(\d)\b", r"x\1", text)
    text = re.sub(r"[^a-zа-я0-9&]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _compact_normalized(value: Any) -> str:
    return _normalize_auto_text(value).replace(" ", "")


def _normalized_tokens(value: Any) -> list[str]:
    return re.findall(r"[a-zа-я0-9&]+", _normalize_auto_text(value))


def _term_in_text(haystack: Any, needle: Any) -> bool:
    normalized_haystack = _normalize_auto_text(haystack)
    normalized_needle = _normalize_auto_text(needle)
    if not normalized_needle:
        return False

    if normalized_needle == "g class":
        return "g class" in normalized_haystack or re.search(r"\bg\s*(?:63|400|450|500|550|580)\b", normalized_haystack) is not None
    if normalized_needle in {"g 63", "g63"}:
        return re.search(r"\bg\s*63\b", normalized_haystack) is not None

    needle_tokens = _normalized_tokens(normalized_needle)
    haystack_tokens = _normalized_tokens(normalized_haystack)
    if not needle_tokens:
        return False

    if len(needle_tokens) == 1:
        token = needle_tokens[0]
        if token in haystack_tokens:
            return True
        # Short model codes must be exact tokens: X7 must not match DBX707.
        if len(token) <= 3 and re.search(r"[a-zа-я]", token) and re.search(r"\d", token):
            return False

    if re.search(rf"(?<![a-zа-я0-9]){re.escape(normalized_needle)}(?![a-zа-я0-9])", normalized_haystack):
        return True

    compact_needle = _compact_normalized(normalized_needle)
    compact_haystack = _compact_normalized(normalized_haystack)
    if len(compact_needle) > 3 and compact_needle in compact_haystack:
        return True

    return False


def _contains_normalized(haystack: Any, needle: Any) -> bool:
    return _term_in_text(haystack, needle)


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
    normalized = _normalize_auto_text(text)
    tokens = [t for t in re.findall(r"[a-zа-я0-9&]+", normalized) if len(t) > 1 and t not in STOPWORDS]
    if "g" in normalized.split() and "63" in normalized.split():
        tokens.extend(["g", "63", "amg"])
    if "g class" in normalized:
        tokens.extend(["g", "class"])
    return list(dict.fromkeys(tokens))


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


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _as_text(value)
        if not clean:
            continue
        key = _normalize_auto_text(clean)
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


@dataclass(slots=True)
class CanonicalCar:
    key: str
    brand: str
    model: str
    pseudo_model: str
    modification: str
    equipment: str
    stock_state: str
    year: int | None
    mileage: int | None
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

        self._apply_inventory_matches(cars, parsed, query_text or "")
        best, relaxed = self._find_best(cars, parsed, query_text or "")
        logger.info(
            "car_search results: %s (relaxed=%s strict_model=%s)",
            len(best),
            relaxed,
            bool(parsed.get("_strict_model")),
        )

        if not best:
            reason = "Подходящие автомобили не найдены"
            if parsed.get("_strict_model"):
                reason = "Запрошенная модель не найдена в актуальном инвентаре"
            return {
                "found": False,
                "reason": reason,
                "should_escalate": True,
                "query_understood": self._public_criteria(parsed),
            }

        result_cars = []
        for item, score in best[:5]:
            explanation = self._explain_match(item, parsed, query_text or "")
            result_cars.append(
                {
                    "brand": item.brand,
                    "model": item.model,
                    "pseudo_model": item.pseudo_model,
                    "modification": item.modification,
                    "year": item.year,
                    "mileage": item.mileage,
                    "price": item.price,
                    "color": item.color,
                    "engine": item.engine,
                    "drive": item.drive,
                    "power": item.power,
                    "equipment": item.equipment,
                    "stock_state": item.stock_state,
                    "description_short": _truncate_text(item.description, 180),
                    "spec_highlights": explanation["spec_highlights"],
                    "matched_fields": explanation["matched_fields"],
                    "matched_terms": explanation["matched_terms"],
                    "url": item.url,
                    "score": round(score, 4),
                }
            )

        return {
            "found": True,
            "relaxed": relaxed,
            "query_understood": self._public_criteria(parsed),
            "cars": result_cars,
        }

    def _public_criteria(self, parsed: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in parsed.items() if not key.startswith("_")}

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
            "feature_terms": _normalize_string_list(provided.get("feature_terms")),
            "_strict_model": False,
            "_matched_alias": "",
        }

        extracted = self._extract_from_text(query_text)
        for key, value in extracted.items():
            if key in {"must_have", "nice_to_have", "feature_terms"}:
                parsed[key] = _unique(parsed.get(key, []) + _normalize_string_list(value))
                continue
            if key.startswith("_"):
                parsed[key] = value
                continue
            if key not in parsed:
                continue
            if parsed[key] in (None, "", []):
                parsed[key] = value

        self._normalize_known_model_criteria(parsed, query_text)

        if parsed["year_min"] and parsed["year_max"] and parsed["year_min"] > parsed["year_max"]:
            parsed["year_min"], parsed["year_max"] = parsed["year_max"], parsed["year_min"]
        if parsed["budget_min"] and parsed["budget_max"] and parsed["budget_min"] > parsed["budget_max"]:
            parsed["budget_min"], parsed["budget_max"] = parsed["budget_max"], parsed["budget_min"]

        return parsed

    def _normalize_known_model_criteria(self, parsed: dict[str, Any], query_text: str) -> None:
        combined = " ".join([query_text, _as_text(parsed.get("brand")), _as_text(parsed.get("model"))])
        normalized = _normalize_auto_text(combined)

        best_match: tuple[int, dict[str, Any], str] | None = None
        for rule in MODEL_ALIASES:
            markers = [_normalize_auto_text(marker) for marker in rule["markers"]]
            matched_marker = next((marker for marker in markers if _term_in_text(normalized, marker)), "")
            if not matched_marker:
                continue

            weight = len(_compact_normalized(matched_marker)) + (5 if rule.get("must_have") else 0)
            if best_match is None or weight > best_match[0]:
                best_match = (weight, rule, matched_marker)

        if best_match is not None:
            _, rule, matched_marker = best_match
            parsed["brand"] = rule["brand"]
            parsed["model"] = rule["model"]
            parsed["_strict_model"] = True
            parsed["_matched_alias"] = matched_marker
            parsed["must_have"] = _unique(parsed.get("must_have", []) + rule.get("must_have", []))

        if parsed.get("model"):
            parsed["_strict_model"] = bool(parsed.get("_strict_model")) or self._looks_specific_model(parsed.get("model"))

    def _looks_specific_model(self, model: Any) -> bool:
        normalized = _normalize_auto_text(model)
        if not normalized:
            return False
        tokens = [token for token in _normalized_tokens(normalized) if token not in {"class", "klass"}]
        return bool(tokens)

    def _extract_from_text(self, text: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        lower = text.lower()
        normalized = _normalize_auto_text(text)

        for feature, markers in FEATURE_ALIASES.items():
            if any(_term_in_text(normalized, marker) for marker in markers):
                result.setdefault("feature_terms", []).append(feature)

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

    def _apply_inventory_matches(self, cars: list[CanonicalCar], parsed: dict[str, Any], query_text: str) -> None:
        normalized_query = _normalize_auto_text(" ".join([query_text, _as_text(parsed.get("model")), _as_text(parsed.get("brand"))]))
        if not normalized_query:
            return

        best_brand: tuple[int, str] | None = None
        best_model: tuple[int, CanonicalCar, str] | None = None

        for car in cars:
            if _term_in_text(normalized_query, car.brand):
                score = len(_compact_normalized(car.brand))
                if best_brand is None or score > best_brand[0]:
                    best_brand = (score, car.brand)

            model_terms = [car.model, car.pseudo_model, car.equipment]
            for term in model_terms:
                if not term or not _term_in_text(normalized_query, term):
                    continue
                score = len(_compact_normalized(term)) + (12 if term == car.model else 8)
                if best_model is None or score > best_model[0]:
                    best_model = (score, car, term)

            # Modification names are useful for trims like Turbo S, GTS, 40d, Brabus 800.
            for term in [car.modification]:
                if not term or not _term_in_text(normalized_query, term):
                    continue
                score = len(_compact_normalized(term)) + 6
                if best_model is None or score > best_model[0]:
                    best_model = (score, car, term)

        if not _as_text(parsed.get("brand")) and best_brand is not None:
            parsed["brand"] = best_brand[1]

        if best_model is not None:
            _, car, term = best_model
            parsed["brand"] = car.brand
            if not _as_text(parsed.get("model")):
                parsed["model"] = car.model
                parsed["_strict_model"] = True
                parsed["_matched_alias"] = term

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
        modification = _as_text(_pick(row, "modification"))
        equipment = _as_text(_pick(row, "equipment"))
        stock_state = _as_text(_pick(row, "stock_state"))
        body_type = _as_text(_pick(row, "body_type"))
        generation = _as_text(_pick(row, "generation"))
        drive = _as_text(_pick(row, "drive"))
        engine = _as_text(_pick(row, "engine"))
        color = _as_text(_pick(row, "color"))
        sale_status = _as_text(_pick(row, "sale_status"))
        description = _as_text(_pick(row, "description"))
        url = _as_text(_pick(row, "url"))

        key_parts = [brand.lower(), model.lower(), pseudo_model.lower(), str(year or ""), str(mileage or ""), str(price or ""), url]
        key = "|".join(key_parts)

        return CanonicalCar(
            key=key,
            brand=brand,
            model=model,
            pseudo_model=pseudo_model,
            modification=modification,
            equipment=equipment,
            stock_state=stock_state,
            year=year,
            mileage=mileage,
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
        has_structured_filter = any(
            criteria.get(key)
            for key in [
                "brand",
                "model",
                "year_min",
                "year_max",
                "budget_min",
                "budget_max",
                "mileage_max",
                "color",
                "engine",
                "drive",
                "body_type",
                "power_min",
            ]
        )
        query_tokens = _tokenize(query_text)

        for relax_level in range(5):
            candidates = [car for car in cars if self._passes(car, criteria, relax_level)] if has_structured_filter else []
            text_candidates = self._text_matches(cars, query_text, criteria)

            merged: dict[str, CanonicalCar] = {car.key: car for car in candidates}
            for car in text_candidates:
                if has_structured_filter and not self._matches_core_identity(car, criteria):
                    continue
                merged.setdefault(car.key, car)

            scored: list[tuple[CanonicalCar, float]] = []
            for car in merged.values():
                score = self._score(car, criteria, query_text)
                scored.append((car, score))

            scored.sort(key=lambda pair: pair[1], reverse=True)
            min_score = 0.24 if query_tokens and not has_structured_filter else 0.18
            if criteria.get("_strict_model"):
                min_score = 0.28
            strong = [item for item in scored if item[1] >= min_score]
            if strong:
                return strong, relax_level > 0

        return [], True

    def _identity_haystack(self, car: CanonicalCar) -> str:
        return " ".join([car.model, car.pseudo_model, car.equipment, car.modification, car.generation])

    def _full_haystack(self, car: CanonicalCar) -> str:
        return " ".join(
            [
                car.brand,
                car.model,
                car.pseudo_model,
                car.equipment,
                car.modification,
                car.generation,
                car.description,
            ]
        )

    def _matches_core_identity(self, car: CanonicalCar, criteria: dict[str, Any]) -> bool:
        brand = _as_text(criteria.get("brand"))
        model = _as_text(criteria.get("model"))

        if brand and not _contains_normalized(car.brand, brand):
            return False
        if model and not _contains_normalized(self._identity_haystack(car), model):
            return False
        return True

    def _passes(self, car: CanonicalCar, criteria: dict[str, Any], relax_level: int) -> bool:
        if not self._matches_core_identity(car, criteria):
            return False

        color = _as_text(criteria.get("color"))
        engine = _as_text(criteria.get("engine"))
        drive = _as_text(criteria.get("drive"))
        body_type = _as_text(criteria.get("body_type"))
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

        if relax_level < 1 and color and not _contains_normalized(car.color, color):
            return False

        if engine and not _contains_normalized(car.engine, engine):
            return False
        if drive and not _contains_normalized(car.drive, drive):
            return False
        if body_type and not _contains_normalized(car.body_type, body_type):
            return False

        mileage_max = criteria.get("mileage_max")
        if mileage_max and car.mileage and car.mileage > mileage_max and relax_level < 3:
            return False

        power_min = criteria.get("power_min")
        if power_min and car.power and car.power < power_min and relax_level < 3:
            return False

        if criteria.get("_strict_model") and relax_level < 3:
            missing = [term for term in criteria.get("must_have", []) if not self._matches_feature_or_term(car, term)]
            if missing:
                return False

        return True

    def _matches_feature_or_term(self, car: CanonicalCar, term: str) -> bool:
        if term in FEATURE_ALIASES:
            return any(_term_in_text(self._full_haystack(car), marker) for marker in FEATURE_ALIASES[term])
        return _term_in_text(self._full_haystack(car), term)

    def _text_matches(self, cars: list[CanonicalCar], query_text: str, criteria: dict[str, Any]) -> list[CanonicalCar]:
        query_tokens = _tokenize(query_text)
        if not query_tokens:
            query_tokens = _tokenize(" ".join(criteria.get("must_have", []) + criteria.get("nice_to_have", [])))

        feature_terms = criteria.get("feature_terms", [])
        if not query_tokens and not feature_terms:
            return []

        result: list[CanonicalCar] = []
        for car in cars:
            haystack = self._full_haystack(car)
            matched_tokens = sum(1 for token in query_tokens if _term_in_text(haystack, token))
            matched_features = sum(1 for term in feature_terms if self._matches_feature_or_term(car, term))
            required = max(1, min(2, len(query_tokens))) if query_tokens else 0
            if matched_features or (query_tokens and matched_tokens >= required):
                result.append(car)
        return result

    def _score(self, car: CanonicalCar, criteria: dict[str, Any], query_text: str) -> float:
        score = 0.0

        brand = _as_text(criteria.get("brand"))
        model = _as_text(criteria.get("model"))
        color = _as_text(criteria.get("color"))
        engine = _as_text(criteria.get("engine"))
        drive = _as_text(criteria.get("drive"))
        body_type = _as_text(criteria.get("body_type"))

        if brand:
            if _normalize_auto_text(brand) == _normalize_auto_text(car.brand):
                score += 0.28
            elif _contains_normalized(car.brand, brand):
                score += 0.16

        if model:
            identity = self._identity_haystack(car)
            if _normalize_auto_text(model) == _normalize_auto_text(car.model):
                score += 0.38
            elif _normalize_auto_text(model) == _normalize_auto_text(car.pseudo_model):
                score += 0.34
            elif _contains_normalized(identity, model):
                score += 0.26
            else:
                score -= 0.35

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
            score += max(0.0, 0.04 - (car.mileage / 5_000_000))

        if color and _contains_normalized(car.color, color):
            score += 0.05
        if engine and _contains_normalized(car.engine, engine):
            score += 0.05
        if drive and _contains_normalized(car.drive, drive):
            score += 0.05
        if body_type and _contains_normalized(car.body_type, body_type):
            score += 0.03

        power_min = criteria.get("power_min")
        if power_min and car.power:
            if car.power >= power_min:
                score += 0.05
            else:
                score -= 0.05

        haystack = self._full_haystack(car)
        query_tokens = _tokenize(query_text)
        if query_tokens:
            overlap = sum(1 for token in query_tokens if _term_in_text(haystack, token))
            score += min(overlap * 0.045, 0.18)

        for token in criteria.get("must_have", []):
            if token and self._matches_feature_or_term(car, token):
                score += 0.08
            elif criteria.get("_strict_model"):
                score -= 0.18
        for token in criteria.get("nice_to_have", []):
            if token and self._matches_feature_or_term(car, token):
                score += 0.025
        for token in criteria.get("feature_terms", []):
            if token and self._matches_feature_or_term(car, token):
                score += 0.1

        if car.url:
            score += 0.04
        else:
            score -= 0.15

        if car.sale_status:
            if car.sale_status.lower() == "onsale":
                score += 0.04
            else:
                score -= 0.25

        if car.stock_state.lower() == "in":
            score += 0.03

        return score

    def _explain_match(self, car: CanonicalCar, criteria: dict[str, Any], query_text: str) -> dict[str, list[str]]:
        matched_fields: list[str] = []
        matched_terms: list[str] = []

        field_map = {
            "brand": car.brand,
            "model": car.model,
            "pseudo_model": car.pseudo_model,
            "modification": car.modification,
            "equipment": car.equipment,
            "generation": car.generation,
            "description": car.description,
        }

        terms = _unique(
            _tokenize(query_text)
            + _normalize_string_list(criteria.get("brand"))
            + _normalize_string_list(criteria.get("model"))
            + criteria.get("must_have", [])
            + criteria.get("nice_to_have", [])
            + criteria.get("feature_terms", [])
        )

        for term in terms:
            for field_name, value in field_map.items():
                if term in FEATURE_ALIASES:
                    matched = any(_term_in_text(value, marker) for marker in FEATURE_ALIASES[term])
                else:
                    matched = _term_in_text(value, term)
                if matched:
                    matched_fields.append(field_name)
                    matched_terms.append(term)

        highlights = self._extract_highlights(car, terms)
        if not highlights:
            highlights = _unique([car.modification, car.equipment])[:2]

        return {
            "matched_fields": _unique(matched_fields),
            "matched_terms": _unique(matched_terms),
            "spec_highlights": highlights,
        }

    def _extract_highlights(self, car: CanonicalCar, terms: list[str]) -> list[str]:
        lines: list[str] = []
        source = "\n".join([car.equipment, car.modification, car.description])
        for raw_line in source.splitlines():
            line = " ".join(raw_line.strip(" •-*\t").split())
            if len(line) < 4:
                continue
            if len(line) > 180:
                line = _truncate_text(line, 180)
            if any(self._line_matches_term(line, term) for term in terms):
                lines.append(line)
        return _unique(lines)[:4]

    def _line_matches_term(self, line: str, term: str) -> bool:
        if term in FEATURE_ALIASES:
            return any(_term_in_text(line, marker) for marker in FEATURE_ALIASES[term])
        return _term_in_text(line, term)
