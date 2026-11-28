"""Reuse of skill result cards inside an assistant-authored results block.

A skill (for example travel ``search_connections``) already produced complete
result cards: legs, stations with coordinates, platforms, provider and booking
link. When the answer then presents some of those results in an
``openmates_embeds`` block, re-authoring them creates thin copies without that
data (no map, no booking provider, raw times). Two paths prevent this:

* an explicit ``{"id", "existing": "<embed_ref>"}`` item may name a skill
  result card of this chat (``skill_result_card_kind``), and
* a newly written ``researched`` item whose identity facts match a skill result
  card of this chat is bound to that card instead (``SkillResultMatcher``).

Candidates come only from the chat's authorized embed_ref index (refs handed to
this turn: history embeds and this turn's skill results); a guessed id never
reaches storage. A candidate must belong to the same owner and chat, be
finished, and its decrypted content must carry the producing skill's identity.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any, Mapping

from toon_format import decode

from backend.apps.ai.utils.authored_result_fences import get_authoring_definitions
from backend.core.api.app.services.authored_existing_cards import record_in_chat
from backend.shared.python_utils.country_codes import iso_country
from backend.shared.python_utils.search_relevance import normalize_url_for_deduplication

logger = logging.getLogger(__name__)

# Bounds the per-carrier lookup work; the index itself holds at most 256 refs.
MAX_SKILL_RESULT_CANDIDATES = 120


def skill_result_card_kind(record: Mapping[str, Any], content: Any) -> str | None:
    """Return the admitted kind of a skill-produced result card, else None.

    Authored cards carry an ``authoring`` block and are handled by
    ``authored_card_kind``; this accepts only plain skill results whose stored
    type and decrypted producer identity match one admitted kind definition.
    """
    if not isinstance(content, dict) or isinstance(content.get("authoring"), dict):
        return None
    for kind, definition in get_authoring_definitions().items():
        if (definition["backend_type"] == record.get("type")
                and content.get("type") in (None, definition["backend_type"])
                and content.get("app_id") == definition["app_id"]
                and content.get("skill_id") == definition["skill_id"]):
            return kind
    return None


def _instant(value: Any) -> str | None:
    """Normalize an ISO timestamp with offset to a comparable UTC instant."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="minutes")


def _connection_key(content: Mapping[str, Any]) -> tuple[str, str] | None:
    """A connection is identified by its exact departure and arrival instants."""
    departure, arrival = _instant(content.get("departure")), _instant(content.get("arrival"))
    if departure is None or arrival is None:
        legs = content.get("legs")
        if isinstance(legs, list) and legs and isinstance(legs[0], dict) and isinstance(legs[-1], dict):
            departure = departure or _instant(legs[0].get("departure"))
            arrival = arrival or _instant(legs[-1].get("arrival"))
    return (departure, arrival) if departure and arrival else None


_DATE_FIELDS = (
    "date_start", "slot_datetime", "date", "check_in", "published_at",
    "publication_date", "available_from", "release_date", "first_air_date",
)
_URL_FIELDS = ("canonical_url", "url", "detail_url", "source_url", "source_page_url",
               "purchase_url", "apply_url", "booking_url", "link")
_IDENTIFIER_FIELDS = ("full_name", "video_id", "icon_id", "part_number", "domain_ascii")


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(re.findall(r"[^\W_]+", "".join(
        char for char in normalized if not unicodedata.combining(char)
    )))


def _first(content: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    return next((value for field in fields if (value := _text(content.get(field)))), "")


def _day(content: Mapping[str, Any]) -> str:
    for field in _DATE_FIELDS:
        value = content.get(field)
        if not isinstance(value, str):
            continue
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            continue
    return ""


def _place(content: Mapping[str, Any]) -> tuple[str, str, str]:
    venue = content.get("venue") or content.get("location")
    venue = venue if isinstance(venue, dict) else {}
    country = venue.get("country") or content.get("venue_country") or content.get("country")
    return (
        iso_country(country) or _text(country),
        _text(venue.get("city")) or _first(content, ("venue_city", "city", "location_name")),
        _text(venue.get("address")) or _first(content, ("venue_address", "formatted_address", "address")),
    )


def _urls(content: Mapping[str, Any], kind: str) -> set[str]:
    fields = (*_URL_FIELDS, "image_url", "public_image_url") if kind == "images.image_result" else _URL_FIELDS
    return {url for field in fields
            if isinstance(raw := content.get(field), str)
            and (url := normalize_url_for_deduplication(raw))}


def _same_result(kind: str, first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    if kind == "travel.connection":
        key = _connection_key(first)
        conflicting_route = any(
            a != b
            for field in ("origin", "destination")
            if (a := _text(first.get(field))) and (b := _text(second.get(field)))
        )
        return key is not None and key == _connection_key(second) and not conflicting_route

    first_place, second_place = _place(first), _place(second)
    first_country, first_city, first_address = first_place
    second_country, second_city, second_address = second_place
    if first_country and second_country and first_country != second_country:
        if bool(iso_country(first_country)) == bool(iso_country(second_country)):
            return False
    if first_city and second_city and first_city != second_city:
        return False
    online = tuple(content.get("online") is True or _text(content.get("event_type")) in {"online", "virtual"}
                   for content in (first, second))
    if kind == "events.event" and online[0] != online[1] and any(first_place + second_place):
        return False
    first_day, second_day = _day(first), _day(second)
    if first_day and second_day and first_day != second_day:
        return False

    for field in _IDENTIFIER_FIELDS:
        identifier = _text(first.get(field))
        if identifier and identifier == _text(second.get(field)):
            return True

    title_fields = ("title", "name", "display_name", "company")
    first_title, second_title = _first(first, title_fields), _first(second, title_fields)
    if kind == "events.event":
        first_title = re.sub(r" (?:19|20)\d{2}$", "", first_title)
        second_title = re.sub(r" (?:19|20)\d{2}$", "", second_title)
    if _urls(first, kind) & _urls(second, kind):
        return not first_title or not second_title or first_title == second_title
    if first_title != second_title or not first_title:
        return False

    if first_address and second_address and first_address != second_address:
        return False
    same_address = bool(first_address and first_address == second_address)
    same_city = bool(first_city and first_city == second_city)
    if kind in {"health.appointment", "fitness.class"}:
        return same_address and first_day == second_day and bool(first_day) and any(
            instant and instant == _instant(second.get(field))
            for field in ("slot_datetime", "date_start")
            if (instant := _instant(first.get(field)))
        )
    if kind == "travel.stay":
        return same_address
    if kind in {"events.event", "weather.weather_day", "news.website", "web.website", "social_media.social_post"}:
        return bool(first_day and first_day == second_day
                    and (same_city or same_address or all(online) or not any(first_place + second_place)))
    return same_address


class SkillResultMatcher:
    """Lazily indexed skill result cards of one chat, keyed per kind by identity facts."""

    def __init__(self, service: Any, index: Mapping[str, Any] | None, *, chat_id: str,
                 user_id_hash: str, user_vault_key_id: str, log_prefix: str = "") -> None:
        self._service = service
        self._index = index if isinstance(index, Mapping) else {}
        self._chat_id = chat_id
        self._user_id_hash = user_id_hash
        self._user_vault_key_id = user_vault_key_id
        self._log_prefix = log_prefix
        self._candidates: dict[str, list[tuple[str, dict[str, Any]]]] | None = None

    async def _load(self) -> dict[str, list[tuple[str, dict[str, Any]]]]:
        candidates: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        embed_ids = list(dict.fromkeys(v for v in self._index.values() if isinstance(v, str) and v))
        for embed_id in embed_ids[-MAX_SKILL_RESULT_CANDIDATES:]:
            record = await self._service._get_cached_embed(embed_id, self._user_vault_key_id, self._log_prefix)
            if (not isinstance(record, dict) or record.get("hashed_user_id") != self._user_id_hash
                    or record.get("status") != "finished" or not record_in_chat(record, self._chat_id)):
                continue
            toon = await self._service._get_cached_embed_toon(embed_id, self._user_vault_key_id, self._log_prefix)
            content = decode(toon) if toon else None
            kind = skill_result_card_kind(record, content)
            if kind is not None:
                candidates.setdefault(kind, []).append((embed_id, content))
        return candidates

    async def match(self, kind: str, content: Mapping[str, Any]) -> str | None:
        """Return the one authorized result this researched item repeats."""
        authoring = content.get("authoring")
        if not isinstance(authoring, dict) or authoring.get("origin") != "researched" or not self._index:
            return None
        if self._candidates is None:
            self._candidates = await self._load()
        matches = [embed_id for embed_id, candidate in self._candidates.get(kind, ())
                   if _same_result(kind, content, candidate)]
        if len(matches) == 1:
            logger.info("%s Authored %s item reuses its skill result card", self._log_prefix, kind)
            return matches[0]
        return None
