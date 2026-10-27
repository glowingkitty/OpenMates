"""Pure continuous-turn orchestration tests; no live provider or product E2E."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.audio.assistant_speech.realtime_turn import (
    MAX_TURN_CHARACTERS, RealtimeSpeechTurn, RealtimeTurnUnavailable,
)
from backend.apps.audio.assistant_speech.voice_profiles import resolve_assistant_voice_profile
from backend.apps.audio.pricing import (
    ASSISTANT_RESPONSE_SPEECH_MODEL, ELEVEN_V4_TURBO_SPEECH_MODEL,
    calculate_assistant_response_speech_credits,
)


class Provider:
    def __init__(self):
        self.events = asyncio.Queue()
        self.open_count = self.cancel_count = self.submitted_characters = 0
        self.inputs = []
        self.finished = False

    async def open(self):
        self.open_count += 1

    async def append_text(self, text):
        self.inputs.append(text)
        self.submitted_characters += len(text)
        self.events.put_nowait(SimpleNamespace(audio_bytes=b"mp3-chunk", alignment=None, final=False))

    async def flush(self):
        return None

    async def finish_input(self):
        self.finished = True
        self.events.put_nowait(SimpleNamespace(audio_bytes=b"", alignment=None, final=True))

    async def cancel(self):
        self.cancel_count += 1

    async def audio_events(self):
        while True:
            event = await self.events.get()
            yield event
            if event.final:
                return


def make_turn(provider=None, *, safety=True, active=None, publish=None, seconds=2):
    provider = provider or Provider()
    events = []
    first_audio = asyncio.Event()

    async def publish_event(channel, event):
        events.append(event)
        if event["payload"]["phase"] == "chunk":
            first_audio.set()
        return True

    finalize = AsyncMock()
    credits = AsyncMock()
    owner = RealtimeSpeechTurn(
        context={"chat_id": "chat", "message_id": "message", "voice_call_id": "call",
                 "segment_id": "track", "sequence": 0, "kind": "voice_prose_turn",
                 "source_version": 1, "user_id_hash": "owner"},
        provider_factory=lambda: provider, prepare=AsyncMock(return_value=3),
        ensure_active=active or AsyncMock(), safety_check=AsyncMock(return_value=safety),
        credit_check=credits, publish_event=publish or publish_event, finalize=finalize, max_seconds=seconds,
    )
    return owner, provider, events, first_audio, finalize, credits


def span(sequence, text):
    return {"segment_id": f"clause-{sequence}", "sequence": sequence, "speakable_text": text}


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response,video-call.chat.ethics
async def test_one_open_session_forwards_audio_before_later_input_and_final_answer():
    owner, provider, events, first, finalize, credits = make_turn()
    await owner.enqueue(span(0, "First released prose."))
    await asyncio.wait_for(first.wait(), 1)
    assert not provider.finished
    assert provider.inputs == ["First released prose. "]
    assert not finalize.called
    await owner.enqueue(span(1, "Next released prose."))
    owner.finish_input()
    await owner.wait()
    assert provider.open_count == 1 and provider.cancel_count == 1
    assert provider.inputs == ["First released prose. ", "Next released prose. "]
    expected_count = sum(map(len, provider.inputs))
    finalize.assert_awaited_once_with(True, expected_count)
    assert credits.await_args_list[-1].args == (expected_count,)
    assert [row["payload"]["phase"] for row in events] == ["start", "chunk", "chunk", "end"]
    assert [row["payload"]["chunk_index"] for row in events] == [0, 0, 1, 2]
    assert len({row["payload"]["attempt_id"] for row in events}) == 1
    assert all(row["payload"]["execution_version"] == 3 for row in events)
    assert "First released prose" not in str(events)
    assert "alignment" not in {row["payload"]["phase"] for row in events}


# contract-test: supporting surface=rest_api assertions=video-call.chat.ethics,video-call.chat.skill-integration
async def test_duplicate_immutable_handoff_never_resubmits_or_reopens():
    owner, provider, _events, first, finalize, _credits = make_turn()
    await owner.enqueue(span(0, "First."))
    await asyncio.wait_for(first.wait(), 1)
    await owner.enqueue(span(0, "First."))
    owner.finish_input()
    await owner.wait()
    await owner.wait()
    finalize.assert_awaited_once_with(True, len("First. "))
    assert provider.inputs == ["First. "] and provider.open_count == 1
    with pytest.raises(RealtimeTurnUnavailable):
        await owner.enqueue(span(1, "Late text."))


# contract-test: supporting surface=rest_api assertions=video-call.chat.ethics
async def test_safety_denial_sends_no_text_and_does_not_bill():
    owner, provider, events, _first, finalize, credits = make_turn(safety=False)
    await owner.enqueue(span(0, "Denied private prose."))
    owner.finish_input()
    await owner.wait()
    assert provider.inputs == []
    credits.assert_not_awaited()
    finalize.assert_awaited_once_with(False, 0)
    assert events[-1]["payload"]["phase"] == "error"
    assert "Denied private prose" not in str(events)


# contract-test: supporting surface=rest_api assertions=video-call.chat.ethics,video-call.audio.spoken-rich-response
async def test_authority_loss_stops_a_stalled_turn_and_rejects_late_audio(monkeypatch):
    from backend.apps.audio.assistant_speech import realtime_turn
    monkeypatch.setattr(realtime_turn, "AUTHORITY_INTERVAL_SECONDS", 0.01)
    active = True

    async def check():
        if not active:
            raise RuntimeError("PRIVATE registry failure")

    owner, provider, events, first, finalize, _credits = make_turn(active=check)
    await owner.enqueue(span(0, "Safe released prose."))
    await asyncio.wait_for(first.wait(), 1)
    active = False
    await owner.wait()
    assert provider.cancel_count == 1
    assert not provider.finished
    finalize.assert_awaited_once_with(False, 0)
    count = len(events)
    provider.events.put_nowait(SimpleNamespace(audio_bytes=b"late-private-audio", final=False))
    await asyncio.sleep(0)
    assert len(events) == count
    assert "PRIVATE" not in str(events)


# contract-test: supporting surface=rest_api assertions=video-call.chat.ethics
async def test_explicit_cancel_is_not_a_draining_close_and_never_bills_partial_work():
    owner, provider, events, first, finalize, _credits = make_turn()
    await owner.enqueue(span(0, "Partial prose."))
    await asyncio.wait_for(first.wait(), 1)
    await owner.cancel()
    assert provider.cancel_count == 1 and not provider.finished
    finalize.assert_awaited_once_with(False, 0)
    assert events[-1]["payload"]["phase"] == "error"


# contract-test: supporting surface=rest_api assertions=video-call.chat.ethics
async def test_bounded_memory_rejects_oversized_text_before_paid_work():
    owner, provider, _events, _first, finalize, _credits = make_turn()
    with pytest.raises(RealtimeTurnUnavailable):
        await owner.enqueue(span(0, "x" * MAX_TURN_CHARACTERS))
    assert provider.open_count == 0 and provider.inputs == []
    finalize.assert_awaited_once_with(False, 0)


# contract-test: supporting surface=rest_api assertions=video-call.chat.ethics
async def test_failed_audio_publication_cancels_provider_without_paid_retry():
    publish = AsyncMock(return_value=False)
    owner, provider, _events, _first, finalize, _credits = make_turn(publish=publish)
    await owner.enqueue(span(0, "Released prose."))
    owner.finish_input()
    await owner.wait()
    assert provider.open_count == 1 and provider.cancel_count == 1
    finalize.assert_awaited_once_with(False, 0)


# contract-test: supporting surface=rest_api assertions=video-call.chat.ethics
async def test_lifetime_bound_closes_idle_provider():
    owner, provider, _events, first, finalize, _credits = make_turn(seconds=0.05)
    await owner.enqueue(span(0, "Released prose."))
    await asyncio.wait_for(first.wait(), 1)
    await owner.wait()
    assert provider.cancel_count == 1 and not provider.finished
    finalize.assert_awaited_once_with(False, 0)


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response
def test_call_v3_profiles_preserve_all_curated_voices_and_manual_mistral_rate():
    from backend.apps.audio.assistant_speech.voice_profiles import ASSISTANT_VOICE_PROVIDER_IDS
    assert len(ASSISTANT_VOICE_PROVIDER_IDS) == 17
    for key, expected in ASSISTANT_VOICE_PROVIDER_IDS.items():
        call = resolve_assistant_voice_profile(key, version=3)
        manual = resolve_assistant_voice_profile(key, version=2)
        assert call.provider == "elevenlabs" and call.model == ELEVEN_V4_TURBO_SPEECH_MODEL
        assert call.elevenlabs_request()["voice_id"] == expected
        assert manual.provider == "mistral" and manual.model == ASSISTANT_RESPONSE_SPEECH_MODEL
    assert calculate_assistant_response_speech_credits(submitted_characters=1000, model=call.model) == 40
    assert calculate_assistant_response_speech_credits(submitted_characters=1000, model=manual.model) == 13


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response
def test_actual_consumer_handoff_does_not_wait_for_audio_before_canonical_final():
    source = (Path(__file__).resolve().parents[1] / "apps/ai/tasks/stream_consumer.py").read_text()
    assert "queue_provider_work=not continuous" in source
    assert source.index("realtime_speech_turn.finish_input()") < source.index("await realtime_speech_turn.wait()")
    assert source.index("completion_timing.mark_final_marker()") < source.index("await realtime_speech_turn.wait()")
    assert "turn_track_id=realtime_speech_turn.track_id" in source


# contract-test: supporting surface=rest_api assertions=video-call.chat.ethics,video-call.audio.spoken-rich-response
@pytest.mark.parametrize("failed", [False, True])
async def test_outer_lifetime_drains_after_postprocessing_and_cancels_on_every_exit(failed):
    import ast
    from contextvars import ContextVar
    from functools import wraps
    source = (Path(__file__).resolve().parents[1] / "apps/ai/tasks/ask_skill_task.py").read_text()
    tree = ast.parse(source)
    nodes = [node for node in tree.body if
             (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
              and node.target.id == "_owned_live_speech")
             or (isinstance(node, ast.FunctionDef) and node.name == "_owns_live_speech")]
    namespace = {"asyncio": asyncio, "ContextVar": ContextVar, "wraps": wraps}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "speech_lifetime", "exec"), namespace)
    trace = []
    owner = SimpleNamespace(wait=AsyncMock(side_effect=lambda: trace.append("audio-drain")),
                            cancel=AsyncMock(side_effect=lambda: trace.append("cancel")))

    async def pipeline():
        namespace["_owned_live_speech"].get().append(owner)
        trace.append("canonical-final")
        if failed:
            raise RuntimeError("pipeline failure")
        trace.append("postprocessing-complete")
        return "result"

    wrapped = namespace["_owns_live_speech"](pipeline)
    if failed:
        with pytest.raises(RuntimeError, match="pipeline failure"):
            await wrapped()
        assert trace == ["canonical-final", "cancel"]
        owner.wait.assert_not_awaited()
    else:
        assert await wrapped() == "result"
        assert trace == ["canonical-final", "postprocessing-complete", "audio-drain", "cancel"]
    owner.cancel.assert_awaited_once()
    assert namespace["_owned_live_speech"].get() is None


class MetadataStore:
    """Small conditional metadata store; rejects any generated-asset collection."""
    def __init__(self):
        self.rows = {"assistant_speech_manifests": [], "assistant_speech_segments": []}

    async def get_items(self, collection, *, params, no_cache):
        assert no_cache
        rows = self.rows[collection]
        for key, value in params.items():
            if key.startswith("filter["):
                field = key[len("filter["):].split("]")[0]
                rows = [row for row in rows if row.get(field) == value]
        return [dict(row) for row in rows]

    async def create_item(self, collection, record):
        row = {"id": f"row-{collection}-{len(self.rows[collection])}", **record}
        self.rows[collection].append(row)
        return dict(row), None

    async def update_item_if_version(self, collection, row_id, patch, version, *, version_field, extra_filters=None):
        row = next(row for row in self.rows[collection] if row["id"] == row_id)
        if row.get(version_field) != version or any(row.get(key) != value for key, value in (extra_filters or {}).items()):
            return None
        row.update(patch)
        return dict(row)

    async def update_item(self, collection, row_id, patch):
        row = next(row for row in self.rows[collection] if row["id"] == row_id)
        row.update(patch)


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response
@pytest.mark.parametrize("version,model", [(2, ASSISTANT_RESPONSE_SPEECH_MODEL), (3, ELEVEN_V4_TURBO_SPEECH_MODEL)])
async def test_actual_manifest_records_correct_model_and_track_bills_once_without_assets(version, model):
    from backend.apps.audio.assistant_speech.persistence import (
        claim_speech_segment_execution, complete_segment_billing, create_manifest_and_segments,
        finalize_speech_segment_execution, prepare_next_segment_billing,
    )
    store = MetadataStore()
    manifest = await create_manifest_and_segments(
        store, user_id="owner", chat_id="chat", assistant_message_id="assistant",
        source_version=1, voice_profile={"key": "sophia", "version": version},
        voice_call_id="call" if version == 3 else None,
        segments=[{"segment_id": "track", "sequence": 0, "source_hash": "private-source-identity",
                   "kind": "voice_prose_turn" if version == 3 else "prose_paragraph"}],
    )
    assert manifest["model"] == model
    claimed = await claim_speech_segment_execution(store, "track", lease_id="lease")
    assert claimed
    assert await finalize_speech_segment_execution(
        store, "track", {"status": "ready", "billable_character_count": 123, "duration_seconds": 1},
        lease_id="lease", execution_version=claimed["execution_version"], completed_live=version == 3,
    )
    billing = await prepare_next_segment_billing(store, manifest["manifest_id"])
    assert billing["model"] == model and billing["submitted_characters"] == 123
    assert await complete_segment_billing(store, billing, usage_id="idempotent-usage")
    assert await prepare_next_segment_billing(store, manifest["manifest_id"]) is None
    assert set(store.rows) == {"assistant_speech_manifests", "assistant_speech_segments"}
    assert "speakable_text" not in str(store.rows) and "audio_bytes" not in str(store.rows)
    assert all(not row.get("generated_asset_id") for row in store.rows["assistant_speech_segments"])


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response
async def test_projection_releases_first_rich_sentence_before_provider_input_eos(monkeypatch):
    from backend.apps.ai.assistant_speech import streaming
    monkeypatch.setattr(streaming, "_token_secret", lambda: b"test-only-key")
    owner, provider, _events, first, finalize, _credits = make_turn()

    async def finish(_metadata):
        owner.finish_input()

    tracker = streaming.ImmutableSpeechBoundaryTracker(
        metadata={"chat_id": "chat", "assistant_message_id": "message", "source_version": 1,
                  "voice_mode": True, "voice_call_id": "call"},
        dispatch_speech=owner.enqueue, finalize_speech=finish,
    )
    initial = "# Results\n\nHere are the images I found. "
    tracker.observe(initial)
    await asyncio.wait_for(first.wait(), 1)
    assert "Here are the images I found. " in provider.inputs
    assert not provider.finished and not finalize.called
    tracker.observe(initial + "See [the source](https://example.com).\n\n[!](embed:image-ref)\n", is_final=True)
    await tracker.wait_for_handoff()
    await owner.wait()
    assert provider.open_count == 1
    assert all("embed:" not in text and "https://" not in text and "#" not in text for text in provider.inputs)
    finalize.assert_awaited_once_with(True, sum(map(len, provider.inputs)))


# contract-test: supporting surface=rest_api assertions=video-call.chat.ethics
async def test_authority_watchdog_covers_provider_handshake(monkeypatch):
    from backend.apps.audio.assistant_speech import realtime_turn
    monkeypatch.setattr(realtime_turn, "AUTHORITY_INTERVAL_SECONDS", 0.01)
    provider = Provider()
    opened = asyncio.Event()
    active = True

    async def stalled_open():
        provider.open_count += 1
        opened.set()
        await asyncio.Event().wait()

    async def check():
        if not active:
            raise RuntimeError("lost authority")

    provider.open = stalled_open
    owner, provider, _events, _first, finalize, _credits = make_turn(provider, active=check)
    await owner.enqueue(span(0, "Released prose."))
    await asyncio.wait_for(opened.wait(), 1)
    active = False
    await owner.wait()
    assert provider.cancel_count == 1 and not provider.inputs
    finalize.assert_awaited_once_with(False, 0)


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response
async def test_first_useful_audio_stops_waiting_preparation_before_playback_start():
    owner, _provider, events, first, _finalize, _credits = make_turn()
    stopped = AsyncMock()
    owner._on_first_audio = stopped
    await owner.enqueue(span(0, "Useful prose."))
    await asyncio.wait_for(first.wait(), 1)
    stopped.assert_awaited_once()
    assert events[0]["payload"]["phase"] == "start"
    owner.finish_input()
    await owner.wait()
    stopped.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response,video-call.chat.ethics,video-call.privacy
async def test_expressive_provider_input_safeguards_and_credits_bind_exact_tagged_text():
    from backend.apps.ai.assistant_speech.projection import project_streaming_speech_segment
    owner, provider, events, _first, finalize, credits = make_turn()
    _, text = project_streaming_speech_segment(
        '<!-- voice:curious -->A useful answer.', voice_mode=True)
    await owner.enqueue(span(0, text))
    owner.finish_input()
    await owner.wait()
    submitted = '[curious] A useful answer. '
    assert provider.inputs == [submitted]
    owner._safety_check.assert_awaited_once_with(submitted)
    assert credits.await_args_list[-1].args == (len(submitted),)
    finalize.assert_awaited_once_with(True, len(submitted))
    assert 'curious' not in str(events) and 'A useful answer' not in str(events)


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response,video-call.privacy
@pytest.mark.parametrize('failure,expected_cause,expected_code', [
    ('provider', 'provider', 'invalid_alignment'),
    ('unexpected', 'unexpected', 'none'),
    ('unknown_provider_code', 'provider', 'unknown'),
])
async def test_failure_diagnostics_are_content_free_and_identify_reader_stage(caplog, failure, expected_cause, expected_code):
    class ProviderError(RuntimeError):
        def __init__(self, code):
            self.code = code
            super().__init__('PRIVATE provider body')
    class FailingProvider(Provider):
        async def audio_events(self):
            if failure == 'unexpected':
                raise RuntimeError('PRIVATE credentials https://private.example/token')
            raise ProviderError('invalid_alignment' if failure == 'provider' else 'PRIVATE_TOKEN')
            yield  # pragma: no cover: retain async-iterator protocol
    owner, provider, _events, _first, finalize, _credits = make_turn(FailingProvider())
    await owner.enqueue(span(0, 'PRIVATE spoken prose.'))
    owner.finish_input()
    await owner.wait()
    assert f'stage=reading cause={expected_cause} code={expected_code}' in caplog.text
    assert 'PRIVATE' not in caplog.text and 'https://' not in caplog.text
    finalize.assert_awaited_once_with(False, 0)


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response,video-call.privacy
@pytest.mark.parametrize('timed_out,expected', [(False, 'cancelled'), (True, 'timeout')])
async def test_cancellation_diagnostics_distinguish_timeout_without_draining(caplog, timed_out, expected):
    import logging
    caplog.set_level(logging.INFO, logger='backend.apps.audio.assistant_speech.realtime_turn')
    owner, provider, _events, first, finalize, _credits = make_turn()
    await owner.enqueue(span(0, 'PRIVATE spoken prose.'))
    await asyncio.wait_for(first.wait(), 1)
    await owner.cancel(timed_out=timed_out)
    assert f'cause={expected} code=none' in caplog.text
    assert 'PRIVATE' not in caplog.text
    assert not provider.finished and provider.cancel_count == 1
    finalize.assert_awaited_once_with(False, 0)


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response,video-call.privacy
async def test_cancel_during_audio_publication_is_not_misdiagnosed_as_transport_failure(caplog):
    import logging
    caplog.set_level(logging.INFO, logger='backend.apps.audio.assistant_speech.realtime_turn')
    publishing = asyncio.Event()
    async def blocked_publish(*_args):
        publishing.set()
        await asyncio.Event().wait()
    owner, provider, _events, _first, finalize, _credits = make_turn(publish=blocked_publish)
    await owner.enqueue(span(0, 'PRIVATE spoken prose.'))
    await asyncio.wait_for(publishing.wait(), 1)
    await owner.cancel()
    assert 'cause=cancelled code=none' in caplog.text
    assert 'publication_failed' not in caplog.text and 'PRIVATE' not in caplog.text
    assert not provider.finished
    finalize.assert_awaited_once_with(False, 0)
