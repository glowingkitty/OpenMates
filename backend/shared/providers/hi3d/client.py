"""Async client for Hi3D image and multi-view 3D generation.

Credentials and bearer tokens are held in memory only. Provider failures are
normalized into typed errors and never include request headers or secrets.
Official contract: https://docs.hi3d.ai/en/api/api-reference/list
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
from collections.abc import Awaitable, Callable
from io import BytesIO
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image, UnidentifiedImageError

from .models import Hi3DTaskResult, Hi3DTaskState, Hi3DView


logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.hitem3d.ai/open-api/v1"
DEFAULT_MAX_DOWNLOAD_BYTES = 150 * 1024 * 1024
DEFAULT_MAX_COVER_BYTES = 10 * 1024 * 1024
DEFAULT_POLL_INTERVAL_SECONDS = 10.0
DEFAULT_MAX_POLLS = 120
_VIEW_ORDER = (Hi3DView.FRONT, Hi3DView.BACK, Hi3DView.LEFT, Hi3DView.RIGHT)
_ALLOWED_DOWNLOAD_HOST_SUFFIXES = (".zaohaowu.net", ".hitem3d.ai", ".hi3d.ai")
_TASK_ID_RESPONSE_KEYS = ("task_id", "taskId")
_PIL_TO_MIME_TYPE = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


class Hi3DProviderError(RuntimeError):
    """Safe normalized provider error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        state: Hi3DTaskState | None = None,
        refunded: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.state = state
        self.refunded = refunded


class Hi3DClient:
    """Pure injected-HTTP Hi3D API client."""

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not access_key or not secret_key:
            raise ValueError("Hi3D credentials are required")
        self._access_key = access_key
        self._secret_key = secret_key
        self._http_client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=30.0),
            follow_redirects=True,
        )
        self._owns_http_client = http_client is None
        self._access_token: str | None = None

    async def __aenter__(self) -> "Hi3DClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def authenticate(self) -> str:
        """Obtain and cache a bearer token."""
        if self._access_token:
            return self._access_token
        try:
            response = await self._http_client.post(
                f"{API_BASE_URL}/auth/token",
                auth=httpx.BasicAuth(self._access_key, self._secret_key),
                json={},
            )
            response.raise_for_status()
            data = self._require_success(response.json(), "authentication")
            token = str(data.get("accessToken") or "")
            if not token:
                raise Hi3DProviderError("Hi3D authentication returned no access token")
            self._access_token = token
            return token
        except Hi3DProviderError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise Hi3DProviderError("Hi3D authentication failed") from exc

    async def get_balance(self) -> float:
        token = await self.authenticate()
        response = await self._request("GET", "/balance", token=token)
        data = self._require_success(response, "balance query")
        try:
            return float(data.get("totalBalance") or 0)
        except (TypeError, ValueError) as exc:
            raise Hi3DProviderError("Hi3D returned an invalid balance") from exc

    async def submit_task(
        self,
        *,
        images: list[tuple[Hi3DView, str, bytes, str]],
    ) -> str:
        """Submit one image or two-to-four ordered multi-view images."""
        if not 1 <= len(images) <= 4:
            raise ValueError("Hi3D requires one to four images")
        positions = [item[0] for item in images]
        if len(set(positions)) != len(positions):
            raise ValueError("Hi3D image views must be unique")
        ordered = sorted(images, key=lambda item: _VIEW_ORDER.index(item[0]))
        token = await self.authenticate()
        files: list[tuple[str, tuple[str, bytes, str]]]
        data = {
            "request_type": "3",
            "model": "hitem3dv2.1",
            "resolution": "1536fast",
            "pbr": "1",
            "face": "500000",
            "format": "2",
        }
        if len(ordered) == 1:
            _, filename, content, mime_type = ordered[0]
            files = [("images", (filename, content, mime_type))]
        else:
            files = [
                ("multi_images", (filename, content, mime_type))
                for _, filename, content, mime_type in ordered
            ]
            supplied = {view for view, *_ in ordered}
            data["multi_images_bit"] = "".join("1" if view in supplied else "0" for view in _VIEW_ORDER)
        response = await self._request("POST", "/submit-task", token=token, files=files, data=data)
        response_data = self._require_success(response, "task submission")
        task_id = str(next((response_data.get(key) for key in _TASK_ID_RESPONSE_KEYS if response_data.get(key)), ""))
        if not task_id:
            raise Hi3DProviderError("Hi3D task submission returned no task ID")
        return task_id

    async def wait_for_task(
        self,
        task_id: str,
        *,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_polls: int = DEFAULT_MAX_POLLS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> Hi3DTaskResult:
        token = await self.authenticate()
        for _ in range(max_polls):
            payload = await self._request(
                "GET",
                "/query-task",
                token=token,
                params={"task_id": task_id},
                allow_provider_error=True,
            )
            code = self._code(payload)
            if code == 50010001:
                raise Hi3DProviderError(
                    "Hi3D generation failed",
                    status_code=code,
                    state=Hi3DTaskState.FAILED,
                    refunded=True,
                )
            data = self._require_success(payload, "task query")
            raw_state = str(data.get("state") or "")
            try:
                state = Hi3DTaskState(raw_state)
            except ValueError as exc:
                raise Hi3DProviderError("Hi3D returned an unknown task state") from exc
            if state is Hi3DTaskState.SUCCESS:
                model_url = str(data.get("url") or "")
                if not model_url:
                    raise Hi3DProviderError("Hi3D successful task returned no model URL")
                return Hi3DTaskResult(
                    task_id=task_id,
                    state=state,
                    model_url=model_url,
                    cover_url=str(data.get("cover_url") or "") or None,
                    content_id=str(data.get("id") or "") or None,
                )
            if state is Hi3DTaskState.FAILED:
                raise Hi3DProviderError("Hi3D generation failed", state=state, refunded=True)
            await sleep(poll_interval_seconds)
        raise Hi3DProviderError("Hi3D generation timed out")

    async def download_glb(
        self,
        url: str,
        *,
        max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    ) -> bytes:
        """Download a bounded provider GLB and validate its binary header."""
        current_url = url
        content = bytearray()
        try:
            for _ in range(4):
                self._validate_download_url(current_url)
                async with self._http_client.stream(
                    "GET",
                    current_url,
                    follow_redirects=False,
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise Hi3DProviderError("Hi3D GLB redirect has no location")
                        current_url = urljoin(current_url, location)
                        self._validate_download_url(current_url)
                        continue
                    response.raise_for_status()
                    self._validate_download_url(str(response.url))
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > max_bytes:
                            raise Hi3DProviderError("Hi3D GLB exceeds the configured size limit")
                    break
            else:
                raise Hi3DProviderError("Hi3D GLB exceeded the redirect limit")
        except Hi3DProviderError:
            raise
        except httpx.HTTPError as exc:
            raise Hi3DProviderError("Hi3D GLB download failed") from exc
        payload = bytes(content)
        self._validate_glb(payload)
        return payload

    async def download_cover(
        self,
        url: str,
        *,
        max_bytes: int = DEFAULT_MAX_COVER_BYTES,
    ) -> tuple[bytes, str]:
        """Download and validate the temporary provider cover before it expires."""
        current_url = url
        content = bytearray()
        try:
            for _ in range(4):
                self._validate_download_url(current_url)
                async with self._http_client.stream(
                    "GET",
                    current_url,
                    follow_redirects=False,
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise Hi3DProviderError("Hi3D cover redirect has no location")
                        current_url = urljoin(current_url, location)
                        self._validate_download_url(current_url)
                        continue
                    response.raise_for_status()
                    self._validate_download_url(str(response.url))
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > max_bytes:
                            raise Hi3DProviderError("Hi3D cover exceeds the configured size limit")
                    break
            else:
                raise Hi3DProviderError("Hi3D cover exceeded the redirect limit")
        except Hi3DProviderError:
            raise
        except httpx.HTTPError as exc:
            raise Hi3DProviderError("Hi3D cover download failed") from exc

        payload = bytes(content)
        try:
            with Image.open(BytesIO(payload)) as image:
                image.verify()
                mime_type = _PIL_TO_MIME_TYPE.get(image.format or "")
        except (UnidentifiedImageError, OSError) as exc:
            raise Hi3DProviderError("Hi3D cover is not a valid image") from exc
        if not mime_type:
            raise Hi3DProviderError("Hi3D cover image format is not supported")
        return payload, mime_type

    @staticmethod
    def _validate_download_url(url: str) -> None:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not any(
            hostname.endswith(suffix) for suffix in _ALLOWED_DOWNLOAD_HOST_SUFFIXES
        ):
            raise Hi3DProviderError("Hi3D download host is not approved")
        if parsed.username or parsed.password:
            raise Hi3DProviderError("Hi3D download host is not approved")

    @staticmethod
    def _validate_glb(payload: bytes) -> None:
        if len(payload) < 20 or payload[:4] != b"glTF":
            raise Hi3DProviderError("Hi3D result is not a valid GLB")
        version, declared_length = struct.unpack_from("<II", payload, 4)
        if version != 2:
            raise Hi3DProviderError("Hi3D GLB version must be 2")
        if declared_length != len(payload):
            raise Hi3DProviderError("Hi3D GLB has an invalid declared size")
        offset = 12
        chunks: list[tuple[bytes, bytes]] = []
        while offset < len(payload):
            if offset + 8 > len(payload):
                raise Hi3DProviderError("Hi3D GLB has a truncated chunk header")
            chunk_length, chunk_type = struct.unpack_from("<I4s", payload, offset)
            offset += 8
            if chunk_length % 4 or offset + chunk_length > len(payload):
                raise Hi3DProviderError("Hi3D GLB has an invalid chunk length")
            chunks.append((chunk_type, payload[offset : offset + chunk_length]))
            offset += chunk_length
        if (
            not chunks
            or len(chunks) > 2
            or chunks[0][0] != b"JSON"
            or (len(chunks) == 2 and chunks[1][0] != b"BIN\x00")
        ):
            raise Hi3DProviderError("Hi3D GLB has invalid chunk framing")
        try:
            document = json.loads(chunks[0][1].decode("utf-8").rstrip(" \t\r\n\x00"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Hi3DProviderError("Hi3D GLB contains invalid JSON") from exc
        asset = document.get("asset") if isinstance(document, dict) else None
        if not isinstance(asset, dict) or str(asset.get("version")) != "2.0":
            raise Hi3DProviderError("Hi3D GLB JSON requires glTF asset version 2.0")
        resources = [*(document.get("buffers") or []), *(document.get("images") or [])]
        if any(isinstance(resource, dict) and resource.get("uri") for resource in resources):
            raise Hi3DProviderError("Hi3D GLB must not reference external resources")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        allow_provider_error: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            response = await self._http_client.request(
                method,
                f"{API_BASE_URL}{path}",
                headers={"Authorization": f"Bearer {token}"},
                **kwargs,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise Hi3DProviderError("Hi3D returned an invalid response")
            if not allow_provider_error and self._code(payload) != 200:
                raise Hi3DProviderError(
                    f"Hi3D {path.removeprefix('/')} failed",
                    status_code=self._code(payload),
                )
            return payload
        except Hi3DProviderError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Hi3D request failed for %s", path)
            raise Hi3DProviderError(f"Hi3D {path.removeprefix('/')} request failed") from exc

    @staticmethod
    def _code(payload: dict[str, Any]) -> int:
        try:
            return int(payload.get("code"))
        except (TypeError, ValueError):
            return -1

    @classmethod
    def _require_success(cls, payload: dict[str, Any], operation: str) -> dict[str, Any]:
        code = cls._code(payload)
        data = payload.get("data")
        if code != 200 or not isinstance(data, dict):
            raise Hi3DProviderError(f"Hi3D {operation} failed", status_code=code)
        return data
