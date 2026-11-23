"""Inbox Kitten client for the AI test users' throwaway signup mailbox.

Dev test tooling (runs in the api container). The mailbox is public by
address: `GET /api/v1/mail/list?recipient=<local part>` returns the stored
messages (each with `storage.region`/`storage.key` or a `storage.url`), and
`GET /api/v1/mail/getKey?region=..&key=..` returns the message JSON with
`subject` (since November 2026 without the bodies), and
`GET /api/v1/mail/getHtml?region=..&key=..` returns the HTML body. The code is
read from the subject (signup: "Your code: …") or else from the HTML body
(sensitive-action codes such as account deletion use a generic subject), and
handed straight to the driver; neither the address nor the code is ever
logged in full.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

BASE_URL = "https://inboxkitten.com/api/v1/mail"
CODE_PATTERN = re.compile(r"(?<![\w.])(\d{6})(?![\w.])")
TAG_PATTERN = re.compile(r"<[^>]+>")
HIDDEN_PATTERN = re.compile(r"<(style|script|head)\b.*?</\1\s*>", re.S | re.I)
REGION_PATTERN = re.compile(r"storage-([a-z0-9-]+)\.api\.mailgun\.net")


class InboxError(RuntimeError):
    """The mailbox could not be read or no code arrived in time."""


def mask_address(address: str) -> str:
    local, _, domain = address.partition("@")
    return f"{local[:3]}***@{domain}" if domain else f"{local[:3]}***"


def storage_ref(item: dict[str, Any]) -> tuple[str, str] | None:
    storage = item.get("storage") or {}
    key = storage.get("key")
    region = storage.get("region")
    if not region and storage.get("url"):
        match = REGION_PATTERN.search(str(storage["url"]))
        region = match.group(1) if match else None
        if not key:
            key = str(storage["url"]).rstrip("/").rsplit("/", 1)[-1]
    return (str(region), str(key)) if region and key else None


def item_timestamp(item: dict[str, Any]) -> float | None:
    """Epoch seconds of a list item (Mailgun `timestamp`, or a Date header)."""
    value = item.get("timestamp")
    if isinstance(value, (int, float)):
        return float(value)
    headers = (item.get("message") or {}).get("headers") or {}
    date = headers.get("date") or item.get("Date")
    if date:
        try:
            return parsedate_to_datetime(str(date)).timestamp()
        except (TypeError, ValueError):
            return None
    return None


def extract_code(message: dict[str, Any]) -> str | None:
    """First standalone six-digit number in subject, plain body, then HTML body."""
    html = TAG_PATTERN.sub(" ", HIDDEN_PATTERN.sub(" ", str(message.get("body-html") or "")))
    for field in (str(message.get("subject") or ""), str(message.get("body-plain") or ""), html):
        match = CODE_PATTERN.search(field)
        if match:
            return match.group(1)
    return None


class InboxKitten:
    def __init__(self, address: str, *, poll_seconds: float = 3.0) -> None:
        self.address = address
        self.local = address.split("@", 1)[0]
        self.poll_seconds = poll_seconds
        self.seen: set[str] = set()

    async def wait_for_code(self, requested_at: float, timeout: float = 120, purpose: str = "signup") -> str:
        """The code of the first new message that arrived after `requested_at` (epoch seconds)."""
        deadline = time.monotonic() + timeout
        async with httpx.AsyncClient(timeout=20) as client:
            while time.monotonic() < deadline:
                try:
                    code = await self._poll(client, requested_at)
                except httpx.HTTPError:
                    code = None  # transient mailbox hiccup; the deadline bounds the retries
                if code:
                    return code
                await asyncio.sleep(self.poll_seconds)
        raise InboxError(f"No code arrived for {mask_address(self.address)} within {int(timeout)} s.")

    async def _poll(self, client: httpx.AsyncClient, requested_at: float) -> str | None:
        response = await client.get(f"{BASE_URL}/list", params={"recipient": self.local})
        response.raise_for_status()
        items = response.json()
        if not isinstance(items, list):
            return None
        for item in sorted(items, key=lambda i: item_timestamp(i) or 0, reverse=True):
            ref = storage_ref(item) if isinstance(item, dict) else None
            if ref is None or ref[1] in self.seen:
                continue
            stamp = item_timestamp(item)
            if stamp is not None and stamp < requested_at - 5:
                self.seen.add(ref[1])
                continue
            message = await client.get(f"{BASE_URL}/getKey", params={"region": ref[0], "key": ref[1]})
            message.raise_for_status()
            self.seen.add(ref[1])
            body = message.json()
            code = extract_code(body)
            if not code and not body.get("body-html"):
                html = await client.get(f"{BASE_URL}/getHtml", params={"region": ref[0], "key": ref[1]})
                html.raise_for_status()
                code = extract_code({"body-html": html.text})
            if code:
                return code
        return None


class DevCacheInbox:
    """Dev-only code source: dev limits signup to approved test domains, whose mail the harness
    cannot read, so the signup code is read from the dev cache (`email_verification:<email>`), as
    scripts/dev_test_account.py does. The web deletion code is session-bound and stored only as a
    digest, so it is not readable: the orchestrator deletes such accounts with the dev admin script.
    Refuses outside SERVER_ENVIRONMENT=development.
    """

    reads_deletion_code = False

    def __init__(self, address: str, *, poll_seconds: float = 2.0) -> None:
        if os.getenv("SERVER_ENVIRONMENT") != "development":
            raise InboxError("The dev cache inbox runs on the development server only.")
        self.address = address.strip().lower()
        self.poll_seconds = poll_seconds
        self._services: Any = None

    async def _cache(self) -> Any:
        if self._services is None:
            if "/app" not in sys.path:
                sys.path.insert(0, "/app")
            from backend.core.api.app.services.cache import CacheService

            cache = CacheService()
            await cache.client
            self._services = cache
        return self._services

    async def wait_for_code(self, requested_at: float, timeout: float = 120, purpose: str = "signup") -> str:
        if purpose != "signup":
            raise InboxError(f"The dev cache holds no readable {purpose} code.")
        cache = await self._cache()
        key = f"email_verification:{self.address}"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = await cache.get(key)
            match = CODE_PATTERN.search(str(value or ""))
            if match:
                return match.group(1)
            await asyncio.sleep(self.poll_seconds)
        raise InboxError(f"No {purpose} code for {mask_address(self.address)} within {int(timeout)} s.")


def make_inbox(signup: dict[str, Any]) -> InboxKitten | DevCacheInbox:
    """The job's code source: `inbox` is "inboxkitten" (default) or "dev_cache"."""
    kind = signup.get("inbox") or "inboxkitten"
    if kind == "dev_cache":
        return DevCacheInbox(signup["email"])
    if kind != "inboxkitten":
        raise InboxError(f"Unknown inbox {kind!r}.")
    return InboxKitten(signup["email"])
