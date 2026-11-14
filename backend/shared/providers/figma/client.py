# backend/shared/providers/figma/client.py
#
# Pure async Figma REST API wrapper. It accepts short-lived access tokens from
# the token broker; it never refreshes tokens and never retries (429 included).
# Every failure is raised as a classified FigmaProviderError.
#
# API reference: https://developers.figma.com/docs/rest-api/
# Spec: specifications/features/app-skills/design-figma/specification.yml

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import httpx

from .errors import FigmaProviderError, classify_status_error

logger = logging.getLogger(__name__)

FIGMA_API_BASE_URL = "https://api.figma.com"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_NODE_IDS = 10
IMAGE_FORMATS = frozenset({"png", "jpg", "svg", "pdf"})
_FIGMA_HOSTS = frozenset({"figma.com", "www.figma.com"})
_URL_KINDS = frozenset({"design", "file", "proto", "board"})
_KEY_RE = re.compile(r"^[A-Za-z0-9]{10,40}$")
_NODE_RE = re.compile(r"^\d+[:\-]\d+(?:[;:\-]\d+)*$")


class FigmaInputError(ValueError):
    """The Figma URL, file key or node ids are not usable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def normalize_node_id(value: str) -> str:
    node = value.strip().replace("%3A", ":").replace("%3a", ":")
    if not _NODE_RE.match(node):
        raise FigmaInputError("invalid_node_id", "Node ids look like 12:34 or 12-34.")
    return node.replace("-", ":")


def parse_figma_reference(
    figma_url: str | None = None, file_key: str | None = None,
    node_ids: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Return (file_key, normalized colon node ids) from a Figma URL or key."""

    nodes = list(node_ids or [])
    key = (file_key or "").strip()
    if figma_url:
        parsed = urlparse(figma_url.strip())
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or host not in _FIGMA_HOSTS:
            raise FigmaInputError("invalid_figma_url", "Only figma.com file URLs are supported.")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2 or parts[0] not in _URL_KINDS:
            raise FigmaInputError("invalid_figma_url", "The URL is not a Figma file URL.")
        key = parts[1]
        if len(parts) >= 4 and parts[2] == "branch":
            key = parts[3]
        url_node = parse_qs(parsed.query).get("node-id")
        if url_node and not nodes:
            nodes = [url_node[0]]
    if not _KEY_RE.match(key):
        raise FigmaInputError("invalid_file_key", "A Figma file URL or file key is required.")
    if len(nodes) > MAX_NODE_IDS:
        raise FigmaInputError("too_many_nodes", f"At most {MAX_NODE_IDS} node ids per request.")
    return key, [normalize_node_id(node) for node in nodes]


class FigmaClient:
    """Minimal Figma REST client for read-only design access."""

    def __init__(
        self, access_token: str, transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self.access_token = access_token
        self.timeout = timeout
        self._transport = transport

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                response = await client.get(f"{FIGMA_API_BASE_URL}{path}", params=params, headers=headers)
        except httpx.TransportError as exc:
            raise FigmaProviderError("figma_unavailable") from exc
        if response.is_error:
            error = classify_status_error(response)
            logger.info("Figma GET %s failed: %s", path.split("/")[2] if path.count("/") > 1 else path, error.code)
            raise error
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def get_file(self, file_key: str, depth: int = 2) -> dict[str, Any]:
        return await self._get(f"/v1/files/{quote(file_key, safe='')}", {"depth": depth})

    async def get_nodes(self, file_key: str, node_ids: list[str], depth: int = 2) -> dict[str, Any]:
        return await self._get(
            f"/v1/files/{quote(file_key, safe='')}/nodes", {"ids": ",".join(node_ids), "depth": depth},
        )

    async def get_images(
        self, file_key: str, node_ids: list[str], fmt: str = "png", scale: float = 1.0,
    ) -> dict[str, Any]:
        if fmt not in IMAGE_FORMATS:
            raise FigmaInputError("invalid_image_format", "Image format must be png, jpg, svg or pdf.")
        return await self._get(
            f"/v1/images/{quote(file_key, safe='')}",
            {"ids": ",".join(node_ids), "format": fmt, "scale": scale},
        )

    async def get_local_variables(self, file_key: str) -> dict[str, Any]:
        return await self._get(f"/v1/files/{quote(file_key, safe='')}/variables/local")
