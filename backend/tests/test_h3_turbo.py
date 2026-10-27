"""Direct, offline HTTP-contract coverage for H3 first-frame submissions."""

import base64
from io import BytesIO
import json

import httpx
from PIL import Image
import pytest

from backend.shared.providers.fal import h3_turbo


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance,video-call.video.fast-generation-default,video-call.privacy
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("image_format", "mime_type"),
    [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")],
)
async def test_h3_submit_preserves_first_frame_bytes_and_mime(image_format, mime_type):
    source = BytesIO()
    Image.new("RGB", (16, 12), (23, 83, 149)).save(source, format=image_format)
    source_bytes = source.getvalue()
    prompt = "Animate this saved garden image with a gentle camera movement."
    requests = []
    request_id = "owned-job-1"
    result_url = f"https://queue.fal.run/minimax/h3-max-turbo/requests/{request_id}"

    def handle(request):
        requests.append(request)
        assert request.method == "POST"
        assert str(request.url) == h3_turbo.QUEUE_URL
        assert not request.url.query
        assert request.headers["Authorization"] == "Key offline-test-key"
        payload = json.loads(request.content)
        assert payload == {
            "prompt": h3_turbo.VIDEO_DIRECTION + prompt + h3_turbo.VIDEO_DIRECTION_END,
            "duration": 5,
            "resolution": "480P",
            "prompt_expansion_mode": "disabled",
            "enable_safety_checker": True,
            "seed": 37,
            "image_url": f"data:{mime_type};base64," + base64.b64encode(source_bytes).decode("ascii"),
        }
        assert base64.b64decode(payload["image_url"].split(",", 1)[1], validate=True) == source_bytes
        assert b"offline-test-key" not in request.content
        return httpx.Response(200, json={
            "request_id": request_id,
            "status_url": result_url + "/status",
            "response_url": result_url,
            "cancel_url": result_url + "/cancel",
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        job = await h3_turbo.submit_clip(
            client, key="offline-test-key", prompt=prompt,
            image_jpeg=source_bytes, image_mime_type=mime_type, seed=37,
        )

    assert len(requests) == 1
    assert job == h3_turbo.FalJob(request_id, result_url + "/status", result_url, result_url + "/cancel")


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance,video-call.privacy
@pytest.mark.asyncio
async def test_h3_submit_rejects_unsupported_image_mime_before_http():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match="Unsupported fal input image format"):
            await h3_turbo.submit_clip(
                client, key="offline-test-key", prompt="Animate this saved image.",
                image_jpeg=b"GIF89a", image_mime_type="image/gif", seed=37,
            )

    assert requests == []
