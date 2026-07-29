# backend/tests/test_audio_recording_embed_filter.py
# Regression tests for LLM-visible audio recording embed filtering.
#
# Audio recordings can store both raw and auto-corrected transcript variants.
# The fullscreen toggle controls which variant should become request context.
# These tests ensure the backend honors that choice before prompt assembly.

import json
import sys
import types

import pytest

toon_stub = types.ModuleType("toon_format")
toon_stub.encode = lambda value: json.dumps(value)
toon_stub.decode = lambda value: json.loads(value)
sys.modules.setdefault("toon_format", toon_stub)

cache_stub = types.ModuleType("backend.core.api.app.services.cache")
cache_stub.CacheService = object
sys.modules.setdefault("backend.core.api.app.services.cache", cache_stub)

directus_stub = types.ModuleType("backend.core.api.app.services.directus")
directus_stub.DirectusService = object
sys.modules.setdefault("backend.core.api.app.services.directus", directus_stub)

encryption_stub = types.ModuleType("backend.core.api.app.utils.encryption")
encryption_stub.EncryptionService = object
sys.modules.setdefault("backend.core.api.app.utils.encryption", encryption_stub)

youtube_stub = types.ModuleType("backend.shared.providers.youtube.youtube_metadata")
youtube_stub.extract_youtube_id_from_url = lambda url: None
sys.modules.setdefault("backend.shared.providers.youtube.youtube_metadata", youtube_stub)

github_stub = types.ModuleType("backend.shared.providers.github")
github_stub.build_github_repo_embed = lambda url: None
github_stub.is_github_repo_url = lambda url: isinstance(url, str) and url.rstrip("/").count("/") == 4 and url.startswith("https://github.com/")
sys.modules.setdefault("backend.shared.providers.github", github_stub)

e2b_preview_stub = types.ModuleType("backend.shared.providers.e2b_application_preview")
e2b_preview_stub.ApplicationPreviewEntrypoint = object
e2b_preview_stub.ApplicationPreviewFile = object
e2b_preview_stub.ApplicationPreviewPlanningError = Exception
e2b_preview_stub.plan_application_preview_startup = lambda *args, **kwargs: None
sys.modules.setdefault("backend.shared.providers.e2b_application_preview", e2b_preview_stub)

decode = toon_stub.decode
encode = toon_stub.encode


def test_audio_recording_filter_uses_original_transcript_when_correction_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "toon_format", toon_stub)
    monkeypatch.delitem(sys.modules, "backend.core.api.app.services.embed_service", raising=False)

    from backend.core.api.app.services.embed_service import EmbedService

    service = EmbedService(cache_service=None, directus_service=None, encryption_service=None)  # type: ignore[arg-type]
    toon_content = encode(
        {
            "type": "audio-recording",
            "status": "finished",
            "filename": "voice-note.webm",
            "mime_type": "audio/webm",
            "transcript": "stale corrected transcript",
            "transcript_original": "raw original transcript",
            "transcript_corrected": "stale corrected transcript",
            "use_corrected": False,
        }
    )

    filtered_toon, _embed_ref = service._filter_toon_for_llm(
        toon_content,
        "audio-embed-id",
        "[test] ",
        {},
    )

    assert decode(filtered_toon)["transcript"] == "raw original transcript"
