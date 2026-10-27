"""Explicit Speak creates its own cache after transient live-call narration."""
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.apps.ai.assistant_speech import streaming
from backend.apps.ai.assistant_speech.projection import project_final_voice_clauses
from backend.apps.audio.assistant_speech.persistence import manifest_id_for
from backend.core.api.app.routes.handlers.websocket_handlers.assistant_speech_handler import handle_assistant_speech_event


SOURCE = "The first answer gives a useful overview.\n\nThe second answer adds a practical example."
CHAT = "11111111-1111-4111-8111-111111111111"
MESSAGE = "22222222-2222-4222-8222-222222222222"
CALL = "c" * 32
OWNER = "owner"


def segment_identity(sequence, source_hash, *, live=False):
    identity = f"{CHAT}:{MESSAGE}:3:{sequence}:{source_hash}"
    if live:
        identity += f":voice-call:{CALL}"
    return hashlib.sha256(identity.encode()).hexdigest()


@pytest.fixture(params=[("sophia", 2), ("scarlett", 3)], ids=["historical-mistral-v2", "eleven-call-v3"])
def manual_speak(monkeypatch, request):
    from backend.apps.audio.tasks import common
    from backend.core.api.app.tasks import celery_config

    monkeypatch.setattr(streaming, "_token_secret", lambda: b"test-only-source-hmac-secret")
    voice_key, live_voice_version = request.param
    clauses = project_final_voice_clauses(SOURCE)
    assert len(clauses) == 2
    live_manifest = manifest_id_for(chat_id=CHAT, assistant_message_id=MESSAGE, source_version=3,
        voice_key=voice_key, voice_version=live_voice_version, voice_call_id=CALL)
    normal_manifest = manifest_id_for(chat_id=CHAT, assistant_message_id=MESSAGE, source_version=3,
        voice_key=voice_key, voice_version=2)
    rows = {"assistant_speech_manifests": [{"id": "live-manifest", "manifest_id": live_manifest,
        "user_id": OWNER, "chat_id": CHAT, "assistant_message_id": MESSAGE, "sealed": True,
        "execution_version": 3, "status": "ready"}], "assistant_speech_segments": []}
    for sequence, text in enumerate(clauses):
        source_hash = streaming._speech_source_identity(text)
        rows["assistant_speech_segments"].append({
            "id": f"live-row-{sequence}", "user_id": OWNER, "chat_id": CHAT, "assistant_message_id": MESSAGE,
            "manifest_id": live_manifest, "segment_id": segment_identity(sequence, source_hash, live=True),
            "sequence": sequence, "source_version": 3, "source_hash": source_hash,
            "kind": "voice_prose_clause", "status": "ready", "billable_character_count": len(text),
            "voice_profile_key": voice_key, "voice_profile_version": live_voice_version, "execution_version": 5,
        })
    original_live = [dict(row) for row in rows["assistant_speech_segments"]]
    timeline, queries, sent = [], [], []
    class Directus:
        chat = SimpleNamespace(check_chat_ownership=AsyncMock(return_value=True))
        async def get_items(self, collection, *, params, no_cache):
            assert no_cache is True
            queries.append((collection, dict(params)))
            if collection == "messages":
                assert params["filter[chat_id][_eq]"] == CHAT
                assert params["filter[client_message_id][_eq]"] == MESSAGE
                return [{"role": "assistant"}]
            candidates = list(rows[collection])
            for key, value in params.items():
                if key.startswith("filter["):
                    assert key.endswith(("][_eq]", "][_neq]")), key
                    field, operator = key[len("filter["):-1].split("][", 1)
                    candidates = [row for row in candidates if (row.get(field) == value) == (operator == "_eq")]
            if params.get("sort"):
                candidates.sort(key=lambda row: row[params["sort"]])
            limit = int(params.get("limit", len(candidates)))
            return [dict(row) for row in (candidates[:limit] if limit != -1 else candidates)]
        async def create_item(self, collection, record):
            identity = "manifest_id" if collection == "assistant_speech_manifests" else "segment_id"
            if any(row[identity] == record[identity] for row in rows[collection]):
                return False, "duplicate"
            timeline.append("persist-manual")
            row = {"id": f"{collection}-{len(rows[collection])}", **record}
            rows[collection].append(row)
            return row, None
        async def update_item_if_version(self, collection, row_id, patch, version, *, version_field, extra_filters):
            row = next(row for row in rows[collection] if row["id"] == row_id)
            if row.get(version_field) != version or any(row.get(key) != value for key, value in extra_filters.items()):
                return None
            row.update(patch)
            return dict(row)
    class Redis:
        async def incrby(self, _key, amount):
            timeline.append("rate")
            return amount
        async def expire(self, *_args):
            return True
    class Cache:
        @property
        def client(self):
            async def connected():
                return Redis()
            return connected()
        async def get_user_vault_key_id(self, user_id):
            assert user_id == OWNER
            return "owner-vault-key"
    class Manager:
        async def send_personal_message(self, message, user_id, device):
            assert (user_id, device) == (OWNER, "device")
            sent.append(message["payload"])
    async def credits(**kwargs):
        timeline.append("credits")
        assert kwargs["user_id"] == OWNER
    budget = AsyncMock(side_effect=credits)
    monkeypatch.setattr(common, "ensure_audio_credit_headroom", budget)
    dispatch = Mock()
    monkeypatch.setattr(celery_config.app, "send_task", dispatch)
    async def send(*, action="request", segments=None, source=SOURCE):
        await handle_assistant_speech_event(manager=Manager(), directus_service=Directus(), cache_service=Cache(),
            user_id=OWNER, device_fingerprint_hash="device", payload={
                "action": action, "chat_id": CHAT, "assistant_message_id": MESSAGE, "source_markdown": source,
                "defer_after_first": action == "request",
                "segments": segments or [{"source_version": 3, "sequence": 0, "kind": "voice_prose_clause",
                    "source_hash": "client-forgery", "speakable_text": "untrusted client text",
                    "voice_profile_key": "client-override", "voice_profile_version": 999,
                    "_verified_voice_source": "client-marker"}],
            })
        return sent[-1]
    return SimpleNamespace(rows=rows, clauses=clauses, voice_key=voice_key,
        live_manifest=live_manifest, normal_manifest=normal_manifest,
        original_live=original_live, timeline=timeline, queries=queries, sent=sent, budget=budget, dispatch=dispatch, send=send)


def generation_calls(case):
    return [call.kwargs["kwargs"]["arguments"] for call in case.dispatch.call_args_list
            if call.args[0] == "apps.audio.tasks.assistant_speech_segment"]


# contract-test: direct surface=rest_api assertions=assistant-speech.execution.first-segment-progressive,assistant-speech.on-demand.generate-missing-only,assistant-speech.privacy.transient-plaintext-encrypted-audio
async def test_explicit_speak_after_live_call_creates_separate_cache_then_reuses_ready_manual_asset(manual_speak):
    case = manual_speak
    response = await case.send()
    assert response["status"] == "accepted"
    manual_rows = [row for row in case.rows["assistant_speech_segments"] if row["manifest_id"] == case.normal_manifest]
    assert len(manual_rows) == 2 and case.normal_manifest != case.live_manifest
    assert len(generation_calls(case)) == 1
    generated = generation_calls(case)[0]
    assert "voice_call_id" not in generated
    assert generated["voice_profile_key"] == case.voice_key and generated["voice_profile_version"] == 2
    from backend.apps.audio.assistant_speech.voice_profiles import resolve_assistant_voice_profile
    assert resolve_assistant_voice_profile(generated["voice_profile_key"],
                                          version=generated["voice_profile_version"]).provider == "mistral"
    assert all(row["voice_profile_key"] == case.voice_key and row["voice_profile_version"] == 2
               for row in manual_rows)
    assert generated["speakable_text"] == case.clauses[0] and generated["kind"] == "voice_prose_clause"
    assert generated["segment_id"] == segment_identity(0, streaming._speech_source_identity(case.clauses[0]))
    assert generated["segment_id"] != case.original_live[0]["segment_id"]
    assert case.timeline.index("rate") < case.timeline.index("persist-manual")
    assert case.timeline.index("credits") < case.timeline.index("persist-manual")
    assert [row for row in case.rows["assistant_speech_segments"] if row["manifest_id"] == case.live_manifest] == case.original_live
    assert "speakable_text" not in repr(case.rows) and SOURCE not in repr(case.sent)
    manual_rows[0].update(status="ready", generated_asset_id="33333333-3333-4333-8333-333333333333", duration_seconds=1.3)
    repeated = await case.send()
    assert repeated["status"] == "accepted"
    ready = next(segment for segment in repeated["segments"] if segment["sequence"] == 0)
    assert ready["generated_asset_id"] == manual_rows[0]["generated_asset_id"] and ready["status"] == "ready"
    assert len(generation_calls(case)) == 1


# contract-test: direct surface=rest_api assertions=assistant-speech.on-demand.generate-missing-only,assistant-speech.access.first-party-owner-scoped,assistant-speech.segmentation.immutable-source
async def test_later_clause_generation_accepts_only_registered_manual_identity(manual_speak):
    case = manual_speak
    assert (await case.send())["status"] == "accepted"
    later = next(row for row in case.rows["assistant_speech_segments"]
        if row["manifest_id"] == case.normal_manifest and row["sequence"] == 1)
    response = await case.send(action="generate", segments=[{
        "segment_id": later["segment_id"], "source_version": 3, "sequence": 1, "kind": "voice_prose_clause",
        "source_hash": "client-forgery", "voice_profile_key": "client-override", "voice_profile_version": 999,
    }])
    assert response["status"] == "accepted"
    assert len(generation_calls(case)) == 2
    generated = generation_calls(case)[1]
    assert generated["segment_id"] == later["segment_id"] and generated["speakable_text"] == case.clauses[1]
    assert generated["voice_profile_key"] == case.voice_key and generated["voice_profile_version"] == 2
    assert "voice_call_id" not in generated


# contract-test: direct surface=rest_api assertions=assistant-speech.access.first-party-owner-scoped,assistant-speech.segmentation.immutable-source
@pytest.mark.parametrize("tamper", ["live-id", "unknown-id", "markdown", "hmac"])
async def test_manual_speak_rejects_live_or_unknown_ids_and_tampered_source_before_dispatch(manual_speak, tamper):
    case = manual_speak
    segment_id = case.original_live[0]["segment_id"] if tamper == "live-id" else "d" * 64
    action = "generate" if tamper in {"live-id", "unknown-id"} else "request"
    source = SOURCE.replace("useful", "tampered") if tamper == "markdown" else SOURCE
    if tamper == "hmac":
        case.rows["assistant_speech_segments"][0]["source_hash"] = "e" * 64
    response = await case.send(action=action, source=source, segments=[{
        "segment_id": segment_id, "source_version": 3, "sequence": 0, "kind": "voice_prose_clause",
    }])
    assert response == {"status": "error", "error": "speech_source_no_longer_current"}
    assert not generation_calls(case)
    case.budget.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=assistant-speech.on-demand.generate-missing-only,assistant-speech.segmentation.immutable-source
@pytest.mark.parametrize("live_version", [2, 3])
async def test_registered_call_voice_profile_resolves_to_supported_mistral_for_manual_request_and_generate(monkeypatch, live_version):
    from backend.apps.audio.assistant_speech.voice_profiles import (
        ASSISTANT_VOICE_PROVIDER_IDS, MISTRAL_VOICE_PROVIDER_IDS, resolve_assistant_voice_profile,
    )
    from backend.core.api.app.routes.handlers.websocket_handlers.assistant_speech_handler import resolve_registered_voice_segments

    assert set(ASSISTANT_VOICE_PROVIDER_IDS) <= set(MISTRAL_VOICE_PROVIDER_IDS)
    monkeypatch.setattr(streaming, "_token_secret", lambda: b"test-only-source-hmac-secret")
    clauses = project_final_voice_clauses(SOURCE)
    source_hash = streaming._speech_source_identity(clauses[0])
    row = {"sequence": 0, "source_version": 3, "source_hash": source_hash,
           "kind": "voice_prose_clause", "status": "ready", "voice_profile_key": "scarlett",
           "voice_profile_version": live_version}
    directus = SimpleNamespace(get_items=AsyncMock(return_value=[row]))
    resolved = await resolve_registered_voice_segments(directus, user_id=OWNER, chat_id=CHAT,
        assistant_message_id=MESSAGE, segments=[{"source_version": 3}], source_markdown=SOURCE, action="request")
    assert resolved[0]["voice_profile_key"] == "scarlett"
    assert resolved[0]["voice_profile_version"] == 2
    assert resolve_assistant_voice_profile("scarlett", version=resolved[0]["voice_profile_version"]).provider == "mistral"
    generated = await resolve_registered_voice_segments(directus, user_id=OWNER, chat_id=CHAT,
        assistant_message_id=MESSAGE, segments=[{"source_version": 3, "segment_id": resolved[0]["segment_id"],
        "voice_profile_key": "client-override", "voice_profile_version": 999}], source_markdown=SOURCE, action="generate")
    assert generated == resolved
    assert row["voice_profile_version"] == live_version
