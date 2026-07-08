# backend/shared/providers/urban_sports/parsers.py
#
# HTML and JSON-LD parsers for Urban Sports Club public discovery pages.
#
# The logged-out web pages expose venue and activity cards as server-rendered
# markup, plus detail pages with schema.org LocalBusiness JSON-LD. Keep parsing
# deterministic and fixture-backed so live provider layout changes fail loudly.

from __future__ import annotations

from dataclasses import asdict, dataclass
import html
import json
import math
import re
from typing import Any, Iterable, Sequence
from urllib.parse import urljoin


BASE_URL = "https://urbansportsclub.com"
UNLIMITED_SPOTS_SENTINEL = 2_147_483_647


@dataclass(frozen=True)
class UrbanSportsVenueCard:
    address_id: str | None
    position: int | None
    name: str
    url: str
    disciplines: list[str]
    district: str | None
    street: str | None
    plans_required: list[str]
    image_url: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UrbanSportsVenueDetail:
    url: str
    name: str | None
    street: str | None
    postal_code: str | None
    city: str | None
    country: str | None
    lat: float | None
    lon: float | None
    image_url: str | None
    rating: float | None
    rating_count: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UrbanSportsClassCard:
    appointment_id: str
    address_id: str | None
    position: int | None
    name: str
    category: str | None
    class_type: str | None
    date: str
    time_range: str | None
    venue_name: str | None
    venue_url: str | None
    district: str | None
    plans_required: list[str]
    spots_left: int | None
    spots_display: str | None
    detail_url: str | None
    image_url: str | None

    @property
    def attendance_mode(self) -> str:
        class_type = normalize_text(self.class_type or "")
        if class_type in {"live", "online", "virtual"}:
            return "online"
        return "onsite"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["attendance_mode"] = self.attendance_mode
        return data


def parse_venue_cards(html_text: str) -> list[UrbanSportsVenueCard]:
    venues: list[UrbanSportsVenueCard] = []
    for chunk in split_result_chunks(html_text, "smm-studio-snippet b-studio-item"):
        name = first_text(chunk, r'class="smm-studio-snippet__studio-link"[^>]*>(.*?)</a>')
        href = first_attr(chunk, r'class="smm-studio-snippet__studio-link"[^>]*href="([^"]+)"')
        if not name or not href:
            continue
        address = first_text(chunk, r'<p class="smm-studio-snippet__address">(.*?)</p>')
        district, street = parse_address(address)
        venues.append(
            UrbanSportsVenueCard(
                address_id=first_attr(chunk, r'data-address-id="([^"]+)"'),
                position=to_int(first_attr(chunk, r'data-position="([^"]+)"')),
                name=name,
                url=urljoin(BASE_URL, href),
                disciplines=all_text(chunk, r'<div class="disciplines">(.*?)</div>'),
                district=district,
                street=street,
                plans_required=all_text(chunk, r'class="smm-studio-snippet__studio-plan"[^>]*>(.*?)</span>'),
                image_url=first_attr(chunk, r'data-src="([^"]+)"'),
            )
        )
    return dedupe_venues(venues)


def parse_activity_cards(html_text: str, date: str) -> list[UrbanSportsClassCard]:
    classes: list[UrbanSportsClassCard] = []
    for chunk in split_result_chunks(html_text, "smm-class-snippet"):
        appointment_id = first_attr(chunk, r'data-appointment-id="([^"]+)"')
        if not appointment_id:
            continue
        tracking = parse_class_tracking(chunk)
        name = tracking.get("name") or first_text(chunk, r'class="smm-class-link title"[^>]*>(.*?)</a>')
        if not name:
            continue
        venue_href = first_attr(chunk, r'class="smm-studio-link visible-lg"[^>]*href="([^"]+)"')
        detail_href = first_attr(chunk, r'data-href="([^"]*class-details/[^"]+)"')
        classes.append(
            UrbanSportsClassCard(
                appointment_id=appointment_id,
                address_id=first_attr(chunk, r'data-address-id="([^"]+)"'),
                position=to_int(tracking.get("search_position")),
                name=name,
                category=tracking.get("category") or first_text(chunk, r'class="smm-class-link title"[^>]*>.*?</a>\s*<p>(.*?)</p>'),
                class_type=tracking.get("type"),
                date=date,
                time_range=first_text(chunk, r'class="smm-class-snippet__class-time"[^>]*>(.*?)</p>'),
                venue_name=first_text(chunk, r'class="smm-studio-link visible-lg"[^>]*>.*?</i>(.*?)</a>'),
                venue_url=urljoin(BASE_URL, venue_href) if venue_href else None,
                district=first_text(chunk, r'class="district"[^>]*>(.*?)</span>'),
                plans_required=all_text(chunk, r'class="smm-class-snippet__class-plan"[^>]*>(.*?)</span>'),
                spots_left=to_int(tracking.get("spots_left")),
                spots_display=format_spots(to_int(tracking.get("spots_left"))),
                detail_url=urljoin(BASE_URL, detail_href) if detail_href else None,
                image_url=first_attr(chunk, r"background-image:\s*url\('([^']+)'\)"),
            )
        )
    return classes


def parse_venue_detail(html_text: str, *, url: str) -> UrbanSportsVenueDetail:
    data = _find_local_business_json_ld(html_text) or {}
    address = data.get("address") if isinstance(data.get("address"), dict) else {}
    geo = data.get("geo") if isinstance(data.get("geo"), dict) else {}
    rating = data.get("aggregateRating") if isinstance(data.get("aggregateRating"), dict) else {}

    return UrbanSportsVenueDetail(
        url=url,
        name=clean_optional(data.get("name")),
        street=clean_optional(address.get("streetAddress")),
        postal_code=clean_optional(address.get("postalCode")),
        city=clean_optional(address.get("addressLocality")),
        country=clean_optional(address.get("addressCountry")),
        lat=to_float(geo.get("latitude")),
        lon=to_float(geo.get("longitude")),
        image_url=clean_optional(data.get("image")),
        rating=to_float(rating.get("ratingValue")),
        rating_count=to_int(clean_optional(rating.get("ratingCount"))),
    )


def filter_by_plan[T](items: Sequence[T], plan: str | None) -> list[T]:
    normalized = normalize_plan_filter(plan)
    if normalized is None:
        return list(items)
    return [item for item in items if normalized in {normalize_text(plan_name) for plan_name in getattr(item, "plans_required", [])}]


def dedupe_venues(items: Iterable[UrbanSportsVenueCard]) -> list[UrbanSportsVenueCard]:
    seen: set[tuple[str | None, str]] = set()
    deduped: list[UrbanSportsVenueCard] = []
    for item in items:
        key = (item.address_id, item.url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def dedupe_classes(items: Iterable[UrbanSportsClassCard]) -> list[UrbanSportsClassCard]:
    seen: set[tuple[str, str]] = set()
    deduped: list[UrbanSportsClassCard] = []
    for item in items:
        key = (item.appointment_id, item.date)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def class_has_min_spots(item: UrbanSportsClassCard, min_spots: int) -> bool:
    if item.spots_left is None:
        return False
    return item.spots_left >= min_spots or item.spots_left >= UNLIMITED_SPOTS_SENTINEL


def haversine_km(lat1: float, lon1: float, lat2: float | None, lon2: float | None) -> float:
    if lat2 is None or lon2 is None:
        return math.inf
    radius_km = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def matches_query(item: dict[str, Any], query: str | None) -> bool:
    if not query:
        return True
    return normalize_text(query) in normalize_text(json.dumps(item, ensure_ascii=False))


def normalize_plan_filter(plan: str | None) -> str | None:
    if not plan:
        return None
    normalized = normalize_text(plan)
    aliases = {
        "s": "essential",
        "m": "classic",
        "l": "premium",
        "xl": "max",
        "essential plan": "essential",
        "classic plan": "classic",
        "premium plan": "premium",
        "max plan": "max",
    }
    return aliases.get(normalized, normalized)


def split_result_chunks(html_text: str, marker: str) -> Iterable[str]:
    start_pattern = re.compile(
        rf'<div[^>]+class="[^"]*(?<![A-Za-z0-9_-]){re.escape(marker)}(?![A-Za-z0-9_-])[^"]*"[^>]*>',
        re.I,
    )
    starts = [match.start() for match in start_pattern.finditer(html_text)]
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else html_text.find("</section>", start)
        if end == -1:
            end = len(html_text)
        yield html_text[start:end]


def parse_class_tracking(chunk: str) -> dict[str, str]:
    match = re.search(r'"class"\s*:\s*\{(.*?)\}', html.unescape(chunk), re.S)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for field in ("id", "name", "category", "type", "spots_left", "search_position"):
        value_match = re.search(rf'"{field}"\s*:\s*("(?:\\.|[^"])*"|[^,}}]+)', match.group(1))
        if value_match:
            fields[field] = decode_tracking_value(value_match.group(1).strip())
    return fields


def parse_address(address: str | None) -> tuple[str | None, str | None]:
    if not address:
        return None, None
    street = first_text(address, r'class="smm-studio-snippet__address-street"[^>]*>(.*?)</span>')
    without_street = re.sub(r'<span class="smm-studio-snippet__address-street".*?</span>', "", address, flags=re.S | re.I)
    district = clean_text(without_street).rstrip(",") or None
    return district, street


def first_attr(chunk: str, pattern: str) -> str | None:
    match = re.search(pattern, chunk, re.S | re.I)
    return clean_text(match.group(1)) if match else None


def first_text(chunk: str, pattern: str) -> str | None:
    match = re.search(pattern, chunk, re.S | re.I)
    return clean_text(match.group(1)) if match else None


def all_text(chunk: str, pattern: str) -> list[str]:
    return [clean_text(value) for value in re.findall(pattern, chunk, re.S | re.I) if clean_text(value)]


def clean_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", html.unescape(str(value)))
    return re.sub(r"\s+", " ", without_tags).strip()


def clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = clean_text(str(value))
    return cleaned or None


def decode_tracking_value(raw_value: str) -> str:
    if raw_value.startswith('"') and raw_value.endswith('"'):
        try:
            return str(json.loads(raw_value))
        except json.JSONDecodeError:
            return raw_value.strip('"').replace(r"\/", "/")
    return raw_value.strip()


def to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_spots(spots_left: int | None) -> str | None:
    if spots_left is None:
        return None
    if spots_left >= UNLIMITED_SPOTS_SENTINEL:
        return "unlimited"
    return str(spots_left)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).casefold().strip()


def _find_local_business_json_ld(html_text: str) -> dict[str, Any] | None:
    for raw_json in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html_text, re.S | re.I):
        try:
            parsed = json.loads(html.unescape(raw_json).strip())
        except json.JSONDecodeError:
            continue
        for candidate in _walk_json_ld(parsed):
            types = candidate.get("@type")
            if types == "LocalBusiness" or (isinstance(types, list) and "LocalBusiness" in types):
                return candidate
    return None


def _walk_json_ld(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _walk_json_ld(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json_ld(item)
