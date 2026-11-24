"""Read FOSDEM edition facts from the organizer's public pages."""
from __future__ import annotations

from datetime import date, datetime
import logging
import re
from typing import Any, Mapping

from backend.shared.python_utils.public_web_reader import PublicWebReadError, read_public_web_page
from backend.shared.python_utils.web_result_extraction import excluded_host, excluded_hosts

logger = logging.getLogger(__name__)
_TITLE = re.compile(r"fosdem(?:[ '\u2019]+(20\d{2}|\d{2}))?(?:\s+by\s+fosdem\s+vzw)?", re.IGNORECASE)
_DATES = re.compile(r"^\s*(\d{1,2})(?:\s*(?:&|and|[-–])\s*(\d{1,2}))?\s+([A-Za-z]+)\s+(20\d{2})\s*$", re.MULTILINE)
_ADDRESS = re.compile(
    r"FOSDEM takes place at (?:the )?(?P<venue>[^,\n]+), (?P<city>[^,\n]+), (?P<country>[^,\n.]+)"
    r"[^\n]*\n\n(?:[^\n]+\n){2}(?P<street>[^\n]*\d[^\n]*)",
    re.IGNORECASE,
)
_COORDINATES = re.compile(r"GPS coordinates:\s*latitude ([NS])(\d+(?:\.\d+)?), longitude ([EW])(\d+(?:\.\d+)?)", re.IGNORECASE)


def edition_start(event: Mapping[str, Any]) -> date | None:
    """Accept the conference itself, including provider attribution aliases."""
    match = _TITLE.fullmatch(str(event.get("title", "")).strip())
    if not match:
        return None
    try:
        start = date.fromisoformat(str(event.get("date_start", ""))[:10])
    except ValueError:
        return None
    edition = match[1]
    return start if not edition or str(start.year).endswith(edition) else None


async def _read(url: str) -> str:
    try:
        page = await read_public_web_page(url, timeout_ms=6000)
    except PublicWebReadError as exc:
        logger.info("[events.search] FOSDEM organizer page unavailable: %s", exc.code)
        return ""
    return str(page.get("markdown") or "") if page.get("url") == url else ""


def _edition_dates(home: str, edition: int) -> tuple[str, str] | None:
    match = _DATES.search(home[:1500])
    if not match:
        return None
    day, last, month, year = match.groups()
    try:
        begins = datetime.strptime(f"{day} {month} {year}", "%d %B %Y").date()
        ends = datetime.strptime(f"{last or day} {month} {year}", "%d %B %Y").date()
    except ValueError:
        return None
    if begins.year != edition or ends < begins:
        return None
    return begins.isoformat(), ends.isoformat()


def _venue(transport: str) -> dict[str, Any] | None:
    address = _ADDRESS.search(transport[:2400])
    if not address:
        return None
    venue: dict[str, Any] = {
        "name": address["venue"].strip(), "address": address["street"].strip(),
        "city": address["city"].strip(), "country": address["country"].strip(),
    }
    if coordinates := _COORDINATES.search(transport[:2400]):
        north_south, latitude, east_west, longitude = coordinates.groups()
        venue["lat"] = float(latitude) * (-1 if north_south.upper() == "S" else 1)
        venue["lon"] = float(longitude) * (-1 if east_west.upper() == "W" else 1)
    return venue


async def read_edition(edition: int) -> dict[str, Any] | None:
    """Use organizer data for the specified year."""
    root = f"https://fosdem.org/{edition}/"
    about_url = f"{root}about/"
    transport_url = f"{root}practical/transportation/"
    if excluded_host(root, excluded_hosts()):
        return None
    dates = _edition_dates(await _read(root), edition)
    if dates is None:
        return None
    # The public reader spaces out page requests to a host. Read these sequentially
    # so parallel requests do not spend their whole timeout waiting on that limit.
    transport = await _read(transport_url)
    about = await _read(about_url)
    result: dict[str, Any] = {
        "title": f"FOSDEM {edition}", "url": root, "date_start": dates[0], "date_end": dates[1],
        "source_page_url": root, "source_page_title": f"FOSDEM {edition}",
    }
    if venue := _venue(transport):
        result.update(venue=venue, event_type="physical", venue_source_url=transport_url)
    about_lower = about.casefold()
    if all(term in about_lower for term in ("non-commercial", "volunteers", "software developers", "talks and presentations")):
        result["description"] = (
            "FOSDEM is a free, volunteer-run conference for free and open source software developers. "
            "Participants meet other projects and attend talks and presentations by project leaders and contributors."
        )
        result["description_source_url"] = about_url
    if "fosdem vzw is a belgian non-profit" in about_lower:
        result["organizer"] = "FOSDEM vzw"
    return result
