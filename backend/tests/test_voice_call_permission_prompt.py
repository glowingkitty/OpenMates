# contract-test-file: infrastructure
# backend/tests/test_voice_call_permission_prompt.py
#
# A call turn that pauses for the user's tap is spoken: the client gets
# pre-recorded lines (no inference, no credits) and the answer after a focus
# decision stays a spoken call turn instead of a silent text turn.

import asyncio
import importlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

from backend.apps.ai.assistant_speech.call_permission_prompt import (
    CALL_PERMISSION_PROMPT_EVENT,
    build_call_permission_prompt,
    publish_call_permission_prompt,
)
from backend.apps.audio.assistant_speech.acknowledgements import (
    ACKNOWLEDGEMENT_ASSET_ROOT,
    PERMISSION_PROMPT_TEXTS,
    build_permission_prompt_clips,
)

STATIC_ROOT = Path(__file__).resolve().parents[2] / "frontend/apps/web_app/static"
MATES = [SimpleNamespace(id="software_development", voice_profile=SimpleNamespace(key="sophia"))]


def _call_turn(**overrides):
    values = dict(
        chat_id="chat-1", voice_mode=True, auto_speak_response=True, is_external=False,
        is_incognito=False, voice_call_id="a" * 32,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


# contract-test: supporting surface=rest_api assertions=video-call.chat.permission-prompt
def test_memory_prompt_in_a_call_uses_the_answering_mates_recorded_lines():
    payload = build_call_permission_prompt(
        request_data=_call_turn(), mates=MATES, mate_id="software_development",
        language="de", request_id="req-1", kind="memory",
    )
    assert payload["kind"] == "memory" and payload["request_id"] == "req-1"
    assert payload["voice_call_id"] == "a" * 32
    assert payload["clips"] == {
        "request": f"{ACKNOWLEDGEMENT_ASSET_ROOT}/sophia/de-DE/needs_memory-1.mp3",
        "reminder": f"{ACKNOWLEDGEMENT_ASSET_ROOT}/sophia/de-DE/needs_reminder-1.mp3",
        "thanks": f"{ACKNOWLEDGEMENT_ASSET_ROOT}/sophia/de-DE/approval_thanks-1.mp3",
        "timeout": f"{ACKNOWLEDGEMENT_ASSET_ROOT}/sophia/de-DE/memory_timeout-1.mp3",
    }


# contract-test: supporting surface=rest_api assertions=video-call.chat.permission-prompt
def test_approval_prompt_never_times_out():
    payload = build_call_permission_prompt(
        request_data=_call_turn(), mates=MATES, mate_id="software_development",
        language="en", request_id="req-2", kind="approval",
    )
    assert payload["clips"]["request"].endswith("/sophia/en-US/needs_approval-1.mp3")
    assert "timeout" not in payload["clips"]


# contract-test: supporting surface=rest_api assertions=video-call.chat.permission-prompt
def test_text_turns_and_unknown_voices_stay_silent():
    common = dict(mates=MATES, mate_id="software_development", language="en", request_id="r", kind="memory")
    assert build_call_permission_prompt(request_data=_call_turn(voice_mode=False), **common) is None
    assert build_call_permission_prompt(request_data=_call_turn(voice_call_id=None), **common) is None
    assert build_call_permission_prompt(request_data=_call_turn(is_incognito=True), **common) is None
    assert build_call_permission_prompt(request_data=_call_turn(), **{**common, "mate_id": "unknown"}) is None
    assert build_call_permission_prompt(request_data=_call_turn(), **{**common, "language": "xx"}) is None


def test_every_recorded_prompt_line_ships_as_a_static_asset():
    manifest = json.loads((STATIC_ROOT / "audio/assistant-acknowledgements/manifest.json").read_text())
    shipped = {entry["relative_path"] for entry in manifest["clips"]}
    voices = sorted(p.name for p in (STATIC_ROOT / "audio/assistant-acknowledgements").iterdir()
                    if p.is_dir() and p.name != "system")
    assert len(voices) == 17
    for language in PERMISSION_PROMPT_TEXTS:
        for voice in voices:
            for url in build_permission_prompt_clips(voice_profile_id=voice, language=language).values():
                relative = url.removeprefix(f"{ACKNOWLEDGEMENT_ASSET_ROOT}/")
                assert relative in shipped, relative
                assert (STATIC_ROOT / url.lstrip("/")).stat().st_size > 1000, relative


def test_prompt_is_published_to_the_users_devices_only():
    published = []

    class _Redis:
        async def publish(self, channel, message):
            published.append((channel, json.loads(message)))

    class _Cache:
        @property
        async def client(self):
            return _Redis()

    cache = _Cache()
    payload = {"request_id": "req-1", "chat_id": "chat-1"}
    assert asyncio.run(publish_call_permission_prompt(
        cache_service=cache, user_id="user-1", payload=payload, log_prefix="[t]"))
    assert published == [("user_cache_events:user-1", {"event_type": CALL_PERMISSION_PROMPT_EVENT, "payload": payload})]
    assert not asyncio.run(publish_call_permission_prompt(
        cache_service=cache, user_id="user-1", payload=None, log_prefix="[t]"))


# contract-test: supporting surface=rest_api assertions=video-call.chat.permission-prompt
def test_focus_decisions_continue_as_the_same_spoken_call_turn():
    """Regression: after a focus decision the answer started silently and was never read out."""
    from backend.apps.ai.processing import main_processor
    auto = importlib.import_module("backend.apps.ai.tasks.focus_mode_auto_confirm_task")
    from backend.apps.ai.testing import mock_replay
    from backend.core.api.app.routes.handlers.websocket_handlers import focus_mode_rejected_handler as rejected

    assert inspect.getsource(main_processor).count("**paused_voice_delivery(request_data)") >= 2
    assert "**paused_voice_delivery(request_data)" in inspect.getsource(mock_replay)
    assert "resumed_voice_delivery(" in inspect.getsource(auto)
    assert "resumed_voice_delivery(" in inspect.getsource(rejected._trigger_continuation_without_focus)


# contract-test: supporting surface=rest_api assertions=video-call.chat.permission-prompt
def test_replayed_call_turn_with_placeholder_mate_speaks_as_its_category_mate():
    from backend.apps.ai.testing.mock_replay import build_preprocessing_result, fixture_answering_mate_id
    from backend.apps.ai.utils.mate_utils import load_mates_config

    mates = load_mates_config()
    fixture = json.loads(Path("backend/apps/ai/testing/fixtures/memory_reuse_load.json").read_text())
    result = build_preprocessing_result(fixture)
    assert result.selected_mate_id == "default"
    answering = fixture_answering_mate_id(result, mates)
    assert answering in {mate.id for mate in mates if mate.category == result.category}
    payload = build_call_permission_prompt(
        request_data=SimpleNamespace(voice_mode=True, auto_speak_response=True, is_external=False,
                                     is_incognito=False, voice_call_id="call-1", chat_id="chat-1", mate_id=None),
        mates=mates, mate_id=answering, language=result.output_language, request_id="req-1", kind="memory",
    )
    assert payload is not None and payload["clips"]["request"]
    real = SimpleNamespace(selected_mate_id="finn", category=result.category)
    assert fixture_answering_mate_id(real, mates) == "finn"
