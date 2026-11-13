"""Gemini Omni video wrapper: request bodies, parsing, error mapping, validation."""

# contract-test-file: infrastructure
import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile

import httpx
import pytest

from backend.shared.providers.google import omni_video as ov
from backend.shared.providers.google.omni_video import (
    OmniImage,
    OmniInvalidArgumentError,
    OmniRegionError,
    OmniSafetyError,
    OmniTimeoutError,
    OmniUnavailableError,
    build_request_body,
    generate_omni_video,
)

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")

IMG = b"\xff\xd8jpeg-bytes"


def _kwargs(**over):
    base = dict(duration_seconds=4, aspect_ratio="16:9", resolution="720p",
                first_frame=None, last_frame=None, reference_images=(),
                source_video=None, delivery="inline")
    base.update(over)
    return base


@pytest.fixture(scope="module")
def mp4() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "t.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "color=red:s=64x48:r=10:d=2", "-pix_fmt", "yuv420p", out], check=True)
        with open(out, "rb") as f:
            return f.read()


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-secret-key")


REAL_CLIENT = httpx.AsyncClient


def _patch_client(monkeypatch, handler):
    real = REAL_CLIENT
    monkeypatch.setattr(
        ov.httpx, "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"}),
    )
    monkeypatch.setattr(ov, "FILE_POLL_INTERVAL_SECONDS", 0)


def _ok(video_item, usage=None):
    return {"status": "completed",
            "usage": usage or {"total_input_tokens": 10, "total_output_tokens": 100, "total_thought_tokens": 5},
            "steps": [{"type": "thought"}, {"type": "model_output", "content": [video_item]}]}


def test_text_to_video_body():
    body = build_request_body("a boat", **_kwargs())
    assert body["model"] == "gemini-omni-1.2-flash"
    assert body["input"] == "a boat"
    assert body["store"] is False
    assert body["response_format"] == {"type": "video", "aspect_ratio": "16:9",
                                       "resolution": "720p", "duration": "4s"}
    assert "generation_config" not in body


def test_first_frame_and_interpolation_bodies():
    one = build_request_body("go", **_kwargs(first_frame=OmniImage(IMG)))
    assert [p["type"] for p in one["input"]] == ["image", "text"]
    assert one["input"][0]["data"] == base64.b64encode(IMG).decode()
    two = build_request_body("go", **_kwargs(first_frame=OmniImage(IMG), last_frame=OmniImage(IMG, "image/png")))
    assert [p["type"] for p in two["input"]] == ["image", "image", "text"]
    assert two["input"][1]["mime_type"] == "image/png"


def test_uri_delivery_requires_store():
    body = build_request_body("x", **_kwargs(delivery="uri"))
    assert body["response_format"]["delivery"] == "uri" and body["store"] is True


def test_reference_and_extend_bodies():
    ref = build_request_body("x", **_kwargs(reference_images=[OmniImage(IMG)] * 2))
    assert ref["generation_config"] == {"video_config": {"task": "reference_to_video"}}
    ext = build_request_body("x", duration_seconds=5, aspect_ratio="16:9", resolution="720p",
                             first_frame=None, last_frame=None, reference_images=(),
                             source_video=b"vid", delivery="inline")
    assert ext["generation_config"]["video_config"]["task"] == "extend"
    assert "aspect_ratio" not in ext["response_format"]
    assert ext["input"][0]["type"] == "video"


@pytest.mark.parametrize("over", [
    dict(duration_seconds=2), dict(duration_seconds=16), dict(aspect_ratio="1:1"),
    dict(resolution="480p"), dict(last_frame=OmniImage(IMG)),
    dict(first_frame=OmniImage(IMG), last_frame=OmniImage(IMG), duration_seconds=11),
    dict(reference_images=[OmniImage(IMG)] * 7),
    dict(first_frame=OmniImage(IMG), reference_images=[OmniImage(IMG)]),
    dict(source_video=b"v", duration_seconds=12),
])
def test_invalid_combinations_raise(over):
    with pytest.raises(OmniInvalidArgumentError):
        build_request_body("x", **_kwargs(**over))


def test_empty_prompt_rejected():
    with pytest.raises(OmniInvalidArgumentError):
        build_request_body("  ", **_kwargs())


def test_inline_response_is_parsed_and_measured(monkeypatch, mp4):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["key"] = request.headers["x-goog-api-key"]
        return httpx.Response(200, json=_ok({"type": "video", "mime_type": "video/mp4",
                                              "data": base64.b64encode(mp4).decode()}))

    _patch_client(monkeypatch, handler)
    video = asyncio.run(generate_omni_video("a boat", duration_seconds=4))
    assert seen["key"] == "test-secret-key"
    assert seen["body"]["store"] is False
    assert video.mp4 == mp4
    assert (video.width, video.height) == (64, 48)
    assert 1.8 <= video.duration_seconds <= 2.2  # measured, not the requested 4
    assert (video.input_tokens, video.output_tokens, video.thought_tokens) == (10, 100, 5)


def test_uri_response_polls_file_then_downloads(monkeypatch, mp4):
    calls = []
    uri = "https://generativelanguage.googleapis.com/v1beta/files/abc123:download?alt=media"

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(200, json=_ok({"type": "video", "mime_type": "video/mp4", "uri": uri}))
        if request.url.path.endswith("/files/abc123"):
            state = "PROCESSING" if calls.count(("GET", request.url.path)) == 1 else "ACTIVE"
            return httpx.Response(200, json={"state": state})
        return httpx.Response(200, content=mp4)

    _patch_client(monkeypatch, handler)
    video = asyncio.run(generate_omni_video("x", duration_seconds=4, delivery="uri"))
    assert video.mp4 == mp4
    assert calls.count(("GET", "/v1beta/files/abc123")) == 2


def _error_handler(status, message, name="INVALID_ARGUMENT"):
    return lambda request: httpx.Response(
        status, json={"error": {"code": status, "message": message, "status": name}})


@pytest.mark.parametrize("status,message,exc", [
    (400, "duration out of range", OmniInvalidArgumentError),
    (404, "model not found", OmniInvalidArgumentError),
    (400, "Input blocked: uploaded video isn't available in your region.", OmniRegionError),
    (400, "Prompt blocked by safety filters", OmniSafetyError),
    (429, "quota exhausted", OmniUnavailableError),
    (503, "overloaded", OmniUnavailableError),
    (403, "key denied", OmniUnavailableError),
])
def test_http_errors_map_to_typed_errors(monkeypatch, status, message, exc):
    _patch_client(monkeypatch, _error_handler(status, message))
    with pytest.raises(exc):
        asyncio.run(generate_omni_video("x", duration_seconds=4))


def test_no_video_output_is_safety_error(monkeypatch):
    _patch_client(monkeypatch, lambda r: httpx.Response(200, json={"status": "completed", "steps": []}))
    with pytest.raises(OmniSafetyError):
        asyncio.run(generate_omni_video("x", duration_seconds=4))


def test_timeout_and_transport_errors(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    def down(request):
        raise httpx.ConnectError("refused test-secret-key", request=request)

    _patch_client(monkeypatch, timeout)
    with pytest.raises(OmniTimeoutError):
        asyncio.run(generate_omni_video("x", duration_seconds=4))
    _patch_client(monkeypatch, down)
    with pytest.raises(OmniUnavailableError) as info:
        asyncio.run(generate_omni_video("x", duration_seconds=4))
    assert "test-secret-key" not in str(info.value)


def test_missing_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.delenv("SECRET__GOOGLE_AI_STUDIO__API_KEY", raising=False)
    with pytest.raises(OmniUnavailableError):
        asyncio.run(generate_omni_video("x", duration_seconds=4))
