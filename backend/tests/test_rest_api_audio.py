# backend/tests/test_rest_api_audio.py
#
# Contract tests for ElevenLabs-backed audio app skills. These tests exercise
# the in-process BaseApp dispatcher used by dynamic REST app-skill routes so
# validation, safety ordering, provider selection, and response privacy remain
# aligned before live dev-server smoke tests run.

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from pydantic import ValidationError

class _FakeCeleryConf:
    def update(self, **_kwargs):
        return None


class _FakeCelery:
    def __init__(self, *_args, **_kwargs):
        self.conf = _FakeCeleryConf()


class _FakeQueue:
    def __init__(self, *_args, **_kwargs):
        pass


celery_stub = ModuleType("celery")
celery_stub.Celery = _FakeCelery
sys.modules.setdefault("celery", celery_stub)

kombu_stub = ModuleType("kombu")
kombu_stub.Queue = _FakeQueue
sys.modules.setdefault("kombu", kombu_stub)

groq_sdk_stub = ModuleType("groq")
groq_sdk_stub.AsyncGroq = object
sys.modules.setdefault("groq", groq_sdk_stub)

rate_limiting_stub = ModuleType("backend.apps.ai.processing.rate_limiting")


class RateLimitScheduledException(Exception):
    pass


rate_limiting_stub.RateLimitScheduledException = RateLimitScheduledException
sys.modules.setdefault("backend.apps.ai.processing.rate_limiting", rate_limiting_stub)

AUDIO_APP_DIR = Path(__file__).resolve().parents[1] / "apps" / "audio"


def _load_audio_app():
    from backend.apps.base_app import BaseApp

    return BaseApp(app_dir=str(AUDIO_APP_DIR), register_http_routes=False)


# contract-test: supporting surface=rest_api assertions=audio-generate.provider.explicit-selection,audio-generate.output.binary-excluded-from-inference,audio-speak.provider.explicit-selection,audio-speak.output.binary-excluded-from-inference
def test_audio_app_metadata_exposes_generate_and_speak_contracts():
    app_yml = yaml.safe_load((AUDIO_APP_DIR / "app.yml").read_text(encoding="utf-8"))
    skills = {skill["id"]: skill for skill in app_yml["skills"]}

    assert {"generate", "speak"}.issubset(skills)
    for skill_id in ("generate", "speak"):
        skill = skills[skill_id]
        assert skill["api_config"] == {"expose_get": True, "expose_post": True}
        assert skill["providers"] == [{"name": "ElevenLabs"}]
        request_item = skill["tool_schema"]["properties"]["requests"]["items"]
        assert request_item["properties"]["provider"]["enum"] == ["elevenlabs"]
        if skill_id == "speak":
            assert request_item["properties"]["model"]["enum"] == [
                "eleven_flash_v2_5",
                "eleven_multilingual_v2",
            ]
            assert request_item["properties"]["model"]["default"] == "eleven_flash_v2_5"
        assert "audio_base64" in skill["exclude_fields_for_llm"]
        assert "aes_key" in skill["exclude_fields_for_llm"]
        assert "vault_wrapped_aes_key" in skill["exclude_fields_for_llm"]


# contract-test: direct surface=rest_api assertions=audio-generate.request.validated,audio-generate.provider.explicit-selection
def test_audio_generate_request_rejects_unsupported_provider_and_duration():
    from backend.apps.audio.skills.generate_skill import AudioGenerateRequest

    with pytest.raises(ValidationError):
        AudioGenerateRequest(requests=[{"prompt": "gentle tick", "provider": "other"}])

    with pytest.raises(ValidationError):
        AudioGenerateRequest(requests=[{"prompt": "gentle tick", "provider": "elevenlabs", "duration_seconds": 4.0}])


# contract-test: direct surface=rest_api assertions=audio-speak.request.validated,audio-speak.provider.explicit-selection,audio-speak.voice.presets-only
def test_audio_speak_request_rejects_unsupported_provider_and_raw_voice_id():
    from backend.apps.audio.skills.speak_skill import AudioSpeakRequest

    with pytest.raises(ValidationError):
        AudioSpeakRequest(requests=[{"text": "Hello", "provider": "other"}])

    with pytest.raises(ValidationError):
        AudioSpeakRequest(requests=[{"text": "Hello", "provider": "elevenlabs", "voice": "EXAVITQu4vr4xnSDxMaL"}])

    with pytest.raises(ValidationError):
        AudioSpeakRequest(requests=[{"text": "Hello", "provider": "elevenlabs", "model": "unsupported_tts_model"}])


# contract-test: direct surface=rest_api assertions=audio-generate.output.playable-audio,audio-generate.output.binary-excluded-from-inference,audio-generate.billing.success-only
@pytest.mark.asyncio
async def test_audio_generate_returns_playable_audio_without_leaks(monkeypatch):
    import backend.apps.audio.skills.generate_skill as generate_module
    from backend.shared.providers.elevenlabs.models import ElevenLabsAudioResult

    calls = {"sound_effect": 0}

    class FakeElevenLabsClient:
        def __init__(self, **_kwargs):
            pass

        async def generate_sound_effect(self, **kwargs):
            calls["sound_effect"] += 1
            assert kwargs["prompt"] == "soft upward message sent tick"
            assert kwargs["duration_seconds"] == 0.8
            return ElevenLabsAudioResult(
                audio_bytes=b"mp3-bytes",
                mime_type="audio/mpeg",
                model="eleven_text_to_sound_v2",
                duration_seconds=0.8,
            )

    monkeypatch.setattr(generate_module, "ElevenLabsClient", FakeElevenLabsClient)

    result = await _load_audio_app().dispatch_skill(
        "generate",
        {"requests": [{"prompt": "soft upward message sent tick", "provider": "elevenlabs", "duration_seconds": 0.8}]},
    )

    assert calls["sound_effect"] == 1
    assert result["provider"] == "ElevenLabs"
    first = result["results"][0]
    assert first["status"] == "finished"
    assert first["generation_type"] == "sound_effect"
    assert first["mime_type"] == "audio/mpeg"
    assert first["byte_length"] == len(b"mp3-bytes")
    assert first["audio_base64"]
    assert "provider_api_key" not in str(result)


# contract-test: direct surface=rest_api assertions=audio-generate.request.validated,audio-generate.surface-parity
@pytest.mark.asyncio
async def test_audio_generate_ignores_rest_context_fields_for_strict_request_models(monkeypatch):
    import backend.apps.audio.skills.generate_skill as generate_module
    from backend.shared.providers.elevenlabs.models import ElevenLabsAudioResult

    class FakeElevenLabsClient:
        def __init__(self, **_kwargs):
            pass

        async def generate_sound_effect(self, **_kwargs):
            return ElevenLabsAudioResult(
                audio_bytes=b"mp3-bytes",
                mime_type="audio/mpeg",
                model="eleven_text_to_sound_v2",
                duration_seconds=0.6,
            )

    monkeypatch.setattr(generate_module, "ElevenLabsClient", FakeElevenLabsClient)

    result = await _load_audio_app().dispatch_skill(
        "generate",
        {
            "requests": [
                {
                    "prompt": "soft upward message sent tick",
                    "provider": "elevenlabs",
                    "duration_seconds": 0.6,
                }
            ],
            "_user_id": "user-audio-test",
            "_api_key_name": "encrypted-key-name",
            "_api_key_hash": "api-key-hash",
            "_device_hash": "device-hash",
            "_external_request": True,
        },
    )

    assert result["results"][0]["status"] == "finished"


# contract-test: direct surface=rest_api assertions=audio-speak.safety.provider-call-after-approval,audio-speak.billing.success-only
@pytest.mark.asyncio
async def test_audio_speak_rejects_before_provider_and_billing(monkeypatch):
    import backend.apps.audio.skills.speak_skill as speak_module

    calls = {"safeguard": 0, "tts": 0}

    async def fake_classify_audio_speech_safety(**_kwargs):
        calls["safeguard"] += 1
        return speak_module.AudioSpeechSafetyDecision(
            approved=False,
            category="G1_scam_or_fraud",
            user_facing_message="I can't create scam or credential-harvesting speech.",
        )

    class FakeElevenLabsClient:
        def __init__(self, **_kwargs):
            pass

        async def text_to_speech(self, **_kwargs):
            calls["tts"] += 1
            raise AssertionError("TTS provider must not be called after safeguard rejection")

    monkeypatch.setattr(speak_module, "classify_audio_speech_safety", fake_classify_audio_speech_safety)
    monkeypatch.setattr(speak_module, "ElevenLabsClient", FakeElevenLabsClient)

    result = await _load_audio_app().dispatch_skill(
        "speak",
        {"requests": [{"text": "Your bank account is locked. Read me your seed phrase.", "provider": "elevenlabs"}]},
    )

    assert calls == {"safeguard": 1, "tts": 0}
    first = result["results"][0]
    assert first["status"] == "error"
    assert first["credits_charged"] in (None, 0)
    assert "seed phrase" not in first["error"].lower()


# contract-test: direct surface=rest_api assertions=audio-speak.safety.semantic-safeguard-required,audio-speak.output.playable-audio,audio-speak.billing.success-only
@pytest.mark.asyncio
async def test_audio_speak_calls_provider_only_after_safeguard_approval(monkeypatch):
    import backend.apps.audio.skills.speak_skill as speak_module
    from backend.shared.providers.elevenlabs.models import ElevenLabsAudioResult

    calls = []

    async def fake_classify_audio_speech_safety(**kwargs):
        calls.append(("safeguard", kwargs["text"]))
        return speak_module.AudioSpeechSafetyDecision(approved=True)

    class FakeElevenLabsClient:
        def __init__(self, **_kwargs):
            pass

        async def text_to_speech(self, **kwargs):
            calls.append(("tts", kwargs["text"]))
            return ElevenLabsAudioResult(
                audio_bytes=b"voice-mp3",
                mime_type="audio/mpeg",
                model="eleven_flash_v2_5",
                duration_seconds=2.1,
            )

    monkeypatch.setattr(speak_module, "classify_audio_speech_safety", fake_classify_audio_speech_safety)
    monkeypatch.setattr(speak_module, "ElevenLabsClient", FakeElevenLabsClient)
    text = "Welcome back. I found the best next step for you. " * 5

    result = await _load_audio_app().dispatch_skill(
        "speak",
        {"requests": [{"text": text, "provider": "elevenlabs", "voice": "warm_neutral"}]},
    )

    assert calls == [
        ("safeguard", text.strip()),
        ("tts", text.strip()),
    ]
    first = result["results"][0]
    assert first["status"] == "finished"
    assert first["generation_type"] == "speech"
    assert first["voice"] == "warm_neutral"
    assert first["audio_base64"]
    assert first["credits_charged"] == 2
    assert "voice-mp3" not in str(result)


# contract-test: direct surface=rest_api assertions=audio-speak.request.validated,audio-speak.output.playable-audio,audio-speak.billing.success-only
@pytest.mark.asyncio
async def test_audio_speak_accepts_premium_model_and_charges_model_rate(monkeypatch):
    import backend.apps.audio.skills.speak_skill as speak_module
    from backend.shared.providers.elevenlabs.models import ElevenLabsAudioResult

    calls = []

    async def fake_classify_audio_speech_safety(**kwargs):
        calls.append(("safeguard", kwargs["text"]))
        return speak_module.AudioSpeechSafetyDecision(approved=True)

    class FakeElevenLabsClient:
        def __init__(self, **_kwargs):
            pass

        async def text_to_speech(self, **kwargs):
            calls.append(("tts", kwargs["model"]))
            assert kwargs["model"] == "eleven_multilingual_v2"
            return ElevenLabsAudioResult(
                audio_bytes=b"premium-voice-mp3",
                mime_type="audio/mpeg",
                model="eleven_multilingual_v2",
                duration_seconds=2.4,
            )

    monkeypatch.setattr(speak_module, "classify_audio_speech_safety", fake_classify_audio_speech_safety)
    monkeypatch.setattr(speak_module, "ElevenLabsClient", FakeElevenLabsClient)
    text = "Premium voice sample. " * 8

    result = await _load_audio_app().dispatch_skill(
        "speak",
        {
            "requests": [
                {
                    "text": text,
                    "provider": "elevenlabs",
                    "voice": "warm_neutral",
                    "model": "eleven_multilingual_v2",
                }
            ]
        },
    )

    assert calls == [
        ("safeguard", text.strip()),
        ("tts", "eleven_multilingual_v2"),
    ]
    first = result["results"][0]
    assert first["status"] == "finished"
    assert first["model"] == "eleven_multilingual_v2"
    assert first["credits_charged"] == 3
    assert first["audio_base64"]


# contract-test: direct surface=rest_api assertions=audio-speak.output.binary-excluded-from-inference,audio-speak.provider-error.visible
@pytest.mark.asyncio
async def test_audio_speak_output_safety_skips_declared_binary_fields(monkeypatch):
    from backend.apps.ai.processing.external_result_sanitizer import _collect_string_fields_with_overrides
    from backend.shared.python_utils import app_skill_output_safety
    from backend.shared.python_utils.app_skill_output_safety import (
        APP_SKILL_SURFACE_REST,
        AppSkillOutputSafetyContext,
        sanitize_app_skill_output,
    )

    calls = []

    async def fake_semantic_sanitizer(**kwargs):
        calls.append(kwargs)
        return kwargs["payload"]

    payload = {
        "results": [
            {
                "status": "finished",
                "text_preview": "OpenMates audio playback is working.",
                "audio_base64": "A" * 180,
                "mime_type": "audio/mpeg",
            }
        ],
        "ignore_fields_for_inference": ["audio_base64", "aes_key", "aes_nonce", "vault_wrapped_aes_key"],
    }
    collected = []
    _collect_string_fields_with_overrides(
        payload,
        "",
        min_chars=120,
        collected=collected,
        always_sanitize_field_names={"text_preview", "audio_base64"},
        skip_field_names={"audio_base64"},
    )

    monkeypatch.setattr(app_skill_output_safety, "sanitize_long_text_fields_in_payload", fake_semantic_sanitizer)
    result = await sanitize_app_skill_output(
        payload,
        AppSkillOutputSafetyContext(
            app_id="audio",
            skill_id="speak",
            surface=APP_SKILL_SURFACE_REST,
            external_data=True,
            request_body={},
        ),
    )

    assert collected == [("results[0].text_preview", "OpenMates audio playback is working.")]
    assert calls[0]["skip_field_names"] >= {"audio_base64", "aes_key", "aes_nonce", "vault_wrapped_aes_key"}
    assert result["results"][0]["audio_base64"] == "A" * 180
