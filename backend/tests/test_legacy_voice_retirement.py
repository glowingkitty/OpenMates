"""Keep retired direct-provider call paths out of the shared chat transport."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


# contract-test: supporting surface=rest_api assertions=video-call.provider.boundary
def test_retired_call_adapters_and_experiment_are_not_callable():
    retired = (
        "backend/shared/providers/gemini_live_voice.py",
        "backend/apps/ai/processing/voice_call_broker.py",
        "backend/apps/ai/processing/voice_call_broker_runtime.py",
        "backend/apps/ai/processing/voice_async_skills.py",
        "backend/apps/ai/processing/voice_project_tools.py",
        "backend/apps/ai/tasks/voice_call_task.py",
        "backend/core/api/app/routes/video_call_experiment.py",
        "frontend/apps/web_app/src/routes/experiment/videocall/+page.svelte",
        "frontend/packages/ui/src/components/videocall/callController.ts",
    )
    assert all(not (ROOT / path).exists() for path in retired)
    for path in (ROOT / "backend").rglob("*.py"):
        if "tests" in path.parts:
            continue
        source = path.read_text()
        assert "voice_call_broker" not in source, str(path)
        assert "video_call_experiment" not in source, str(path)
        assert "gemini_live_voice" not in source, str(path)
        assert "apps.ai.tasks.voice_call_request" not in source, str(path)


# contract-test: supporting surface=rest_api assertions=video-call.provider.boundary
def test_standard_google_chat_and_media_providers_remain_available():
    catalog = yaml.safe_load((ROOT / "backend/providers/google.yml").read_text())
    assert catalog["provider_id"] == "google"
    models = catalog["models"]
    assert any(model.get("for_app_skill") == "ai.ask" for model in models)
    assert all("live" not in model["id"].lower() for model in models)
    assert (ROOT / "backend/apps/ai/llm_providers/google_client.py").is_file()
    assert (ROOT / "backend/shared/providers/google/gemini_image.py").is_file()
    assert (ROOT / "backend/shared/providers/google/gemini_video.py").is_file()
