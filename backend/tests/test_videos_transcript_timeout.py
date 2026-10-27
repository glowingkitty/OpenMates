"""Unsupported transcript requests must fail before any network or secret access."""

import pytest
from backend.tests.test_media_ccc_skill import transcript_module  # noqa: F401


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ",
])
async def test_unsupported_transcript_requests_fail_without_provider_access(transcript_module, monkeypatch, url):  # noqa: F811
    async def forbidden(*args, **kwargs):
        pytest.fail("Unsupported sources must never invoke a caption provider")

    monkeypatch.setattr(transcript_module.MediaCCCClient, "fetch_transcript", forbidden)
    skill = transcript_module.TranscriptSkill(
        app=None, app_id="videos", skill_id="get_transcript",
        skill_name="Transcript", skill_description="Published captions",
    )
    request_id, results, error = await skill._process_single_transcript_request({"url": url}, 1, None)
    assert request_id == 1
    assert results == []
    assert "unavailable" in error
