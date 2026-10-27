"""Pixel transport and fail-closed visual admission through the native Jev wire."""
import base64
from io import BytesIO
import json

import httpx
from PIL import Image
import pytest

from backend.apps.ai.daily_inspiration import thumbnail_review
from backend.shared.providers.typesafe.client import JevDecisionClient


class Secrets:
    async def get_secret(self, **_kwargs):
        return "test-key"


def image_bytes():
    out = BytesIO()
    Image.new("RGB", (480, 360), "blue").save(out, format="JPEG")
    return out.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["suitable", "reject", "uncertain", "outage", "missing", "low_confidence"])
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_actual_pixels_reach_jev_and_only_visual_approval_admits(monkeypatch, decision):
    received = []
    async def fetch(identity):
        assert identity == "DOH-HNotTaE"
        return thumbnail_review.prepare_thumbnail(image_bytes())
    monkeypatch.setattr(thumbnail_review, "fetch_thumbnail", fetch)
    async def handler(request):
        body = json.loads(request.content)
        received.append(body)
        assert request.headers["TypeSafe-Danger-Zone-Images"] == "true"
        assert request.url.host == "api.typesafe.ai"
        asset = body["assets"][body["state"]["thumbnail"]]
        with Image.open(BytesIO(base64.b64decode(asset["data_base64"]))) as image:
            assert image.size == (560, 420)
        assert "printed in the image" in body["questions"]["visual"]["instructions"]
        if decision == "outage":
            return httpx.Response(503)
        choice = decision if decision in {"suitable", "reject", "uncertain"} else "suitable"
        answers = {"visual": {"type": "choice", "choice": choice,
                    "probabilities": {choice: 1.0}, "confidence": .1 if decision == "low_confidence" else 1.0}}
        return httpx.Response(200, json={"model": "jev-1.14.0", "answers": {} if decision == "missing" else answers})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await thumbnail_review.review_thumbnails([{"youtube_id": "DOH-HNotTaE", "title": "Architecture",
            "thumbnail_url": "http://127.0.0.1/private"}],
            JevDecisionClient(secrets_manager=Secrets(), http_client=http, provider="typesafe", max_retries=0))
    assert len(received) == 1
    assert bool(result) == (decision == "suitable")
    if result:
        assert result[0]["thumbnail_url"] == "https://i.ytimg.com/vi/DOH-HNotTaE/hqdefault.jpg"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_missing_thumbnail_never_degrades_to_text_only_review(monkeypatch):
    async def unavailable(_identity):
        raise httpx.ReadTimeout("unavailable")
    monkeypatch.setattr(thumbnail_review, "fetch_thumbnail", unavailable)
    class NoInference:
        async def evaluate(self, **_kwargs):
            pytest.fail("Missing pixels must not reach Jev as text")
    assert await thumbnail_review.review_thumbnails([{"youtube_id": "DOH-HNotTaE"}], NoInference()) == []


# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
@pytest.mark.parametrize("identity", ["../private", "https://evil.invalid/", "a" * 12, "DOH-HNotTaE?x=1"])
def test_thumbnail_urls_are_constructed_only_from_valid_video_ids(identity):
    with pytest.raises(ValueError):
        thumbnail_review.thumbnail_url(identity)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_high_text_rank_cannot_bypass_visual_rejection(monkeypatch):
    from backend.apps.ai.daily_inspiration import decisions
    async def pixels(_identity):
        return thumbnail_review.prepare_thumbnail(image_bytes())
    monkeypatch.setattr(thumbnail_review, "fetch_thumbnail", pixels)
    calls = []
    async def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if body.get("assets"):
            answers = {"visual": {"type": "choice", "choice": "reject",
                                  "probabilities": {"reject": 1.0}, "confidence": 1.0}}
        else:
            answers = {}
            for key, question in body["questions"].items():
                if question["type"] == "score":
                    answers[key] = {"type": "score", "score": 4, "confidence": 1.0,
                                    "legend": {str(i): label for i, label in enumerate(question["criteria"])},
                                    "probabilities": {str(i): 1.0 if i == 4 else 0.0 for i in range(5)}}
                else:
                    choice = "science" if key.endswith("_category") else "allow"
                    answers[key] = {"type": "choice", "choice": choice,
                                    "probabilities": {choice: 1.0}, "confidence": 1.0}
        return httpx.Response(200, json={"model": "jev-1.14.0", "answers": answers})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await decisions.review_candidates([{"youtube_id": "DOH-HNotTaE", "title": "Cloud formation",
            "description": "Cooling vapor condenses into droplets."}], Secrets(), rank=True,
            client=JevDecisionClient(secrets_manager=Secrets(), http_client=http, provider="typesafe", max_retries=0))
    assert result == []
    assert len(calls) == 2
    assert "assets" in calls[1]
