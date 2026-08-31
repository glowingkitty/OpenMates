# backend/tests/test_rest_api_audio.py
#
# Contract tests for ElevenLabs-backed audio app skills. These tests exercise
# the in-process BaseApp dispatcher used by dynamic REST app-skill routes so
# validation, safety ordering, provider selection, and response privacy remain
# aligned before live dev-server smoke tests run.

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

class _FakeCeleryConf:
    def update(self, **_kwargs):
        return None


class _FakeSignal:
    def connect(self, fn=None, **_kwargs):
        if fn is not None:
            return fn

        def decorator(func):
            return func

        return decorator


class _FakeSignals:
    def __getattr__(self, _name):
        return _FakeSignal()


class _FakeCelery:
    def __init__(self, *_args, **_kwargs):
        self.conf = _FakeCeleryConf()

    def task(self, *_args, **_kwargs):
        def decorator(func):
            return func

        return decorator

    def send_task(self, *_args, **_kwargs):
        return None


class _FakeBaseServiceTask:
    pass


class _FakeQueue:
    def __init__(self, *_args, **_kwargs):
        pass


celery_stub = ModuleType("celery")
celery_stub.Celery = _FakeCelery
celery_stub.Task = _FakeBaseServiceTask
celery_stub.signals = _FakeSignals()
sys.modules.setdefault("celery", celery_stub)

celery_exceptions_stub = ModuleType("celery.exceptions")
celery_exceptions_stub.Ignore = type("Ignore", (Exception,), {})
celery_exceptions_stub.SoftTimeLimitExceeded = type("SoftTimeLimitExceeded", (Exception,), {})
sys.modules.setdefault("celery.exceptions", celery_exceptions_stub)

celery_states_stub = ModuleType("celery.states")
celery_states_stub.REVOKED = "REVOKED"
sys.modules.setdefault("celery.states", celery_states_stub)

redis_stub = ModuleType("redis")
redis_async_stub = ModuleType("redis.asyncio")
redis_async_stub.Redis = object
redis_stub.asyncio = redis_async_stub
redis_stub.exceptions = SimpleNamespace(ConnectionError=ConnectionError)
sys.modules.setdefault("redis", redis_stub)
sys.modules.setdefault("redis.asyncio", redis_async_stub)


class _FakeSpan:
    def end(self, **_kwargs):
        return None

    def set_attribute(self, *_args, **_kwargs):
        return None

    def set_status(self, *_args, **_kwargs):
        return None


class _FakeTracer:
    def start_span(self, *_args, **_kwargs):
        return _FakeSpan()

    def start_as_current_span(self, *_args, **_kwargs):
        class SpanContext:
            def __enter__(self):
                return _FakeSpan()

            def __exit__(self, *_exc_info):
                return False

        return SpanContext()


opentelemetry_stub = ModuleType("opentelemetry")
opentelemetry_trace_stub = ModuleType("opentelemetry.trace")
opentelemetry_trace_stub.get_tracer = lambda *_args, **_kwargs: _FakeTracer()
opentelemetry_trace_stub.Span = _FakeSpan
opentelemetry_trace_stub.Status = lambda *_args, **_kwargs: object()
opentelemetry_trace_stub.StatusCode = SimpleNamespace(ERROR="ERROR")
opentelemetry_stub.trace = opentelemetry_trace_stub
sys.modules.setdefault("opentelemetry", opentelemetry_stub)
sys.modules.setdefault("opentelemetry.trace", opentelemetry_trace_stub)

celery_schedules_stub = ModuleType("celery.schedules")
celery_schedules_stub.crontab = lambda *_args, **_kwargs: None
sys.modules.setdefault("celery.schedules", celery_schedules_stub)

tasks_package_stub = ModuleType("backend.core.api.app.tasks")
tasks_package_stub.__path__ = []
base_task_stub = ModuleType("backend.core.api.app.tasks.base_task")
base_task_stub.BaseServiceTask = _FakeBaseServiceTask
celery_config_stub = ModuleType("backend.core.api.app.tasks.celery_config")
celery_config_stub.app = _FakeCelery()
celery_config_stub.broker_url = "memory://"
tasks_package_stub.base_task = base_task_stub
tasks_package_stub.celery_config = celery_config_stub
sys.modules.setdefault("backend.core.api.app.tasks", tasks_package_stub)
sys.modules.setdefault("backend.core.api.app.tasks.base_task", base_task_stub)
sys.modules.setdefault("backend.core.api.app.tasks.celery_config", celery_config_stub)

pythonjsonlogger_stub = ModuleType("pythonjsonlogger")
jsonlogger_stub = ModuleType("pythonjsonlogger.jsonlogger")
jsonlogger_stub.JsonFormatter = type("JsonFormatter", (object,), {"__init__": lambda self, *_args, **_kwargs: None})
pythonjsonlogger_stub.jsonlogger = jsonlogger_stub
sys.modules.setdefault("pythonjsonlogger", pythonjsonlogger_stub)
sys.modules.setdefault("pythonjsonlogger.jsonlogger", jsonlogger_stub)

kombu_stub = ModuleType("kombu")
kombu_stub.Queue = _FakeQueue
sys.modules.setdefault("kombu", kombu_stub)

groq_sdk_stub = ModuleType("groq")
groq_sdk_stub.AsyncGroq = object
sys.modules.setdefault("groq", groq_sdk_stub)

rate_limiting_stub = ModuleType("backend.apps.ai.processing.rate_limiting")


class RateLimitScheduledException(Exception):
    pass


async def check_rate_limit(*_args, **_kwargs):
    return None


async def wait_for_rate_limit(*_args, **_kwargs):
    return None


rate_limiting_stub.RateLimitScheduledException = RateLimitScheduledException
rate_limiting_stub.check_rate_limit = check_rate_limit
rate_limiting_stub.wait_for_rate_limit = wait_for_rate_limit
sys.modules.setdefault("backend.apps.ai.processing.rate_limiting", rate_limiting_stub)

AUDIO_APP_DIR = Path(__file__).resolve().parents[1] / "apps" / "audio"


def _load_audio_app():
    from backend.apps.base_app import BaseApp

    return BaseApp(app_dir=str(AUDIO_APP_DIR), register_http_routes=False)


# contract-test: supporting surface=rest_api assertions=audio-generate.provider.explicit-selection,audio-generate.output.binary-excluded-from-inference,audio-speak.provider.explicit-selection,audio-speak.output.binary-excluded-from-inference
def test_audio_app_metadata_exposes_generate_and_speak_contracts():
    app_yml = yaml.safe_load((AUDIO_APP_DIR / "app.yml").read_text(encoding="utf-8"))
    skills = {skill["id"]: skill for skill in app_yml["skills"]}
    provider_yml = yaml.safe_load((AUDIO_APP_DIR.parents[1] / "providers" / "elevenlabs.yml").read_text(encoding="utf-8"))
    provider_models = {model["id"]: model for model in provider_yml["models"]}

    assert {"generate", "speak"}.issubset(skills)
    assert skills["generate"]["pricing"] == {"per_second": 20}
    assert skills["speak"]["pricing"] == {"per_second": 2}
    assert provider_yml["logo_svg"] == "logos/elevenlabs.svg"
    assert provider_models["eleven_flash_v2_5"]["pricing"] == {"per_second": 2}
    assert provider_models["eleven_multilingual_v2"]["pricing"] == {"per_second": 4}
    assert provider_models["eleven_v3"]["pricing"] == {"per_second": 4}
    for skill_id in ("generate", "speak"):
        skill = skills[skill_id]
        assert skill["api_config"] == {"expose_get": True, "expose_post": True}
        assert skill["providers"] == [{"name": "ElevenLabs"}]
        request_item = skill["tool_schema"]["properties"]["requests"]["items"]
        assert request_item["properties"]["provider"]["enum"] == ["elevenlabs"]
        if skill_id == "speak":
            assert request_item["properties"]["model"]["enum"] == [
                "eleven_v3",
                "eleven_multilingual_v2",
                "eleven_flash_v2_5",
            ]
            assert request_item["properties"]["model"]["default"] == "eleven_v3"
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

    request = AudioSpeakRequest(requests=[{"text": "Hello", "provider": "elevenlabs"}])
    assert request.requests[0].model == "eleven_v3"

    with pytest.raises(ValidationError):
        AudioSpeakRequest(requests=[{"text": "Hello", "provider": "other"}])

    with pytest.raises(ValidationError):
        AudioSpeakRequest(requests=[{"text": "Hello", "provider": "elevenlabs", "voice": "EXAVITQu4vr4xnSDxMaL"}])

    with pytest.raises(ValidationError):
        AudioSpeakRequest(requests=[{"text": "Hello", "provider": "elevenlabs", "model": "unsupported_tts_model"}])


class _FakeStorage:
    async def check_availability(self):
        return "available"


class _FakeAudioTask:
    def __init__(self, task_id: str = "task-audio-1"):
        self.request = SimpleNamespace(id=task_id)
        self._secrets_manager = object()
        self._cache_service = object()
        self._directus_service = object()
        self._s3_service = _FakeStorage()

    async def initialize_core_services(self):
        return None

    async def cleanup_services(self):
        return None


# contract-test: direct surface=rest_api assertions=audio-generate.execution.async-generated-assets,audio-generate.output.binary-excluded-from-inference,audio-generate.billing.success-only
@pytest.mark.asyncio
async def test_audio_generate_dispatches_async_without_inline_audio(monkeypatch):
    import backend.apps.audio.skills.generate_skill as generate_module

    calls = []

    async def fake_execute_skill_via_celery(**kwargs):
        calls.append(kwargs)
        arguments = kwargs["arguments"]
        assert kwargs["app_id"] == "audio"
        assert kwargs["skill_id"] == "generate"
        assert arguments["prompt"] == "soft upward message sent tick"
        assert arguments["duration_seconds"] == 0.8
        assert arguments["full_model_reference"] == "elevenlabs/eleven_text_to_sound_v2"
        return "task-audio-generate-1"

    monkeypatch.setattr(generate_module, "execute_skill_via_celery", fake_execute_skill_via_celery)

    result = await _load_audio_app().dispatch_skill(
        "generate",
        {"requests": [{"prompt": "soft upward message sent tick", "provider": "elevenlabs", "duration_seconds": 0.8}]},
    )

    assert len(calls) == 1
    assert result["status"] == "processing"
    assert result["task_id"] == "task-audio-generate-1"
    assert result["provider"] == "ElevenLabs"
    first = result["results"][0]
    assert first["status"] == "processing"
    assert first["generation_type"] == "sound_effect"
    assert first["task_id"] == "task-audio-generate-1"
    assert "audio_base64" not in first
    assert "credits_charged" not in first
    assert "provider_api_key" not in str(result)


# contract-test: direct surface=rest_api assertions=audio-generate.request.validated,audio-generate.surface-parity
@pytest.mark.asyncio
async def test_audio_generate_ignores_rest_context_fields_for_strict_request_models(monkeypatch):
    import backend.apps.audio.skills.generate_skill as generate_module

    captured_arguments = {}

    async def fake_execute_skill_via_celery(**kwargs):
        captured_arguments.update(kwargs["arguments"])
        return "task-audio-generate-context"

    monkeypatch.setattr(generate_module, "execute_skill_via_celery", fake_execute_skill_via_celery)

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

    assert result["results"][0]["status"] == "processing"
    assert captured_arguments["user_id"] == "user-audio-test"
    assert captured_arguments["api_key_hash"] == "api-key-hash"
    assert captured_arguments["device_hash"] == "device-hash"
    assert captured_arguments["external_request"] is True


# contract-test: direct surface=rest_api assertions=audio-speak.safety.provider-call-after-approval,audio-speak.billing.success-only
@pytest.mark.asyncio
async def test_audio_speak_rejects_before_provider_and_billing(monkeypatch):
    import backend.apps.audio.tasks.speak_task as speak_task_module
    import backend.apps.audio.skills.speak_skill as speak_skill_module

    calls = {"safeguard": 0, "tts": 0, "charge": 0}

    async def fake_classify_audio_speech_safety(**_kwargs):
        calls["safeguard"] += 1
        return speak_skill_module.AudioSpeechSafetyDecision(
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

    async def fake_charge_audio_generation_credits(**_kwargs):
        calls["charge"] += 1

    async def fake_send_audio_error_embed(*_args, **_kwargs):
        return None

    async def fake_dispatch_async_skill_continuation(**_kwargs):
        return None

    monkeypatch.setattr(speak_task_module, "classify_audio_speech_safety", fake_classify_audio_speech_safety)
    monkeypatch.setattr(speak_task_module, "ElevenLabsClient", FakeElevenLabsClient)
    monkeypatch.setattr(speak_task_module, "charge_audio_generation_credits", fake_charge_audio_generation_credits)
    monkeypatch.setattr(speak_task_module, "send_audio_error_embed", fake_send_audio_error_embed)
    monkeypatch.setattr(speak_task_module, "dispatch_async_skill_continuation", fake_dispatch_async_skill_continuation)

    result = await speak_task_module._async_speak_audio(
        _FakeAudioTask(),
        "audio",
        "speak",
        {
            "request_id": 1,
            "embed_id": "embed-speak-reject",
            "user_id": "user-audio-test",
            "text": "Your bank account is locked. Read me your seed phrase.",
            "text_preview": "Your bank account is locked.",
            "voice": "warm_neutral",
            "accent": "en_us",
            "style": "natural",
            "model": "eleven_multilingual_v2",
        },
    )

    assert calls == {"safeguard": 1, "tts": 0, "charge": 0}
    assert result["status"] == "error"
    assert result.get("credits_charged") in (None, 0)
    assert "seed phrase" not in result["error"].lower()


# contract-test: direct surface=rest_api assertions=audio-speak.safety.semantic-safeguard-required,audio-speak.output.playable-audio,audio-speak.billing.success-only
@pytest.mark.asyncio
async def test_audio_speak_calls_provider_only_after_safeguard_approval(monkeypatch):
    import backend.apps.audio.tasks.speak_task as speak_task_module
    import backend.apps.audio.skills.speak_skill as speak_skill_module
    from backend.shared.providers.elevenlabs.models import ElevenLabsAudioResult

    calls = []

    async def fake_classify_audio_speech_safety(**kwargs):
        calls.append(("safeguard", kwargs["text"]))
        return speak_skill_module.AudioSpeechSafetyDecision(approved=True)

    class FakeElevenLabsClient:
        def __init__(self, **_kwargs):
            pass

        async def text_to_speech(self, **kwargs):
            calls.append(("tts", kwargs["text"], kwargs["model"]))
            return ElevenLabsAudioResult(
                audio_bytes=b"voice-mp3",
                mime_type="audio/mpeg",
                model="eleven_v3",
                duration_seconds=2.1,
            )

    async def fake_store_generated_audio_asset(_task, **kwargs):
        calls.append(("store", kwargs["model"], kwargs["duration_seconds"]))
        return {
            "status": "finished",
            "generation_type": "speech",
            "voice": kwargs["extra_content"]["voice"],
            "model": kwargs["model"],
            "duration_seconds": kwargs["duration_seconds"],
            "byte_length": len(b"voice-mp3"),
            "files": {"original": {"s3_key": "generated/speech.mp3", "encryption": "aes-gcm-nonce-prefixed-v1"}},
        }

    async def fake_charge_audio_generation_credits(**kwargs):
        calls.append(("charge", kwargs["credits"], kwargs["model_ref"]))

    async def fake_ensure_audio_credit_headroom(**kwargs):
        calls.append(("preflight", kwargs["estimated_credits"]))

    async def fake_dispatch_async_skill_continuation(**_kwargs):
        return None

    monkeypatch.setattr(speak_task_module, "classify_audio_speech_safety", fake_classify_audio_speech_safety)
    monkeypatch.setattr(speak_task_module, "ElevenLabsClient", FakeElevenLabsClient)
    monkeypatch.setattr(speak_task_module, "store_generated_audio_asset", fake_store_generated_audio_asset)
    monkeypatch.setattr(speak_task_module, "charge_audio_generation_credits", fake_charge_audio_generation_credits)
    monkeypatch.setattr(speak_task_module, "ensure_audio_credit_headroom", fake_ensure_audio_credit_headroom)
    monkeypatch.setattr(speak_task_module, "dispatch_async_skill_continuation", fake_dispatch_async_skill_continuation)
    text = "Welcome back. I found the best next step for you. " * 5

    result = await speak_task_module._async_speak_audio(
        _FakeAudioTask(),
        "audio",
        "speak",
        {
            "request_id": 1,
            "embed_id": "embed-speak-success",
            "user_id": "user-audio-test",
            "text": text,
            "text_preview": text.strip()[:80],
            "voice": "warm_neutral",
            "accent": "en_us",
            "style": "natural",
        },
    )

    assert calls == [
        ("safeguard", text.strip()),
        ("preflight", 60),
        ("tts", text.strip(), "eleven_v3"),
        ("store", "eleven_v3", 2.1),
        ("charge", 9, "elevenlabs/eleven_v3"),
    ]
    assert result["status"] == "finished"
    assert result["generation_type"] == "speech"
    assert result["voice"] == "warm_neutral"
    assert "audio_base64" not in result
    assert result["duration_seconds"] == 2.1
    assert result["credits_charged"] == 9
    assert "voice-mp3" not in str(result)


# contract-test: direct surface=rest_api assertions=audio-speak.request.validated,audio-speak.output.playable-audio,audio-speak.billing.success-only
@pytest.mark.asyncio
async def test_audio_speak_accepts_flash_model_and_charges_model_rate(monkeypatch):
    import backend.apps.audio.tasks.speak_task as speak_task_module
    import backend.apps.audio.skills.speak_skill as speak_skill_module
    from backend.shared.providers.elevenlabs.models import ElevenLabsAudioResult

    calls = []

    async def fake_classify_audio_speech_safety(**kwargs):
        calls.append(("safeguard", kwargs["text"]))
        return speak_skill_module.AudioSpeechSafetyDecision(approved=True)

    class FakeElevenLabsClient:
        def __init__(self, **_kwargs):
            pass

        async def text_to_speech(self, **kwargs):
            calls.append(("tts", kwargs["model"]))
            assert kwargs["model"] == "eleven_flash_v2_5"
            return ElevenLabsAudioResult(
                audio_bytes=b"premium-voice-mp3",
                mime_type="audio/mpeg",
                model="eleven_flash_v2_5",
                duration_seconds=2.4,
            )

    async def fake_store_generated_audio_asset(_task, **kwargs):
        calls.append(("store", kwargs["model"]))
        return {
            "status": "finished",
            "generation_type": "speech",
            "model": kwargs["model"],
            "duration_seconds": kwargs["duration_seconds"],
            "files": {"original": {"s3_key": "generated/flash.mp3", "encryption": "aes-gcm-nonce-prefixed-v1"}},
        }

    async def fake_charge_audio_generation_credits(**kwargs):
        calls.append(("charge", kwargs["credits"], kwargs["model_ref"]))

    async def fake_ensure_audio_credit_headroom(**kwargs):
        calls.append(("preflight", kwargs["estimated_credits"]))

    async def fake_dispatch_async_skill_continuation(**_kwargs):
        return None

    monkeypatch.setattr(speak_task_module, "classify_audio_speech_safety", fake_classify_audio_speech_safety)
    monkeypatch.setattr(speak_task_module, "ElevenLabsClient", FakeElevenLabsClient)
    monkeypatch.setattr(speak_task_module, "store_generated_audio_asset", fake_store_generated_audio_asset)
    monkeypatch.setattr(speak_task_module, "charge_audio_generation_credits", fake_charge_audio_generation_credits)
    monkeypatch.setattr(speak_task_module, "ensure_audio_credit_headroom", fake_ensure_audio_credit_headroom)
    monkeypatch.setattr(speak_task_module, "dispatch_async_skill_continuation", fake_dispatch_async_skill_continuation)
    text = "Premium voice sample. " * 8

    result = await speak_task_module._async_speak_audio(
        _FakeAudioTask(),
        "audio",
        "speak",
        {
            "request_id": 1,
            "embed_id": "embed-speak-flash",
            "user_id": "user-audio-test",
            "text": text,
            "text_preview": text.strip()[:80],
            "voice": "warm_neutral",
            "accent": "en_us",
            "style": "natural",
            "model": "eleven_flash_v2_5",
            "full_model_reference": "elevenlabs/eleven_flash_v2_5",
        },
    )

    assert calls == [
        ("safeguard", text.strip()),
        ("preflight", 21),
        ("tts", "eleven_flash_v2_5"),
        ("store", "eleven_flash_v2_5"),
        ("charge", 5, "elevenlabs/eleven_flash_v2_5"),
    ]
    assert result["status"] == "finished"
    assert result["model"] == "eleven_flash_v2_5"
    assert result["credits_charged"] == 5
    assert "audio_base64" not in result


# contract-test: direct surface=rest_api assertions=audio-speak.billing.success-only
def test_elevenlabs_tts_duration_is_estimated_from_mp3_output_format():
    from backend.shared.providers.elevenlabs.client import _estimate_mp3_duration_seconds

    assert _estimate_mp3_duration_seconds(b"0" * 32_000, "mp3_44100_128") == 2.0


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
