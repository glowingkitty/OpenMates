# backend/tests/test_hi3d_provider.py
#
# Contract tests for the pure Hi3D API wrapper.
# Network calls are mocked so normal test runs never consume provider credits.
# The tests pin authentication, input ordering, task-state normalization,
# download validation, and secret-safe errors before provider implementation.

from __future__ import annotations

import asyncio
import json
import logging
import struct
from io import BytesIO

import httpx
import pytest
from PIL import Image

from backend.shared.providers.hi3d.client import Hi3DClient, Hi3DProviderError
from backend.shared.providers.hi3d.models import Hi3DTaskState, Hi3DView


ACCESS_KEY = "test-access-key"
SECRET_KEY = "test-secret-key"


def _glb(document: dict[str, object] | None = None, *, version: int = 2) -> bytes:
    json_bytes = json.dumps(document or {"asset": {"version": "2.0"}}).encode()
    json_bytes += b" " * (-len(json_bytes) % 4)
    total_length = 12 + 8 + len(json_bytes)
    return b"glTF" + struct.pack("<II", version, total_length) + struct.pack("<I4s", len(json_bytes), b"JSON") + json_bytes


def _glb_with_duplicate_json() -> bytes:
    base = _glb()
    json_chunk = base[12:]
    payload = base + json_chunk
    return payload[:8] + len(payload).to_bytes(4, "little") + payload[12:]


VALID_GLB = _glb()
DOWNLOAD_URL = "https://hitem3dstatic.zaohaowu.net/model.glb"
COVER_URL = "https://hitem3dstatic.zaohaowu.net/cover.webp"


def _client(handler: httpx.MockTransport) -> tuple[Hi3DClient, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(transport=handler)
    return Hi3DClient(ACCESS_KEY, SECRET_KEY, http_client=http_client), http_client


@pytest.mark.asyncio
async def test_authenticates_and_queries_balance_without_secret_logs(caplog: pytest.LogCaptureFixture) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/auth/token"):
            assert request.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"code": 200, "data": {"accessToken": "bearer-token"}, "msg": "success"})
        assert request.headers["authorization"] == "Bearer bearer-token"
        return httpx.Response(200, json={"code": 200, "data": {"totalBalance": 200}, "msg": "success"})

    client, http_client = _client(httpx.MockTransport(handler))
    caplog.set_level(logging.DEBUG)
    try:
        assert await client.get_balance() == 200
    finally:
        await http_client.aclose()

    assert [request.url.path for request in requests] == [
        "/open-api/v1/auth/token",
        "/open-api/v1/balance",
    ]
    assert ACCESS_KEY not in caplog.text
    assert SECRET_KEY not in caplog.text
    assert "bearer-token" not in caplog.text


@pytest.mark.asyncio
async def test_submits_ordered_multi_view_v21_fast_pbr_glb() -> None:
    submitted_body = b""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal submitted_body
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"code": 200, "data": {"accessToken": "token"}, "msg": "success"})
        submitted_body = await request.aread()
        return httpx.Response(200, json={"code": 200, "data": {"task_id": "task-1"}, "msg": "success"})

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        task_id = await client.submit_task(
            images=[
                (Hi3DView.FRONT, "front.png", b"front", "image/png"),
                (Hi3DView.BACK, "back.png", b"back", "image/png"),
                (Hi3DView.LEFT, "left.png", b"left", "image/png"),
                (Hi3DView.RIGHT, "right.png", b"right", "image/png"),
            ]
        )
    finally:
        await http_client.aclose()

    assert task_id == "task-1"
    assert b'hitem3dv2.1' in submitted_body
    assert b'1536fast' in submitted_body
    assert b'name="pbr"' in submitted_body
    assert submitted_body.index(b"front.png") < submitted_body.index(b"back.png")
    assert submitted_body.index(b"back.png") < submitted_body.index(b"left.png")
    assert submitted_body.index(b"left.png") < submitted_body.index(b"right.png")


@pytest.mark.asyncio
async def test_wait_for_task_normalizes_states_and_refunded_failure() -> None:
    states = iter(
        [
            {"code": 200, "data": {"task_id": "task-1", "state": "queueing"}, "msg": "success"},
            {"code": 200, "data": {"task_id": "task-1", "state": "processing"}, "msg": "success"},
            {"code": 50010001, "data": {}, "msg": "generate failed"},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"code": 200, "data": {"accessToken": "token"}, "msg": "success"})
        return httpx.Response(200, json=next(states))

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(Hi3DProviderError) as excinfo:
            await client.wait_for_task("task-1", poll_interval_seconds=0, sleep=asyncio.sleep)
    finally:
        await http_client.aclose()

    assert excinfo.value.refunded is True
    assert excinfo.value.state is Hi3DTaskState.FAILED


@pytest.mark.asyncio
async def test_download_glb_rejects_wrong_magic_and_oversize() -> None:
    payloads = iter([b"not-glb", VALID_GLB + b"too-large"])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=next(payloads), headers={"content-type": "model/gltf-binary"})

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(Hi3DProviderError, match="GLB"):
            await client.download_glb(DOWNLOAD_URL, max_bytes=100)
        with pytest.raises(Hi3DProviderError, match="size"):
            await client.download_glb(DOWNLOAD_URL, max_bytes=len(VALID_GLB))
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "content_type", "message"),
    [
        (_glb(version=1), "model/gltf-binary", "version"),
        (_glb({"asset": {"version": "2.0"}, "buffers": [{"uri": "https://example.test/x.bin"}]}), "model/gltf-binary", "external"),
        (b"<html>not a glb</html>", "text/html", "GLB"),
    ],
)
async def test_download_glb_rejects_unsafe_container_variants(
    payload: bytes,
    content_type: str,
    message: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, headers={"content-type": content_type})

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(Hi3DProviderError, match=message):
            await client.download_glb(DOWNLOAD_URL)
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_download_glb_accepts_provider_misreported_content_type() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=VALID_GLB, headers={"content-type": "text/plain"})

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        assert await client.download_glb(DOWNLOAD_URL) == VALID_GLB
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_download_glb_rejects_unapproved_host() -> None:
    client, http_client = _client(httpx.MockTransport(lambda _request: httpx.Response(200, content=VALID_GLB)))
    try:
        with pytest.raises(Hi3DProviderError, match="host"):
            await client.download_glb("http://127.0.0.1/internal.glb")
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_download_cover_validates_provider_image_and_returns_mime_type() -> None:
    image = Image.new("RGB", (4, 4), color=(234, 118, 0))
    output = BytesIO()
    image.save(output, format="WEBP")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=output.getvalue(), headers={"content-type": "image/webp"})

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        content, mime_type = await client.download_cover(COVER_URL)
    finally:
        await http_client.aclose()

    assert content == output.getvalue()
    assert mime_type == "image/webp"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "content_type", "message"),
    [
        (b"not-an-image", "image/webp", "image"),
        (b"<html>not an image</html>", "text/html", "image"),
    ],
)
async def test_download_cover_rejects_invalid_image_content(
    payload: bytes,
    content_type: str,
    message: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, headers={"content-type": content_type})

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(Hi3DProviderError, match=message):
            await client.download_cover(COVER_URL)
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_download_cover_accepts_provider_misreported_content_type() -> None:
    image = Image.new("RGB", (4, 4), color=(32, 64, 128))
    output = BytesIO()
    image.save(output, format="WEBP")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=output.getvalue(), headers={"content-type": "text/plain"})

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        content, mime_type = await client.download_cover(COVER_URL)
    finally:
        await http_client.aclose()

    assert content == output.getvalue()
    assert mime_type == "image/webp"


@pytest.mark.asyncio
async def test_download_glb_does_not_follow_redirect_to_unapproved_host() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/internal.glb"})

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(Hi3DProviderError, match="host"):
            await client.download_glb(DOWNLOAD_URL)
    finally:
        await http_client.aclose()
    assert requested == [DOWNLOAD_URL]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [_glb_with_duplicate_json(), _glb({"asset": []})])
async def test_download_glb_rejects_invalid_chunk_or_asset_shape(payload: bytes) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, headers={"content-type": "model/gltf-binary"})

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        with pytest.raises(Hi3DProviderError):
            await client.download_glb(DOWNLOAD_URL)
    finally:
        await http_client.aclose()
