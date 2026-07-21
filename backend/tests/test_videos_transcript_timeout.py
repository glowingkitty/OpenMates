# backend/tests/test_videos_transcript_timeout.py
#
# Unit coverage for the YouTube transcript backend timeout contract.
# Provider calls are intentionally mocked here because live YouTube and proxy
# behavior is quota- and network-dependent. The workflow capability smoke tests
# only need this skill to fail quickly and visibly when the provider stalls.

import asyncio
import importlib
import sys
from types import ModuleType
from typing import Any

import pytest

TRANSCRIPT_MODULE_NAME = "backend.apps.videos.skills.transcript_skill"


def _stub_module(name: str, attributes: dict[str, Any]) -> ModuleType:
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


@pytest.mark.asyncio
async def test_fetch_transcript_times_out_when_provider_future_stalls(monkeypatch) -> None:
    previous_transcript_module = sys.modules.pop(TRANSCRIPT_MODULE_NAME, None)
    try:
        stub_modules = {
            "celery": {"Celery": object},
            "backend.shared.providers.youtube.youtube_metadata": {"get_video_metadata_batched": object},
            "backend.core.api.app.services.creators.revenue_service": {"CreatorRevenueService": object},
            "backend.core.api.app.services.directus": {"DirectusService": object},
            "backend.core.api.app.utils.encryption": {"EncryptionService": object},
            "backend.core.api.app.services.cache": {"CacheService": object},
        }
        for name, attributes in stub_modules.items():
            monkeypatch.setitem(sys.modules, name, _stub_module(name, attributes))

        transcript_module = importlib.import_module(TRANSCRIPT_MODULE_NAME)

        skill = transcript_module.TranscriptSkill(
            app=None,
            app_id="videos",
            skill_id="get_transcript",
            skill_name="Get transcript",
            skill_description="Fetch YouTube transcript",
        )
        loop = asyncio.get_running_loop()
        stalled = loop.create_future()

        async def build_proxy_config(_secrets_manager):
            return None

        def run_in_executor(_executor, _func):
            return stalled

        monkeypatch.setattr(transcript_module, "YOUTUBE_TRANSCRIPT_AVAILABLE", True)
        monkeypatch.setattr(transcript_module, "TRANSCRIPT_FETCH_TIMEOUT_SECONDS", 0.01)
        monkeypatch.setattr(skill, "_build_webshare_proxy_config_async", build_proxy_config)
        monkeypatch.setattr(loop, "run_in_executor", run_in_executor)

        result = await skill._fetch_transcript(
            video_id="dQw4w9WgXcQ",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            secrets_manager=None,
            languages=["en"],
        )
    finally:
        sys.modules.pop(TRANSCRIPT_MODULE_NAME, None)
        if previous_transcript_module is not None:
            sys.modules[TRANSCRIPT_MODULE_NAME] = previous_transcript_module

    assert result == {
        "success": False,
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "error": "Transcript fetch timed out after 0.01s",
    }
