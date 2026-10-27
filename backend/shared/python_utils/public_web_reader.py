"""Direct, robots-aware public page reads without credentials or browser execution.

Successful extraction is complete within fixed budgets. Oversized or blocked
pages fail visibly; no partial body is returned and no subresources are fetched.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from html.parser import HTMLParser
import ipaddress
import json
import re
import socket
import ssl
import time
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from weakref import WeakKeyDictionary

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify
from protego import Protego

from backend.shared.python_utils.website_text import MAX_PAGE_BYTES, normalize_page_text, website_read_status

USER_AGENT = "OpenMatesReader/1.0 (+https://openmates.org)"
ROBOTS_AGENT = "OpenMatesReader"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_ROBOTS_BYTES = 512 * 1024
MAX_REDIRECTS = 3
MAX_HTML_NODES = 50_000
MAX_ORIGINS = 256
MIN_REQUEST_INTERVAL = 1.0
_REDIRECTS = {301, 302, 303, 307, 308}
_CHARSET = re.compile(r"charset\s*=\s*[\"']?([A-Za-z0-9._-]+)", re.I)
_PAYWALL = re.compile(r"subscription required|subscribe to (?:continue|read|unlock)|purchase (?:a subscription|access)", re.I)


class PublicWebReadError(ValueError):
    """A safe failure suitable for the public skill response, without page content."""

    def __init__(self, code: str, message: str, http_status: int | None = None):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


@dataclass(frozen=True)
class _Target:
    url: str
    origin: str
    hostname: str


@dataclass
class _Origin:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_request: float = 0.0
    next_request: float = 0.0
    interval: float = MIN_REQUEST_INTERVAL


@dataclass
class _Access:
    slots: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(4))
    origins: dict[str, _Origin] = field(default_factory=dict)
    parsers: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(2))


_ACCESS: WeakKeyDictionary = WeakKeyDictionary()


def _target(url: str) -> _Target:
    try:
        if not isinstance(url, str) or len(url) > 4096 or any(ord(c) <= 32 or ord(c) == 127 for c in url):
            raise ValueError
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)):
            raise ValueError
        hostname = parsed.hostname.encode("idna").decode("ascii").lower()
        host = f"[{hostname}]" if ":" in hostname else hostname
        normalized = urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
        # Use the same URL canonicalization for robots matching and the actual request.
        normalized = str(httpx.URL(normalized))
        return _Target(normalized, f"https://{host}", hostname)
    except (ValueError, UnicodeError, httpx.InvalidURL):
        raise PublicWebReadError("invalid_url", "Only public HTTPS URLs on port 443 without credentials are supported.") from None


async def _public_ip(hostname: str) -> str:
    try:
        answers = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(hostname, 443, type=socket.SOCK_STREAM), 2.0,
        )
        ips = list(dict.fromkeys(row[4][0] for row in answers))
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise PublicWebReadError("unsafe_address", "The website address is not public.")
        return ips[0]
    except PublicWebReadError:
        raise
    except (OSError, ValueError, TimeoutError):
        raise PublicWebReadError("dns_error", "The website address could not be verified.") from None


def _origin(access: _Access, origin: str) -> _Origin:
    if origin not in access.origins:
        now = time.monotonic()
        for key, entry in list(access.origins.items()):
            if not entry.lock.locked() and now - entry.last_request > 60 and entry.next_request <= now:
                del access.origins[key]
        if len(access.origins) >= MAX_ORIGINS:
            raise PublicWebReadError("rate_limited", "The reader is busy. Please try again later.")
        access.origins[origin] = _Origin(interval=MIN_REQUEST_INTERVAL)
    return access.origins[origin]


async def _fetch(target: _Target, access: _Access, *, max_bytes: int) -> tuple[int, httpx.Headers, bytes]:
    entry = _origin(access, target.origin)
    async with entry.lock:
        await asyncio.sleep(max(0, entry.next_request - time.monotonic()))
        entry.last_request = time.monotonic()
        entry.next_request = entry.last_request + entry.interval
        ip = await _public_ip(target.hostname)
        pinned = httpx.URL(target.url).copy_with(host=ip)
        # System trust may include an operator-provided CA. Certificate checking
        # and original-host SNI stay enabled while all environment proxies are off.
        async with httpx.AsyncClient(
            verify=ssl.create_default_context(), trust_env=False,
            follow_redirects=False, timeout=httpx.Timeout(8.0),
        ) as client:
            async with client.stream(
                "GET", pinned,
                headers={"Host": target.origin[8:], "User-Agent": USER_AGENT,
                         "Accept": "text/html,text/plain;q=0.9", "Accept-Encoding": "identity"},
                extensions={"sni_hostname": target.hostname},
            ) as response:
                headers = response.headers
                if response.status_code != 200:
                    return response.status_code, headers, b""
                # Never decode compressed bodies: even one decoder call may allocate
                # more than the page budget before the caller can count the output.
                if headers.get("content-encoding", "identity").strip().lower() not in {"", "identity"}:
                    raise PublicWebReadError("unsupported_encoding", "The website returned an unsupported content encoding.", response.status_code)
                length = headers.get("content-length")
                if length:
                    try:
                        if int(length) < 0 or int(length) > max_bytes:
                            raise PublicWebReadError("too_large", "The website response exceeds the reader size limit.", 200)
                    except ValueError as error:
                        if isinstance(error, PublicWebReadError):
                            raise
                        raise PublicWebReadError("malformed_content", "The website returned invalid response metadata.", 200) from None
                body = bytearray()
                async for chunk in response.aiter_raw(chunk_size=64 * 1024):
                    if len(body) + len(chunk) > max_bytes:
                        raise PublicWebReadError("too_large", "The website response exceeds the reader size limit.", 200)
                    body.extend(chunk)
                return response.status_code, headers, bytes(body)


async def _robots(target: _Target, access: _Access) -> Protego:
    location = _target(target.origin + "/robots.txt")
    for hop in range(MAX_REDIRECTS + 1):
        try:
            status, headers, body = await _fetch(location, access, max_bytes=MAX_ROBOTS_BYTES)
        except PublicWebReadError:
            raise
        if status in {404, 410}:
            return Protego.parse("")
        if status in _REDIRECTS:
            if hop == MAX_REDIRECTS or not headers.get("location"):
                raise PublicWebReadError("robots_unavailable", "The website crawler policy could not be verified.", status)
            location = _target(urljoin(location.url, headers["location"]))
            if location.origin != target.origin:
                raise PublicWebReadError("robots_unavailable", "The website crawler policy redirects to another origin.", status)
            continue
        if status != 200:
            raise PublicWebReadError("robots_unavailable", "The website crawler policy could not be verified.", status)
        mime = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if (mime not in {"", "text/plain"}
                or re.search(rb"<(?:!doctype\s+html|html|head|body|title|script)\b", body, re.I)):
            raise PublicWebReadError("robots_unavailable", "The website crawler policy is not a supported text response.", status)
        try:
            policy = Protego.parse(body.decode("utf-8-sig", errors="strict"))
        except (ValueError, UnicodeError):
            raise PublicWebReadError("robots_unavailable", "The website crawler policy could not be parsed.", status) from None
        delay = policy.crawl_delay(ROBOTS_AGENT) or 0
        rate = policy.request_rate(ROBOTS_AGENT)
        if rate and rate.requests > 0:
            delay = max(delay, rate.seconds / rate.requests)
        entry = _origin(access, target.origin)
        entry.interval = max(MIN_REQUEST_INTERVAL, delay)
        entry.next_request = max(entry.next_request, entry.last_request + entry.interval)
        return policy
    raise AssertionError("Bounded crawler-policy loop exhausted")


class _HTMLBudget(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes = 0

    def handle_starttag(self, tag, attrs):
        self.nodes += 1
        if self.nodes > MAX_HTML_NODES:
            raise PublicWebReadError("too_large", "The website document exceeds the reader complexity limit.", 200)


def _linked_url(base: str, value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = urljoin(base, value.strip())
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme in {"http", "https"} and parsed.hostname and parsed.username is None and parsed.password is None:
            return candidate
    except ValueError:
        pass
    return None


def _declares_nonfree_page(soup: BeautifulSoup) -> bool:
    """Respect publisher access declarations, including JSON-LD graph/part forms.

    This inspects structured page access metadata, not text merely discussing
    subscriptions or paywalls, and never attempts to remove an access overlay.
    """
    def nonfree_parts(value: Any) -> bool:
        pending = [value]
        visited = 0
        while pending:
            node = pending.pop()
            visited += 1
            if visited > MAX_HTML_NODES:
                raise PublicWebReadError("too_large", "The website metadata exceeds the reader complexity limit.", 200)
            if isinstance(node, list):
                pending.extend(node)
            elif isinstance(node, dict):
                free = node.get("isAccessibleForFree")
                if free is False or isinstance(free, str) and free.strip().lower() == "false":
                    return True
                parts = node.get("hasPart")
                if isinstance(parts, (dict, list)):
                    pending.append(parts)
        return False

    for script in soup.find_all("script", type=lambda value: value and value.split(";", 1)[0].strip().lower() == "application/ld+json"):
        try:
            document = json.loads(script.string or script.get_text())
        except (ValueError, RecursionError):
            continue
        pending = [document]
        visited = 0
        while pending:
            node = pending.pop()
            visited += 1
            if visited > MAX_HTML_NODES:
                raise PublicWebReadError("too_large", "The website metadata exceeds the reader complexity limit.", 200)
            if isinstance(node, list):
                pending.extend(node)
            elif isinstance(node, dict):
                kinds = node.get("@type", [])
                kinds = [kinds] if isinstance(kinds, str) else kinds
                if isinstance(kinds, list) and any(
                    isinstance(kind, str) and kind.rsplit("/", 1)[-1].rsplit("#", 1)[-1].endswith(("Article", "Page"))
                    for kind in kinds
                ) and nonfree_parts(node):
                    return True
                pending.extend(value for value in node.values() if isinstance(value, (dict, list)))
    return False


def _extract(url: str, headers: httpx.Headers, body: bytes, only_main_content: bool) -> dict[str, Any]:
    content_type = headers.get("content-type", "").lower()
    mime = content_type.split(";", 1)[0].strip()
    if mime not in {"text/html", "text/plain"}:
        raise PublicWebReadError("unsupported_content_type", "Only HTML and plain-text pages are supported.", 200)
    charset = _CHARSET.search(content_type)
    if not charset and mime == "text/html":
        charset = _CHARSET.search(body[:8192].decode("ascii", errors="ignore"))
    try:
        text = body.decode(charset.group(1) if charset else "utf-8", errors="strict")
    except (LookupError, UnicodeError):
        raise PublicWebReadError("malformed_content", "The website text encoding could not be read.", 200) from None
    if "\x00" in text:
        raise PublicWebReadError("malformed_content", "The website did not return a supported text document.", 200)
    page: dict[str, Any] = {"url": url, "source_url": url, "http_status": 200, "title": "",
                            "markdown": "", "language": None, "favicon": None,
                            "og_image": None, "og_sitename": None, "warnings": []}
    if mime == "text/plain":
        page["markdown"] = normalize_page_text(text)
    else:
        _HTMLBudget().feed(text)
        soup = BeautifulSoup(text, "html.parser")
        if _declares_nonfree_page(soup):
            raise PublicWebReadError("blocked", "The publisher marks this page or part of it as requiring paid access.", 200)
        page["title"] = soup.title.get_text(" ", strip=True) if soup.title else ""
        page["language"] = soup.html.get("lang") if soup.html else None
        base = url
        base_tag = soup.find("base", href=True)
        if base_tag:
            base = _linked_url(url, base_tag.get("href")) or url
        for key, prop in [("og_image", "og:image"), ("og_sitename", "og:site_name")]:
            meta = soup.find("meta", attrs={"property": prop})
            value = meta.get("content") if meta else None
            page[key] = _linked_url(base, value) if key == "og_image" else value
        icon = soup.find("link", rel=lambda value: value and "icon" in value)
        page["favicon"] = _linked_url(base, icon.get("href")) if icon else None
        for element in list(soup.find_all(["script", "style", "template", "iframe", "object", "embed"])):
            element.decompose()
        for element in list(soup.find_all(attrs={"hidden": True})):
            element.decompose()
        for element in list(soup.find_all(attrs={"aria-hidden": "true"})):
            element.decompose()
        for element in list(soup.find_all(style=True)):
            if element.attrs and re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", str(element.get("style")), re.I):
                element.decompose()
        visible = soup.get_text(" ", strip=True)
        if len(visible) < 4000 and _PAYWALL.search(visible):
            raise PublicWebReadError("blocked", "The website requires access that this reader does not have.", 200)
        if website_read_status({"title": page["title"], "markdown": visible}) == "blocked":
            raise PublicWebReadError("blocked", "The website blocked this reader or requires authentication.", 200)
        selected = soup.find("main") or soup.find("article") or soup.body or soup
        if not only_main_content:
            selected = soup.body or soup
        elif selected.name not in {"main", "article"}:
            for element in list(selected.find_all(["nav", "footer", "header", "aside"])):
                element.decompose()
        for link in selected.find_all("a", href=True):
            destination = _linked_url(base, link.get("href"))
            if destination:
                link["href"] = destination
            else:
                del link["href"]
        for image in list(selected.find_all("img")):
            image.replace_with(str(image.get("alt") or ""))
        page["markdown"] = normalize_page_text(markdownify(str(selected), heading_style="ATX", wrap=False))
    if sum(len(value.encode("utf-8")) for value in page.values() if isinstance(value, str)) > MAX_PAGE_BYTES:
        raise PublicWebReadError("too_large", "The extracted page exceeds the reader text limit.", 200)
    status = website_read_status(page)
    if status != "usable":
        raise PublicWebReadError(status, "The website did not return readable public page text.", 200)
    page["read_status"] = status
    return page


async def _parse_page(access: _Access, url: str, headers: httpx.Headers, body: bytes, only_main_content: bool) -> dict[str, Any]:
    # A timed-out caller cannot stop a Python worker thread. Retain its parser
    # slot until it finishes so cancellation cannot queue unbounded CPU/memory.
    await access.parsers.acquire()
    task = asyncio.create_task(asyncio.to_thread(_extract, url, headers, body, only_main_content))

    def finished(done):
        access.parsers.release()
        if not done.cancelled():
            done.exception()  # Consume a late error after the caller timed out.

    task.add_done_callback(finished)
    return await asyncio.shield(task)


async def _read(target: _Target, access: _Access, only_main_content: bool) -> dict[str, Any]:
    policies: dict[str, Protego] = {}
    for hop in range(MAX_REDIRECTS + 1):
        if target.origin not in policies:
            policies[target.origin] = await _robots(target, access)
        if not policies[target.origin].can_fetch(target.url, ROBOTS_AGENT):
            raise PublicWebReadError("robots_denied", "The website does not permit this reader to access this page.")
        status, headers, body = await _fetch(target, access, max_bytes=MAX_INPUT_BYTES)
        if status in _REDIRECTS:
            if hop == MAX_REDIRECTS or not headers.get("location"):
                raise PublicWebReadError("redirect_limit", "The website exceeded the reader redirect limit.", status)
            target = _target(urljoin(target.url, headers["location"]))
            continue
        if status != 200:
            raise PublicWebReadError("http_error", "The website did not permit a successful page read.", status)
        return await _parse_page(access, target.url, headers, body, only_main_content)
    raise AssertionError("Bounded page redirect loop exhausted")


async def read_public_web_page(url: str, *, only_main_content: bool = True, timeout_ms: int = 20_000) -> dict[str, Any]:
    """Read a complete public page within one bounded, robots-aware operation."""
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or not 1000 <= timeout_ms <= 30_000:
        raise PublicWebReadError("invalid_timeout", "The reader timeout must be between 1000 and 30000 milliseconds.")
    target = _target(url)
    loop = asyncio.get_running_loop()
    access = _ACCESS.setdefault(loop, _Access())
    try:
        async with asyncio.timeout(timeout_ms / 1000), access.slots:
            return await _read(target, access, only_main_content)
    except PublicWebReadError:
        raise
    except TimeoutError:
        raise PublicWebReadError("timeout", "The website read exceeded its time limit.") from None
    except (httpx.HTTPError, ssl.SSLError):
        raise PublicWebReadError("network_error", "The website could not be reached securely.") from None
