"""Deterministic coverage of public CCC captions, language choice and safe IO."""

import asyncio
import json

import httpx
import pytest

from backend.shared.providers.media_ccc import MediaCCCClient, MediaCCCError, extract_media_ccc_slug
from backend.shared.providers.media_ccc import client as provider
from backend.shared.providers.media_ccc.client import parse_captions

URL = "https://media.ccc.de/v/39c3-a-post-american-enshittification-resistant-internet"
CAPTION_URL = "https://cdn.media.ccc.de/congress/2025/test.vtt"
VTT = "WEBVTT\n\nNOTE not a cue\nignore me\n\ncue-1\n00:01.250 --> 00:03.500 align:start\n<v Cory>Hello &amp; welcome</v>\nsecond line\n"


def lecture(tracks=None):
    return {"data": {"lectureBySlug": {"title": "Public talk", "originalLanguage": "eng", "subtitles": tracks if tracks is not None else [{"url": CAPTION_URL, "mimeType": "text/vtt", "language": "eng"}]}}}


@pytest.mark.parametrize("url", [
    "https://media.ccc.de.evil.test/v/talk", "https://evil.test/media.ccc.de/v/talk",
    "https://media.ccc.de@127.0.0.1/v/talk", "http://media.ccc.de/v/talk",
    "https://media.ccc.de:8443/v/talk", "https://media.ccc.de/v/a/b",
    "https://media.ccc.de/v/../graphql", "https://media.ccc.de/v/%2fgraphql",
])
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.assistant.bounded-private-failure
def test_rejects_noncanonical_talk_urls(url):
    assert extract_media_ccc_slug(url) is None


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.assistant.bounded-private-failure
def test_slug_ignores_query_and_fragment():
    assert extract_media_ccc_slug(URL + "?tracking=private#t=20") == URL.rsplit("/", 1)[1]


@pytest.mark.parametrize("content", [VTT, "\ufeff1\r\n00:00:01,250 --> 00:00:03,500\r\nHello &amp; welcome\r\nsecond line\r\n"])
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.assistant.bounded-private-failure
def test_parses_srt_and_vtt_without_cue_ids_or_markup(content):
    captions = parse_captions(content)
    assert [caption.model_dump() for caption in captions] == [{"start": 1.25, "duration": 2.25, "text": "Hello & welcome second line"}]


@pytest.mark.parametrize("content", ["WEBVTT\n\nNOTE no captions", "<html>Unavailable</html>", "1\n00:00:05,000 --> 00:00:01,000\nBad timing"])
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.assistant.bounded-private-failure
def test_empty_or_invalid_captions_fail_visibly(content):
    with pytest.raises(MediaCCCError):
        parse_captions(content)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.assistant.bounded-private-failure
async def test_uses_graphql_variables_and_normalizes_language_with_safe_cdn_redirect():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            assert json.loads(request.content)["variables"] == {"slug": URL.rsplit("/", 1)[1]}
            assert b"tracking" not in request.content
            return httpx.Response(200, json=lecture())
        if request.url.host == "cdn.media.ccc.de":
            return httpx.Response(302, headers={"location": "https://mirror.selfnet.de/c3subtitles/test.vtt"})
        return httpx.Response(200, text=VTT)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        transcript = await MediaCCCClient(http).fetch_transcript(URL + "?tracking=private", ["en"])
    assert transcript.language == "en"
    assert transcript.captions[0].text == "Hello & welcome second line"
    assert [request.method for request in requests] == ["POST", "GET", "GET"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.assistant.bounded-private-failure
async def test_language_preferences_choose_german_over_english_and_vtt_over_srt():
    tracks = [
        {"url": CAPTION_URL, "mimeType": "text/vtt", "language": "eng"},
        {"url": CAPTION_URL + ".de.srt", "mimeType": "application/x-subrip", "language": "deu"},
        {"url": CAPTION_URL + ".de.vtt", "mimeType": "text/vtt", "language": "deu"},
    ]

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json=lecture(tracks))
        assert str(request.url).endswith(".de.vtt")
        return httpx.Response(200, text=VTT)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await MediaCCCClient(http).fetch_transcript(URL, ["de-DE", "en"])
    assert result.language == "de"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,error", [
    (lecture([]), "No published captions"),
    ({"data": {"lectureBySlug": None}}, "not found"),
    ({"errors": [{"message": "backend failure"}]}, "caption metadata"),
    (lecture([{ "url": CAPTION_URL, "mimeType": "text/vtt", "language": "fra"}]), "Available languages: fr"),
])
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.assistant.bounded-private-failure
async def test_missing_captions_language_or_talk_returns_explicit_error(payload, error):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as http:
        with pytest.raises(MediaCCCError, match=error):
            await MediaCCCClient(http).fetch_transcript(URL, ["en"])


@pytest.mark.asyncio
@pytest.mark.parametrize("redirect", [False, True])
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.assistant.bounded-private-failure
async def test_rejects_untrusted_caption_hosts_before_request(redirect):
    requested = []

    def handler(request):
        requested.append(request.url.host)
        if request.method == "POST":
            tracks = [{"url": CAPTION_URL if redirect else "https://127.0.0.1/private.vtt", "mimeType": "text/vtt", "language": "eng"}]
            return httpx.Response(200, json=lecture(tracks))
        return httpx.Response(302, headers={"location": "https://127.0.0.1/private.vtt"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(MediaCCCError, match="unsupported caption download host"):
            await MediaCCCClient(http).fetch_transcript(URL)
    assert "127.0.0.1" not in requested


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.assistant.bounded-private-failure
async def test_retries_rate_limit_without_unbounded_wait(monkeypatch):
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(provider.asyncio, "sleep", sleep)
    responses = iter([httpx.Response(429, headers={"retry-after": "99999"}), httpx.Response(200, json=lecture()), httpx.Response(200, text=VTT)])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: next(responses))) as http:
        result = await MediaCCCClient(http).fetch_transcript(URL)
    assert result.language == "en"
    assert sleeps == [5.0]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.assistant.bounded-private-failure
async def test_deadline_bounds_the_whole_fetch(monkeypatch):
    async def handler(request):
        await asyncio.Future()

    monkeypatch.setattr(provider, "FETCH_TIMEOUT_SECONDS", 0.01)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(MediaCCCError, match="timed out"):
            await MediaCCCClient(http).fetch_transcript(URL)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.assistant.bounded-private-failure
async def test_oversized_captions_fail_visibly(monkeypatch):
    monkeypatch.setattr(provider, "MAX_RESPONSE_BYTES", 500)

    def handler(request):
        return httpx.Response(200, json=lecture()) if request.method == "POST" else httpx.Response(200, text="x" * 501)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(MediaCCCError, match="size limit"):
            await MediaCCCClient(http).fetch_transcript(URL)
