"""Fetch published SRT/WebVTT captions through the official CCC GraphQL API.

Only the public lecture slug and selected caption URL leave the server. No
OpenMates identifiers, cookies, proxy credentials or chat text are sent to CCC.
API reference: https://github.com/voc/voctoweb#public-graphql-api
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from urllib.parse import urljoin, urlparse

import httpx

from backend.shared.testing.caching_http_transport import create_http_client
from .models import Caption, MediaCCCTranscript

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://media.ccc.de/graphql"
FETCH_TIMEOUT_SECONDS = 45.0
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_ATTEMPTS = 3
# CCC's subtitle CDN currently redirects to Selfnet's c3subtitles mirror.
# Fail closed if a new mirror is introduced; never follow arbitrary API URLs.
CAPTION_HOSTS = {"cdn.media.ccc.de", "static.media.ccc.de", "mirror.selfnet.de"}
SUBTITLE_MIME_TYPES = {"application/x-subrip", "application/srt", "text/srt", "text/vtt"}
LECTURE_QUERY = """query TranscriptCaptions($slug: ID!) {
  lectureBySlug(slug: $slug) {
    title
    originalLanguage
    subtitles { url mimeType language }
  }
}"""
LANGUAGE_ALIASES = {
    "eng": "en", "deu": "de", "ger": "de", "fra": "fr", "fre": "fr",
    "spa": "es", "ita": "it", "por": "pt", "nld": "nl", "dut": "nl",
    "ces": "cs", "cze": "cs", "pol": "pl", "rus": "ru", "ukr": "uk",
    "jpn": "ja", "zho": "zh", "chi": "zh", "kor": "ko", "ara": "ar",
    "tur": "tr", "swe": "sv", "fin": "fi", "dan": "da", "nor": "no",
}
TIMING_LINE = re.compile(
    r"^(?P<start>(?:\d+:)?[0-5]\d:[0-5]\d[.,]\d{3})\s+-->\s+"
    r"(?P<end>(?:\d+:)?[0-5]\d:[0-5]\d[.,]\d{3})(?:\s+.*)?$"
)


class MediaCCCError(ValueError):
    """A safe, actionable provider failure, including unavailable captions."""


def extract_media_ccc_slug(url: str) -> str | None:
    """Accept canonical HTTPS talk URLs only; query/fragment never reach CCC."""
    try:
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.hostname != "media.ccc.de"
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            return None
        match = re.fullmatch(r"/v/([A-Za-z0-9][A-Za-z0-9_-]{0,255})/?", parsed.path)
        return match.group(1) if match else None
    except ValueError:
        return None


def normalize_language(language: str) -> str:
    base = language.lower().replace("_", "-").split("-")[0]
    return LANGUAGE_ALIASES.get(base, base)


def _seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    return sum(float(part) * 60 ** index for index, part in enumerate(reversed(parts)))


def parse_captions(content: str) -> list[Caption]:
    """Normalize SRT and WebVTT cues, excluding headers, settings and markup."""
    captions = []
    content = content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    for block in re.split(r"\n[ \t]*\n", content.strip()):
        lines = block.splitlines()
        if not lines or lines[0].split(" ", 1)[0] in {"WEBVTT", "NOTE", "STYLE", "REGION"}:
            continue
        for index, line in enumerate(lines):
            if "-->" not in line:
                continue
            timing = TIMING_LINE.fullmatch(line.strip())
            if not timing:
                raise MediaCCCError("media.ccc.de returned invalid caption timing.")
            start, end = _seconds(timing["start"]), _seconds(timing["end"])
            if end <= start:
                raise MediaCCCError("media.ccc.de returned invalid caption timing.")
            text = html.unescape(re.sub(r"<[^>]*>", "", " ".join(lines[index + 1:]))).strip()
            if text:
                captions.append(Caption(start=start, duration=end - start, text=text))
            break
    if not captions:
        raise MediaCCCError("media.ccc.de returned empty or invalid captions.")
    return captions


def _validate_caption_url(url: str) -> None:
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in CAPTION_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise MediaCCCError("media.ccc.de returned an unsupported caption download host.")


class MediaCCCClient:
    """Public, free API wrapper; injected HTTP client supports deterministic tests."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client

    async def _request(self, client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
        for attempt in range(MAX_ATTEMPTS):
            try:
                async with client.stream(method, url, follow_redirects=False, **kwargs) as response:
                    if response.status_code not in {429, 502, 503, 504} or attempt == MAX_ATTEMPTS - 1:
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > MAX_RESPONSE_BYTES:
                                raise MediaCCCError("media.ccc.de caption response exceeded the size limit.")
                        # aiter_bytes decodes compression; do not decode it a second time.
                        headers = {k: v for k, v in response.headers.items()
                                   if k.lower() not in {"content-encoding", "content-length", "transfer-encoding"}}
                        result = httpx.Response(response.status_code, headers=headers,
                                                content=bytes(body), request=response.request)
                        if not result.is_redirect:
                            result.raise_for_status()
                        return result
                    retry_after = response.headers.get("retry-after", "")
            except httpx.TransportError:
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                retry_after = ""
            delay = min(float(retry_after), 5.0) if retry_after.isdigit() else 0.5 * 2 ** attempt
            logger.warning("Retrying media.ccc.de request after transient provider failure (attempt %d)", attempt + 1)
            await asyncio.sleep(delay)
        raise MediaCCCError("media.ccc.de request failed.")  # defensive

    async def _fetch(self, client: httpx.AsyncClient, slug: str, languages: list[str] | None) -> MediaCCCTranscript:
        response = await self._request(client, "POST", GRAPHQL_URL,
                                       json={"query": LECTURE_QUERY, "variables": {"slug": slug}})
        payload = response.json()
        if payload.get("errors"):
            raise MediaCCCError("media.ccc.de could not retrieve the talk's caption metadata.")
        lecture = (payload.get("data") or {}).get("lectureBySlug")
        if not lecture:
            raise MediaCCCError("media.ccc.de talk was not found.")
        tracks = [track for track in lecture.get("subtitles", [])
                  if track.get("mimeType") in SUBTITLE_MIME_TYPES]
        if not tracks:
            raise MediaCCCError("No published captions are available for this media.ccc.de talk. "
                                "A transcript-based summary is unavailable.")
        preferences = languages if languages is not None else ["en", "de", "es", "fr"]
        selected = None
        for language in preferences:
            matches = [track for track in tracks
                       if normalize_language(track.get("language") or "") == normalize_language(language)]
            if matches:
                selected = next((track for track in matches if track["mimeType"] == "text/vtt"), matches[0])
                break
        if selected is None:
            available = sorted({normalize_language(track.get("language") or "") for track in tracks})
            raise MediaCCCError("No media.ccc.de captions match the requested languages. "
                                f"Available languages: {', '.join(available)}.")
        caption_url = selected["url"]
        for _ in range(4):
            _validate_caption_url(caption_url)
            response = await self._request(client, "GET", caption_url)
            if not response.is_redirect:
                break
            caption_url = urljoin(caption_url, response.headers.get("location", ""))
        else:
            raise MediaCCCError("media.ccc.de caption download exceeded the redirect limit.")
        return MediaCCCTranscript(title=lecture.get("title") or slug,
                                  language=normalize_language(selected.get("language") or ""),
                                  captions=parse_captions(response.text))

    async def fetch_transcript(self, url: str, languages: list[str] | None = None) -> MediaCCCTranscript:
        slug = extract_media_ccc_slug(url)
        if slug is None:
            raise MediaCCCError("Invalid media.ccc.de talk URL; expected https://media.ccc.de/v/<slug>.")
        try:
            async with asyncio.timeout(FETCH_TIMEOUT_SECONDS):
                if self._client is not None:
                    return await self._fetch(self._client, slug, languages)
                async with create_http_client("media_ccc", timeout=15.0, headers={"User-Agent": "OpenMates/1.0"}) as client:
                    return await self._fetch(client, slug, languages)
        except TimeoutError as exc:
            raise MediaCCCError("media.ccc.de caption retrieval timed out after 45s.") from exc
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            if isinstance(exc, MediaCCCError):
                raise
            logger.warning("media.ccc.de caption retrieval failed: %s", type(exc).__name__)
            raise MediaCCCError("media.ccc.de caption retrieval failed; please try again later.") from exc

    async def health_check(self) -> bool:
        """HEAD only, without downloading captions or incurring billing."""
        try:
            async with create_http_client("media_ccc", timeout=10.0) as client:
                response = await client.head("https://media.ccc.de/about.html")
                return response.status_code == 200
        except httpx.HTTPError:
            return False
