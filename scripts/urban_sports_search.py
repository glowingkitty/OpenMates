"""
Urban Sports Club public search client.

This script uses the same public, server-rendered search endpoints used by
urbansportsclub.com for logged-out venue and activity discovery. The official
partner API documented at docs.urbansportsclub.io requires a contract and
credentials; it is not the consumer search surface. The useful public endpoints
found during research are /en/venues and /en/activities with query params such
as city_id, business_type[], plan_type, date, category, venue, district, and
type[]. Results are parsed from stable result card markup in the returned HTML.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any, Iterable
from urllib.parse import urlencode, urljoin

import requests


BASE_URL = "https://urbansportsclub.com"
DEFAULT_LANGUAGE = "en"
DEFAULT_CITY_ID = "1"  # Berlin
DEFAULT_BUSINESS_TYPE = "b2c"
DEFAULT_PLAN_TYPE = "1"  # Essential
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
UNLIMITED_SPOTS_SENTINEL = 2_147_483_647


@dataclass(frozen=True)
class City:
    id: str
    name: str
    country: str | None = None


@dataclass(frozen=True)
class Venue:
    address_id: str | None
    position: int | None
    name: str
    url: str
    disciplines: list[str]
    district: str | None
    street: str | None
    plans: list[str]
    image_url: str | None


@dataclass(frozen=True)
class UrbanClass:
    appointment_id: str | None
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
    plans: list[str]
    spots_left: int | None
    spots_display: str | None
    detail_url: str | None
    image_url: str | None


class UrbanSportsClient:
    def __init__(
        self,
        base_url: str = BASE_URL,
        language: str = DEFAULT_LANGUAGE,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.language = language.strip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": DEFAULT_USER_AGENT,
            }
        )

    def search_venues(
        self,
        *,
        city_id: str,
        plan_type: str,
        business_type: str,
        pages: int,
        query: str | None = None,
        category: str | None = None,
        venue: str | None = None,
        district: str | None = None,
        class_type: str | None = None,
        delay_seconds: float = 0.0,
    ) -> list[Venue]:
        results: list[Venue] = []
        for page in range(1, pages + 1):
            html_text = self._get_search_page(
                "venues",
                city_id=city_id,
                plan_type=plan_type,
                business_type=business_type,
                page=page,
                category=category,
                venue=venue,
                district=district,
                class_type=class_type,
            )
            page_results = parse_venues(html_text)
            if query:
                page_results = [item for item in page_results if matches_query(asdict(item), query)]
            results.extend(page_results)
            if page == pages or not has_next_page(html_text, page):
                break
            if delay_seconds:
                time.sleep(delay_seconds)
        return dedupe_venues(results)

    def search_classes(
        self,
        *,
        city_id: str,
        plan_type: str,
        business_type: str,
        start_date: dt.date,
        days: int,
        pages: int,
        query: str | None = None,
        category: str | None = None,
        venue: str | None = None,
        district: str | None = None,
        class_type: str | None = None,
        min_spots: int = 1,
        delay_seconds: float = 0.0,
    ) -> list[UrbanClass]:
        results: list[UrbanClass] = []
        for day_offset in range(days):
            search_date = start_date + dt.timedelta(days=day_offset)
            for page in range(1, pages + 1):
                html_text = self._get_search_page(
                    "activities",
                    city_id=city_id,
                    plan_type=plan_type,
                    business_type=business_type,
                    page=page,
                    date=search_date.isoformat(),
                    category=category,
                    venue=venue,
                    district=district,
                    class_type=class_type,
                )
                page_results = parse_classes(html_text, search_date.isoformat())
                page_results = [item for item in page_results if class_has_min_spots(item, min_spots)]
                if query:
                    page_results = [item for item in page_results if matches_query(asdict(item), query)]
                results.extend(page_results)
                if page == pages or not has_next_page(html_text, page):
                    break
                if delay_seconds:
                    time.sleep(delay_seconds)
            if delay_seconds and day_offset != days - 1:
                time.sleep(delay_seconds)
        return dedupe_classes(results)

    def list_cities(self) -> list[City]:
        html_text = self._get_search_page(
            "venues",
            city_id=DEFAULT_CITY_ID,
            plan_type=DEFAULT_PLAN_TYPE,
            business_type=DEFAULT_BUSINESS_TYPE,
            page=1,
        )
        return parse_cities(html_text)

    def resolve_city_id(self, city_name: str) -> str:
        normalized = normalize_text(city_name)
        matches = [city for city in self.list_cities() if normalize_text(city.name) == normalized]
        if not matches:
            partial = [city for city in self.list_cities() if normalized in normalize_text(city.name)]
            suggestions = ", ".join(f"{city.name}={city.id}" for city in partial[:8])
            suffix = f" Did you mean one of: {suggestions}?" if suggestions else ""
            raise ValueError(f"Could not resolve city name {city_name!r}.{suffix}")
        return matches[0].id

    def _get_search_page(self, endpoint: str, **params: str | int | None) -> str:
        url = self._build_url(endpoint, params)
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def _build_url(self, endpoint: str, params: dict[str, str | int | None]) -> str:
        query: list[tuple[str, str]] = []
        for key, value in params.items():
            if value in (None, ""):
                continue
            query_key = "business_type[]" if key == "business_type" else key
            query.append((query_key, str(value)))
        return f"{self.base_url}/{self.language}/{endpoint}?{urlencode(query)}"


def parse_venues(html_text: str) -> list[Venue]:
    venues: list[Venue] = []
    for chunk in split_result_chunks(html_text, "smm-studio-snippet b-studio-item"):
        name = first_text(chunk, r'class="smm-studio-snippet__studio-link"[^>]*>(.*?)</a>')
        href = first_attr(chunk, r'class="smm-studio-snippet__studio-link"[^>]*href="([^"]+)"')
        if not name or not href:
            continue
        address = first_text(chunk, r'<p class="smm-studio-snippet__address">(.*?)</p>')
        district, street = parse_address(address)
        venues.append(
            Venue(
                address_id=first_attr(chunk, r'data-address-id="([^"]+)"'),
                position=to_int(first_attr(chunk, r'data-position="([^"]+)"')),
                name=name,
                url=urljoin(BASE_URL, href),
                disciplines=all_text(chunk, r'<div class="disciplines">(.*?)</div>'),
                district=district,
                street=street,
                plans=all_text(chunk, r'class="smm-studio-snippet__studio-plan"[^>]*>(.*?)</span>'),
                image_url=first_attr(chunk, r'data-src="([^"]+)"'),
            )
        )
    return venues


def parse_classes(html_text: str, date: str) -> list[UrbanClass]:
    classes: list[UrbanClass] = []
    for chunk in split_result_chunks(html_text, "smm-class-snippet"):
        appointment_id = first_attr(chunk, r'data-appointment-id="([^"]+)"')
        if not appointment_id:
            continue
        tracking = parse_class_tracking(chunk)
        name = tracking.get("name") or first_text(
            chunk,
            r'class="smm-class-link title"[^>]*>(.*?)</a>',
        )
        if not name:
            continue
        venue_href = first_attr(chunk, r'class="smm-studio-link visible-lg"[^>]*href="([^"]+)"')
        detail_href = first_attr(chunk, r'data-href="([^"]*class-details/[^"]+)"')
        classes.append(
            UrbanClass(
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
                plans=all_text(chunk, r'class="smm-class-snippet__class-plan"[^>]*>(.*?)</span>'),
                spots_left=to_int(tracking.get("spots_left")),
                spots_display=format_spots(to_int(tracking.get("spots_left"))),
                detail_url=urljoin(BASE_URL, detail_href) if detail_href else None,
                image_url=first_attr(chunk, r"background-image:\s*url\('([^']+)'\)"),
            )
        )
    return classes


def parse_cities(html_text: str) -> list[City]:
    select_match = re.search(r'<select[^>]+id="city_id"[^>]*>(.*?)</select>', html_text, re.S | re.I)
    if not select_match:
        return []
    cities: list[City] = []
    country: str | None = None
    for token in re.finditer(r'<optgroup[^>]*label="([^"]+)"[^>]*>|<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', select_match.group(1), re.S | re.I):
        if token.group(1):
            country = clean_text(token.group(1))
            continue
        city_id = clean_text(token.group(2) or "")
        name = clean_text(token.group(3) or "")
        if city_id and name:
            cities.append(City(id=city_id, name=name, country=country))
    return cities


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
    body = match.group(1)
    fields: dict[str, str] = {}
    for field in ("id", "name", "category", "type", "spots_left", "search_position"):
        value_match = re.search(rf'"{field}"\s*:\s*("(?:\\.|[^"])*"|[^,}}]+)', body)
        if value_match:
            fields[field] = decode_tracking_value(value_match.group(1).strip())
    return fields


def decode_tracking_value(raw_value: str) -> str:
    if raw_value.startswith('"') and raw_value.endswith('"'):
        try:
            decoded = json.loads(raw_value)
        except json.JSONDecodeError:
            return raw_value.strip('"').replace(r"\/", "/")
        return str(decoded)
    return raw_value.strip()


def has_next_page(html_text: str, current_page: int) -> bool:
    next_page = current_page + 1
    return bool(re.search(rf'[?&amp;]page={next_page}(?:["&])', html_text))


def first_attr(chunk: str, pattern: str) -> str | None:
    match = re.search(pattern, chunk, re.S | re.I)
    return clean_text(match.group(1)) if match else None


def first_text(chunk: str, pattern: str) -> str | None:
    match = re.search(pattern, chunk, re.S | re.I)
    return clean_text(match.group(1)) if match else None


def all_text(chunk: str, pattern: str) -> list[str]:
    return [clean_text(value) for value in re.findall(pattern, chunk, re.S | re.I) if clean_text(value)]


def clean_text(value: str) -> str:
    without_tags = re.sub(r'<[^>]+>', ' ', html.unescape(value))
    return re.sub(r'\s+', ' ', without_tags).strip()


def parse_address(address: str | None) -> tuple[str | None, str | None]:
    if not address:
        return None, None
    street = first_text(address, r'class="smm-studio-snippet__address-street"[^>]*>(.*?)</span>')
    without_street = re.sub(r'<span class="smm-studio-snippet__address-street".*?</span>', '', address, flags=re.S | re.I)
    district = clean_text(without_street).rstrip(",") or None
    return district, street


def to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def format_spots(spots_left: int | None) -> str | None:
    if spots_left is None:
        return None
    if spots_left >= UNLIMITED_SPOTS_SENTINEL:
        return "unlimited"
    return str(spots_left)


def class_has_min_spots(item: UrbanClass, min_spots: int) -> bool:
    if item.spots_left is None:
        return False
    return item.spots_left >= min_spots or item.spots_left >= UNLIMITED_SPOTS_SENTINEL


def matches_query(item: dict[str, Any], query: str) -> bool:
    needle = normalize_text(query)
    haystack = normalize_text(json.dumps(item, ensure_ascii=False))
    return needle in haystack


def normalize_text(value: str) -> str:
    return re.sub(r'\s+', ' ', value).casefold().strip()


def dedupe_venues(items: list[Venue]) -> list[Venue]:
    seen: set[tuple[str | None, str]] = set()
    deduped: list[Venue] = []
    for item in items:
        key = (item.address_id, item.url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def dedupe_classes(items: list[UrbanClass]) -> list[UrbanClass]:
    seen: set[tuple[str | None, str]] = set()
    deduped: list[UrbanClass] = []
    for item in items:
        key = (item.appointment_id, item.date)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def print_results(items: list[Any], output_format: str, limit: int | None) -> None:
    limited = items[:limit] if limit else items
    if output_format == "json":
        print(json.dumps([asdict(item) for item in limited], ensure_ascii=False, indent=2))
        return
    if not limited:
        print("No results.")
        return
    for item in limited:
        data = asdict(item)
        if isinstance(item, City):
            suffix = f" ({data['country']})" if data["country"] else ""
            print(f"{data['id']:>5}  {data['name']}{suffix}")
            continue
        if isinstance(item, Venue):
            print(f"{data['position'] or '-':>3}  {data['name']}")
            print(f"     {', '.join(data['disciplines']) or '-'}")
            address = ", ".join(part for part in [data['district'], data['street']] if part)
            print(f"     {address or '-'}")
            print(f"     plans: {', '.join(data['plans']) or '-'}")
            print(f"     {data['url']}")
            continue
        print(f"{data['date']} {data['time_range'] or '--:--'}  {data['name']}")
        print(f"     {data['venue_name'] or '-'} · {data['district'] or '-'} · {data['category'] or '-'}")
        print(f"     spots: {data['spots_display'] or '-'} · plans: {', '.join(data['plans']) or '-'}")
        if data['detail_url']:
            print(f"     {data['detail_url']}")


def add_common_search_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--city-id", default=DEFAULT_CITY_ID, help="Urban Sports city_id. Defaults to Berlin (1).")
    parser.add_argument("--city", help="Resolve a city name to city_id by reading the website city selector.")
    parser.add_argument("--plan-type", default=DEFAULT_PLAN_TYPE, help="Plan id: 1 Essential, 2 Classic, 3 Premium, 6 Max.")
    parser.add_argument("--business-type", default=DEFAULT_BUSINESS_TYPE, help="Usually b2c for private members.")
    parser.add_argument("--category", help="Category/activity id from the website filters.")
    parser.add_argument("--venue", help="Venue id from the website filters.")
    parser.add_argument("--district", help="District id from the website filters.")
    parser.add_argument("--class-type", dest="class_type", help="Class type filter, for example live or onsite.")
    parser.add_argument("--query", help="Local text filter applied to parsed results.")
    parser.add_argument("--pages", type=int, default=1, help="Maximum result pages to fetch per search/date.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum results to print. Use 0 for no limit.")
    parser.add_argument("--format", choices=("table", "json"), default="table", help="Output format.")
    parser.add_argument("--delay", type=float, default=0.0, help="Optional delay between paginated requests.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="HTTP timeout in seconds.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search Urban Sports Club venues and upcoming classes from public web search endpoints.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 scripts/urban_sports_search.py venues --city Berlin --query yoga --limit 10\n"
            "  python3 scripts/urban_sports_search.py classes --city Berlin --query cycling --days 7 --pages 2\n"
            "  python3 scripts/urban_sports_search.py cities --query lisbon --format json\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    venue_parser = subparsers.add_parser("venues", help="Search location/venue cards.")
    add_common_search_args(venue_parser)

    class_parser = subparsers.add_parser("classes", help="Search upcoming class cards with available spots.")
    add_common_search_args(class_parser)
    class_parser.add_argument("--date", help="Start date as YYYY-MM-DD. Defaults to today.")
    class_parser.add_argument("--days", type=int, default=1, help="Number of days to search from --date.")
    class_parser.add_argument("--min-spots", type=int, default=1, help="Minimum available spots. Defaults to 1.")

    city_parser = subparsers.add_parser("cities", help="List known city ids from the website selector.")
    city_parser.add_argument("--query", help="Local text filter for city names/countries.")
    city_parser.add_argument("--format", choices=("table", "json"), default="table")
    city_parser.add_argument("--limit", type=int, default=50)
    city_parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    return parser


def resolve_city_id(client: UrbanSportsClient, args: argparse.Namespace) -> str:
    if args.city:
        return client.resolve_city_id(args.city)
    return args.city_id


def parse_start_date(value: str | None) -> dt.date:
    if not value:
        return dt.date.today()
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--date must use YYYY-MM-DD") from exc


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    client = UrbanSportsClient(timeout=args.timeout)

    try:
        if args.command == "cities":
            cities = client.list_cities()
            if args.query:
                cities = [city for city in cities if matches_query(asdict(city), args.query)]
            print_results(cities, args.format, args.limit)
            return 0

        city_id = resolve_city_id(client, args)
        limit = None if args.limit == 0 else args.limit
        if args.command == "venues":
            venues = client.search_venues(
                city_id=city_id,
                plan_type=args.plan_type,
                business_type=args.business_type,
                pages=max(args.pages, 1),
                query=args.query,
                category=args.category,
                venue=args.venue,
                district=args.district,
                class_type=args.class_type,
                delay_seconds=max(args.delay, 0.0),
            )
            print_results(venues, args.format, limit)
            return 0

        classes = client.search_classes(
            city_id=city_id,
            plan_type=args.plan_type,
            business_type=args.business_type,
            start_date=parse_start_date(args.date),
            days=max(args.days, 1),
            pages=max(args.pages, 1),
            query=args.query,
            category=args.category,
            venue=args.venue,
            district=args.district,
            class_type=args.class_type,
            min_spots=max(args.min_spots, 0),
            delay_seconds=max(args.delay, 0.0),
        )
        print_results(classes, args.format, limit)
        return 0
    except requests.RequestException as exc:
        print(f"Urban Sports request failed: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
