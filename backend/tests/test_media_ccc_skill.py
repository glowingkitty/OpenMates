"""Skill integration with deterministic captions and the real formatter/schema."""

import importlib
import sys
from types import ModuleType

import pytest

from backend.shared.providers.media_ccc.models import Caption, MediaCCCTranscript


@pytest.fixture
def transcript_module(monkeypatch):
    name = "backend.apps.videos.skills.transcript_skill"
    previous = sys.modules.pop(name, None)
    stubs = {
        "celery": {"Celery": object},
        "backend.shared.providers.youtube.youtube_metadata": {"get_video_metadata_batched": object},
        "backend.core.api.app.services.creators.revenue_service": {"CreatorRevenueService": object},
        "backend.core.api.app.services.directus": {"DirectusService": object},
        "backend.core.api.app.utils.encryption": {"EncryptionService": object},
        "backend.core.api.app.services.cache": {"CacheService": object},
    }
    for module_name, attributes in stubs.items():
        stub = ModuleType(module_name)
        vars(stub).update(attributes)
        monkeypatch.setitem(sys.modules, module_name, stub)
    try:
        yield importlib.import_module(name)
    finally:
        sys.modules.pop(name, None)
        if previous is not None:
            sys.modules[name] = previous


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.output.external-semantic
def test_request_schema_accepts_ccc_and_rejects_youtube(transcript_module):
    model = transcript_module.TranscriptRequestItem
    for url in ["https://media.ccc.de/v/public-talk"]:
        assert model(url=url).url == url
    for url in ["https://media.ccc.de.evil.test/v/talk", "https://www.youtube.com/shorts/dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"]:
        with pytest.raises(ValueError):
            model(url=url)


@pytest.mark.asyncio
@pytest.mark.parametrize("sanitized", ["[00:00:01.250] Safe caption", None, ""])
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.output.external-semantic
async def test_ccc_uses_shared_sanitizer_formatter_and_never_youtube_or_income(transcript_module, monkeypatch, sanitized):
    skill = transcript_module.TranscriptSkill(app=None, app_id="videos", skill_id="get_transcript", skill_name="Transcript", skill_description="Published captions")
    seen = []

    async def fetch(self, url, languages):
        assert url == "https://media.ccc.de/v/public-talk"
        assert languages == ["en"]
        return MediaCCCTranscript(title="Public talk", language="en", captions=[Caption(start=1.25, duration=2, text="Safe caption")])

    async def sanitize(**kwargs):
        seen.append(kwargs["content"])
        return sanitized

    monkeypatch.setattr(transcript_module.MediaCCCClient, "fetch_transcript", fetch)
    monkeypatch.setattr(transcript_module, "sanitize_external_content", sanitize)
    assert not hasattr(skill, "_fetch_transcript")
    assert not hasattr(skill, "_create_creator_income_for_video")
    request_id, results, error = await skill._process_single_transcript_request(
        {"url": "https://media.ccc.de/v/public-talk#t=5", "languages": ["en"]}, "ccc", None
    )
    assert request_id == "ccc"
    assert seen == ["[00:00:01.250] Safe caption"]
    if sanitized:
        assert error is None
        assert results[0]["provider"] == "media.ccc.de"
        assert results[0]["metadata"]["title"] == "Public talk"
        assert results[0]["transcript"] == sanitized
        assert results[0]["word_count"] == 2
    else:
        assert not results
        assert "sanitization" in error.lower()
