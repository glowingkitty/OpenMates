"""A saved Browse embed reaches chat history without screenshot bytes or metrics.

Specification: feature.app-skill.web-browse (form-with-user). Module stubs as in
test_audio_recording_embed_filter.py so EmbedService imports without services.
"""

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



# contract-test: supporting surface=rest_api assertions=web-browse.form-with-user
def test_browse_embed_history_view_keeps_the_form_and_drops_screenshot_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.core.api.app.services import embed_service

    monkeypatch.setattr(embed_service, "decode", decode)
    monkeypatch.setattr(embed_service, "encode", encode)
    service = embed_service.EmbedService(cache_service=None, directus_service=None, encryption_service=None)  # type: ignore[arg-type]  # stubbed services are not used by the filter
    form = [{"label": "Email address", "kind": "type", "value": ""}]
    toon_content = encode(
        {
            "type": "app_skill_use",
            "app_id": "web",
            "skill_id": "browse",
            "status": "finished",
            "embed_ref": "browse-form-abc",
            "results": [
                {
                    "status": "needs_user",
                    "url": "https://forms.example.org/apply",
                    "observations_form": form,
                    "observations_text": "unverified page text",
                    "screenshot_base64": "A" * 60000,
                    "metrics_steps": 3,
                }
            ],
        }
    )

    filtered_toon, embed_ref = service._filter_toon_for_llm(toon_content, "browse-embed-id", "[test] ", {})

    filtered = decode(filtered_toon)
    assert embed_ref == "browse-form-abc"
    assert filtered["results"] == [
        {"status": "needs_user", "url": "https://forms.example.org/apply", "observations_form": form}
    ]
    assert "AAAA" not in filtered_toon
