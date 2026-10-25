"""Transient audio never fans out beyond the authenticated live-call owner."""

import ast
import asyncio
import base64
import hashlib
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.shared.python_utils.assistant_speech_audio import (
    MAX_AUDIO_CHUNK_BYTES,
    route_assistant_speech_audio,
    validate_assistant_speech_audio_event,
    validate_assistant_speech_sealed_segments,
)

CHAT = "11111111-1111-4111-8111-111111111111"
MESSAGE = hashlib.sha256(b"canonical-assistant-message").hexdigest()
ATTEMPT = "33333333-3333-4333-8333-333333333333"
CALL = "a" * 32
SEGMENT = "b" * 64
OWNER = "authenticated-owner"
CHANNEL = f"chat_stream::{CHAT}"


def event(phase="chunk", **updates):
    payload = {
        "chat_id": CHAT, "message_id": MESSAGE, "voice_call_id": CALL,
        "segment_id": SEGMENT, "sequence": 0, "kind": "voice_prose_clause",
        "source_version": 1, "execution_version": 2, "attempt_id": ATTEMPT,
        "phase": phase, "chunk_index": 0, "mime_type": "audio/mpeg",
    }
    if phase == "chunk":
        payload["audio_data"] = base64.b64encode(b"public-test-audio").decode()
    payload.update(updates)
    return {"type": "assistant_speech_audio", "chat_id": CHAT, "message_id": MESSAGE,
            "user_id_hash": hashlib.sha256(OWNER.encode()).hexdigest(), "payload": payload}


def sealed_payload():
    return {"status": "sealed", "voice_call_id": CALL, "source_version": 1,
            "segments": [{"segment_id": SEGMENT, "sequence": 0, "kind": "voice_prose_clause", "source_version": 1}]}


@pytest.mark.parametrize("fault", ["private_field", "duplicate", "unordered", "source", "boolean_source", "kind", "id", "call", "oversized", "private_error"])
# contract-test: supporting surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.access.first-party-owner-scoped
def test_sealed_membership_rejects_private_or_ambiguous_nested_rows(fault):
    payload = sealed_payload()
    row = payload["segments"][0]
    if fault == "private_field":
        row["text"] = "must never forward"
    elif fault == "duplicate":
        payload["segments"].append(dict(row))
    elif fault == "unordered":
        row["sequence"] = 2
        payload["segments"].append({**row, "segment_id": "c" * 64, "sequence": 1})
    elif fault == "source":
        row["source_version"] = 2
    elif fault == "boolean_source":
        row["source_version"] = True
    elif fault == "kind":
        row["kind"] = "waiting_confirmation"
    elif fault == "id":
        row["segment_id"] = "../segment"
    elif fault == "call":
        payload["voice_call_id"] = "invalid"
    elif fault == "private_error":
        payload["error"] = "PRIVATE-HANDOFF-EXCEPTION"
    else:
        payload["segments"] = [row] * 1025
    with pytest.raises(ValueError):
        validate_assistant_speech_sealed_segments(payload)


# contract-test: supporting surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.access.first-party-owner-scoped
def test_sealed_membership_allows_exact_ordered_and_empty_membership():
    payload = sealed_payload()
    assert validate_assistant_speech_sealed_segments(payload) == payload["segments"]
    payload["segments"] = []
    assert validate_assistant_speech_sealed_segments(payload) == []


class Manager:
    def __init__(self, *, owning=True, duplicate=False):
        self.active_connections = {
            OWNER: {
                "owning-device": SimpleNamespace(scope={"voice_call_session_hash": "owning-session" if owning else "wrong-session"}),
                "other-device-same-active-chat": SimpleNamespace(scope={"voice_call_session_hash": "other-session"}),
                "unscoped-device": SimpleNamespace(scope={}),
            },
            "other-user": {"same-chat": SimpleNamespace(scope={"voice_call_session_hash": "owning-session"})},
        }
        if duplicate:
            self.active_connections[OWNER]["ambiguous-owner"] = SimpleNamespace(scope={"voice_call_session_hash": "owning-session"})
        self.send_personal_message = AsyncMock()

    def get_connections_for_user(self, user):
        return self.active_connections.get(user, {})

    def get_active_chat(self, *_args):
        raise AssertionError("Transient audio must never consult visible-chat scope")


@pytest.mark.parametrize("phase,index", [("start", 0), ("chunk", 0), ("chunk", 4095), ("end", 4096), ("error", 0)])
@pytest.mark.parametrize("kind,sequence", [("voice_prose_clause", 0), ("waiting_confirmation", -1)])
# contract-test: supporting surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.access.first-party-owner-scoped
def test_valid_payload_phases_and_bounds(phase, index, kind, sequence):
    original = event(phase, chunk_index=index, kind=kind, sequence=sequence)
    assert validate_assistant_speech_audio_event(original, channel=CHANNEL) == original["payload"]


@pytest.mark.parametrize("message_id", [MESSAGE, "22222222-2222-4222-8222-222222222222"])
# contract-test: supporting surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.access.first-party-owner-scoped
def test_canonical_assistant_hash_and_uuid_message_identities(message_id):
    original = event(message_id=message_id)
    original["message_id"] = message_id
    assert validate_assistant_speech_audio_event(original, channel=CHANNEL)["message_id"] == message_id


@pytest.mark.parametrize("message_id", ["a" * 63, "a" * 65, "g" * 64, "../message", True, None])
# contract-test: supporting surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.access.first-party-owner-scoped
def test_invalid_message_identity_rejected_even_when_envelope_matches(message_id):
    original = event(message_id=message_id)
    original["message_id"] = message_id
    with pytest.raises(ValueError, match="invalid_envelope_identity"):
        validate_assistant_speech_audio_event(original, channel=CHANNEL)


@pytest.mark.parametrize("kind,sequence", [
    ("waiting_confirmation", 0), ("waiting_confirmation", 1), ("waiting_confirmation", -2),
    ("waiting_confirmation", True), ("waiting_confirmation", False),
    ("voice_prose_clause", -1), ("app_use_announcement", 0), ("app_use_announcement", -1),
    ("prose_paragraph", 0),
])
# contract-test: supporting surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.access.first-party-owner-scoped
def test_kind_sequence_pairs_are_exact(kind, sequence):
    with pytest.raises(ValueError):
        validate_assistant_speech_audio_event(event(kind=kind, sequence=sequence), channel=CHANNEL)


@pytest.mark.parametrize("field,value", [
    ("sequence", True), ("sequence", -1), ("sequence", 65536),
    ("source_version", False), ("source_version", 0), ("execution_version", "1"),
    ("execution_version", 1 << 53), ("chunk_index", True), ("chunk_index", 4096),
    ("chunk_index", -1), ("chat_id", MESSAGE), ("message_id", CHAT),
    ("voice_call_id", "a" * 31), ("voice_call_id", "../call"),
    ("segment_id", "bad segment"), ("segment_id", "x" * 10000),
    ("attempt_id", "not-a-uuid"), ("kind", "waiting_confirmation"),
    ("mime_type", "audio/wav"), ("phase", "replay"),
    ("audio_data", "!bad!"), ("audio_data", ""), ("audio_data", "AB=="),
    ("audio_data", base64.b64encode(b"x" * (MAX_AUDIO_CHUNK_BYTES + 1)).decode()),
])
# contract-test: supporting surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.access.first-party-owner-scoped
def test_malformed_audio_fields_rejected(field, value):
    with pytest.raises(ValueError):
        validate_assistant_speech_audio_event(event(**{field: value}), channel=CHANNEL)


@pytest.mark.parametrize("phase", ["start", "end", "error"])
# contract-test: supporting surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.access.first-party-owner-scoped
def test_non_chunk_events_cannot_carry_audio_or_private_fields(phase):
    for extra in ({"audio_data": "eA=="}, {"text": "must not forward"}, {"key": "must not forward"}):
        with pytest.raises(ValueError, match="invalid_payload_fields"):
            validate_assistant_speech_audio_event(event(phase, **extra), channel=CHANNEL)


# contract-test: supporting surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.access.first-party-owner-scoped
def test_envelope_scope_channel_and_payload_fields_are_exact():
    cases = [event(secret="must not forward"), event()]
    cases[1]["external_request"] = True
    bad_hash = event()
    bad_hash["user_id_hash"] = "wrong"
    cases.append(bad_hash)
    bad_identity = event()
    bad_identity["chat_id"] = "../chat"
    cases.append(bad_identity)
    for malformed in cases:
        with pytest.raises(ValueError):
            validate_assistant_speech_audio_event(malformed, channel=CHANNEL)
    with pytest.raises(ValueError, match="channel_scope_mismatch"):
        validate_assistant_speech_audio_event(event(), channel=f"chat_stream::{MESSAGE}")
    with pytest.raises(ValueError, match="invalid_chunk_index"):
        validate_assistant_speech_audio_event(event("start", chunk_index=1), channel=CHANNEL)


# contract-test: supporting surface=gui.web assertions=assistant-speech.access.first-party-owner-scoped,video-call.audio.single-owner,video-call.privacy
@pytest.mark.parametrize("kind,sequence", [("voice_prose_clause", 0), ("waiting_confirmation", -1)])
async def test_live_audio_routes_only_to_exact_call_owner_without_active_chat_lookup(kind, sequence):
    manager = Manager()
    lookup = AsyncMock(return_value="owning-session")
    original = event(kind=kind, sequence=sequence)
    outcome = await route_assistant_speech_audio(envelope=original, channel=CHANNEL, manager=manager, cache=object(), session_lookup=lookup)
    assert outcome == "delivered"
    lookup.assert_awaited_once()
    assert lookup.await_args.kwargs == {"user_id": OWNER, "chat_id": CHAT, "call_id": CALL}
    manager.send_personal_message.assert_awaited_once_with(
        message={"type": "assistant_speech_audio", "payload": original["payload"]},
        user_id=OWNER, device_fingerprint_hash="owning-device",
    )


@pytest.mark.parametrize("scenario,expected", [
    ("wrong_device", "owner_connection_unavailable"),
    ("duplicate_connection", "owner_connection_unavailable"),
    ("ended_call", "inactive_call"), ("cache_failure", "authority_unavailable"),
    ("missing_owner", "owner_unavailable"), ("malformed", "invalid_event"),
])
@pytest.mark.parametrize("kind,sequence", [("voice_prose_clause", 0), ("waiting_confirmation", -1)])
# contract-test: supporting surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.access.first-party-owner-scoped
async def test_audio_authority_fails_closed(scenario, expected, kind, sequence):
    manager = Manager(owning=scenario != "wrong_device", duplicate=scenario == "duplicate_connection")
    lookup = AsyncMock(return_value=None if scenario == "ended_call" else "owning-session")
    if scenario == "cache_failure":
        lookup.side_effect = RuntimeError("private authority details must not escape")
    if scenario == "missing_owner":
        del manager.active_connections[OWNER]
    original = event(kind=kind, sequence=sequence, **({"secret": "private"} if scenario == "malformed" else {}))
    assert await route_assistant_speech_audio(envelope=original, channel=CHANNEL, manager=manager,
                                            cache=object(), session_lookup=lookup) == expected
    manager.send_personal_message.assert_not_awaited()
    if scenario == "malformed":
        lookup.assert_not_awaited()


@pytest.mark.parametrize("row", [
    [OWNER, "owning-session", CHAT, "finalizing"],
    [OWNER, "owning-session", CHAT, "ended"],
    ["other-user", "owning-session", CHAT, "active"],
    [OWNER, "owning-session", MESSAGE, "active"],
    [None, None, None, None],
])
# contract-test: supporting surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.access.first-party-owner-scoped
async def test_real_registry_missing_ended_or_wrong_owner_chat_cannot_route(row):
    class Redis:
        async def hmget(self, *_args):
            return row

    class Cache:
        @property
        async def client(self):
            return Redis()

    manager = Manager()
    assert await route_assistant_speech_audio(envelope=event(), channel=CHANNEL,
                                            manager=manager, cache=Cache()) == "inactive_call"
    manager.send_personal_message.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.access.first-party-owner-scoped
async def test_real_listener_branch_survives_malformed_audio_then_routes_valid_owner(caplog):
    """Execute the actual listener AST, avoiding unrelated API dependency imports."""
    source = Path(__file__).parents[1] / "core/api/app/routes/websockets.py"
    tree = ast.parse(source.read_text())
    listener = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "listen_for_ai_chat_streams")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), listener], type_ignores=[])
    manager = Manager()

    class Redis:
        async def hmget(self, key, *_fields):
            assert key == f"voice:call:{CALL}"
            return [OWNER, "owning-session", CHAT, "active"]

    class Cache:
        @property
        async def client(self):
            return Redis()

        async def subscribe_to_channel(self, _channel):
            yield {"channel": CHANNEL, "data": event(audio_data="invalid private bytes")}
            yield {"channel": CHANNEL, "data": event()}

    logger = logging.getLogger("speech-audio-listener-test")
    namespace = {"logger": logger, "manager": manager, "_safe_payload_summary": lambda _payload: "safe_metadata"}
    exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
    with caplog.at_level(logging.DEBUG, logger=logger.name):
        await namespace["listen_for_ai_chat_streams"](SimpleNamespace(state=SimpleNamespace(cache_service=Cache())))
    manager.send_personal_message.assert_awaited_once()
    assert manager.send_personal_message.await_args.kwargs["device_fingerprint_hash"] == "owning-device"
    assert "category=invalid_event" in caplog.text
    assert "private bytes" not in caplog.text
    assert event()["payload"]["audio_data"] not in caplog.text


# contract-test: supporting surface=rest_api assertions=assistant-speech.playback.live-call-streaming,assistant-speech.access.first-party-owner-scoped
async def test_real_listener_routes_only_valid_content_free_live_seal():
    source = Path(__file__).parents[1] / "core/api/app/routes/websockets.py"
    tree = ast.parse(source.read_text())
    listener = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "listen_for_ai_chat_streams")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), listener], type_ignores=[])
    manager = Manager()
    valid = {**event("start"), "type": "assistant_speech_status", "payload": sealed_payload()}
    invalid = {**valid, "payload": {**sealed_payload(), "segments": [{**sealed_payload()["segments"][0], "text": "PRIVATE-SEAL-CANARY"}]}}

    class Redis:
        async def hmget(self, key, *_fields):
            assert key == f"voice:call:{CALL}"
            return [OWNER, "owning-session", CHAT, "active"]

    class Cache:
        @property
        async def client(self):
            return Redis()

        async def subscribe_to_channel(self, _channel):
            for payload in (invalid, valid):
                yield {"channel": CHANNEL, "data": payload}

    namespace = {"logger": logging.getLogger("speech-seal-listener-test"), "manager": manager,
                 "hashlib": hashlib, "asyncio": asyncio,
                 "_safe_payload_summary": lambda _payload: "safe_metadata"}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.startswith("SAFE_ASSISTANT_SPEECH_"):
                    namespace[target.id] = ast.literal_eval(node.value)
    exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
    await namespace["listen_for_ai_chat_streams"](SimpleNamespace(state=SimpleNamespace(cache_service=Cache())))
    manager.send_personal_message.assert_awaited_once_with(
        message={"type": "assistant_speech_status", "payload": {"chat_id": CHAT, "message_id": MESSAGE, **sealed_payload()}},
        user_id=OWNER, device_fingerprint_hash="owning-device",
    )

# contract-test: supporting surface=rest_api assertions=assistant-speech.playback.live-call-streaming,video-call.privacy
def test_continuous_turn_alignment_is_bounded_text_free_and_separate_from_finite_clauses():
    timing = {"segment_id": "c" * 64, "sequence": 0, "start_ms": 0, "end_ms": 1000}
    envelope = event("alignment", kind="voice_prose_turn", clause_timings=[timing])
    assert validate_assistant_speech_audio_event(envelope, channel=CHANNEL)["clause_timings"] == [timing]
    for changes in [
        {"kind": "voice_prose_clause"},
        {"sequence": 1},
        {"clause_timings": [{**timing, "text": "private"}]},
        {"clause_timings": [{**timing, "end_ms": 600001}]},
        {"clause_timings": [timing, {**timing, "segment_id": "d" * 64, "sequence": 1, "start_ms": 500}]},
        {"clause_timings": [{**timing, "start_ms": False}]},
    ]:
        with pytest.raises(ValueError):
            validate_assistant_speech_audio_event({**envelope, "payload": {**envelope["payload"], **changes}}, channel=CHANNEL)
    assert validate_assistant_speech_audio_event(event("start", kind="voice_prose_turn"), channel=CHANNEL)["kind"] == "voice_prose_turn"


# contract-test: supporting surface=rest_api assertions=assistant-speech.playback.live-call-streaming,video-call.privacy
def test_continuous_turn_seal_accepts_only_content_free_track_identity():
    payload = {**sealed_payload(), "turn_track_id": "d" * 64}
    assert validate_assistant_speech_sealed_segments(payload) == payload["segments"]
    for track in [None, "private text", {}, 1]:
        with pytest.raises(ValueError):
            validate_assistant_speech_sealed_segments({**payload, "turn_track_id": track})
