"""Shared normalization and bounded HTTP behavior for public job sources."""

import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit, urlunsplit

import httpx


class ProviderError(Exception):
    """A provider failure containing only safe, caller-visible information."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.skip_depth += 1
        elif self.skip_depth == 0 and tag in {"p", "br", "li", "div", "h1", "h2", "h3"}:
            self.parts.append(" ")


def clean_text(value: object, *, max_length: int = 5000) -> str:
    if not isinstance(value, str):
        return ""
    parser = _TextParser()
    parser.feed(value)
    return re.sub(r"\s+", " ", unescape("".join(parser.parts))).strip()[:max_length]


def safe_url(value: object, *, allowed_hosts: set[str] | None = None) -> str | None:
    """Keep only HTTPS links; strip fragments and reject credentials."""
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.port not in (None, 443):
            return None
        if allowed_hosts and host not in allowed_hosts:
            return None
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    except ValueError:
        return None


def country_matches(requested: str | None, supported: str) -> bool:
    aliases = {"DE": {"DE", "GERMANY", "DEUTSCHLAND"}, "SE": {"SE", "SWEDEN", "SVERIGE"}}
    return not requested or requested.strip().upper() in aliases.get(supported.upper(), {supported.upper()})


def parse_date(value: object) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, ValueError, OSError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def within_days(published_at: str | None, max_days_old: int | None) -> bool:
    if max_days_old is None:
        return True
    date = parse_date(published_at)
    return date is not None and date >= datetime.now(timezone.utc) - timedelta(days=max(0, max_days_old))


def normalize_employment_type(value: object) -> str | None:
    if isinstance(value, list):
        value = next((item for item in value if isinstance(item, str)), None)
    if not isinstance(value, str):
        return None
    token = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "fulltime": "full_time", "full_time": "full_time", "vollzeit": "full_time", "vz": "full_time",
        "parttime": "part_time", "part_time": "part_time", "teilzeit": "part_time", "tz": "part_time",
        "internship": "internship", "praktikum": "internship", "trainee": "internship",
        "contract": "contract", "freelance": "contract", "selbstaendigkeit": "contract",
        "minijob": "part_time", "ausbildung": "apprenticeship", "apprenticeship": "apprenticeship",
    }
    return aliases.get(token)


def job_matches(
    job: dict, *, query: str = "", location: str | None = None, remote: bool | None = None,
    employment_type: str | None = None, max_days_old: int | None = None,
) -> bool:
    if remote is not None and job.get("remote") is not remote:
        return False
    if employment_type:
        wanted_type = normalize_employment_type(employment_type)
        if wanted_type is None or normalize_employment_type(job.get("employment_type")) != wanted_type:
            return False
    if location and location.casefold() not in (job.get("location") or "").casefold():
        return False
    if not within_days(job.get("published_at"), max_days_old):
        return False
    haystack = " ".join(str(job.get(key) or "") for key in ("title", "company", "description")).casefold()
    return all(term.casefold() in haystack for term in query.split())


async def fetch_json(
    client: httpx.AsyncClient, url: str, *, params: dict | None = None, headers: dict | None = None,
) -> dict:
    """Retry transient failures at most twice, respecting a short Retry-After."""
    for attempt in range(3):
        try:
            response = await client.get(url, params=params, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == 2:
                raise ProviderError("unavailable", "Job source is temporarily unavailable.") from exc
            await asyncio.sleep(0.2 * (2 ** attempt))
            continue
        if response.status_code == 429:
            if attempt == 2:
                raise ProviderError("rate_limited", "Job source is rate limited.")
            raw = response.headers.get("Retry-After", "")
            try:
                delay = float(raw)
            except ValueError:
                try:
                    delay = (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    delay = 0.5
            await asyncio.sleep(min(2.0, max(0.0, delay)))
            continue
        if response.status_code >= 500 and attempt < 2:
            await asyncio.sleep(0.2 * (2 ** attempt))
            continue
        if response.status_code >= 400:
            raise ProviderError("unavailable", "Job source is temporarily unavailable.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("invalid_response", "Job source returned invalid data.") from exc
        if not isinstance(payload, dict):
            raise ProviderError("invalid_response", "Job source returned invalid data.")
        return payload
    raise ProviderError("unavailable", "Job source is temporarily unavailable.")
