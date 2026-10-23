import asyncio

from backend.apps.ai.assistant_speech.voice_waiting import DelayedVoiceWaiting


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
async def test_delayed_waiting_uses_request_language_once_and_never_falls_back_to_english():
    spoken = []
    waiting = DelayedVoiceWaiting(language="de-DE", response_ready=lambda: False,
                                  dispatch=spoken.append, delay_seconds=0.001)
    waiting.start()
    waiting.start()
    await asyncio.sleep(0.01)
    await waiting.close()
    assert spoken == ["Lass mich kurz darüber nachdenken."]
    unsupported = DelayedVoiceWaiting(language="zz", response_ready=lambda: False,
                                      dispatch=spoken.append, delay_seconds=0)
    unsupported.start()
    await asyncio.sleep(0)
    await unsupported.close()
    assert len(spoken) == 1


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
async def test_useful_response_or_completion_suppresses_waiting_confirmation():
    spoken = []
    ready = False
    waiting = DelayedVoiceWaiting(language="en", response_ready=lambda: ready,
                                  dispatch=spoken.append, delay_seconds=0.001)
    waiting.start()
    ready = True
    await asyncio.sleep(0.01)
    await waiting.close()
    cancelled = DelayedVoiceWaiting(language="en", response_ready=lambda: False,
                                    dispatch=spoken.append, delay_seconds=0.01)
    cancelled.start()
    await cancelled.close()
    await asyncio.sleep(0.02)
    assert spoken == []


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
async def test_waiting_uses_remaining_worker_budget_without_a_second_full_delay(monkeypatch):
    from types import SimpleNamespace
    from backend.apps.ai.assistant_speech import voice_waiting

    delays = []
    spoken = []
    real_sleep = asyncio.sleep

    async def sleep(delay):
        delays.append(delay)
        await real_sleep(0)

    # Patch only this module's clock/sleep, preserving the event loop's clock.
    monkeypatch.setattr(voice_waiting, "time", SimpleNamespace(monotonic=lambda: 101.0))
    monkeypatch.setattr(voice_waiting, "asyncio", SimpleNamespace(
        sleep=sleep, create_task=asyncio.create_task, gather=asyncio.gather,
    ))
    partial = DelayedVoiceWaiting(language="fr", response_ready=lambda: False,
                                  dispatch=spoken.append, started_at=100.0)
    partial.start()
    partial.start()
    await partial._task
    await partial.close()
    expired = DelayedVoiceWaiting(language="de", response_ready=lambda: False,
                                  dispatch=spoken.append, started_at=90.0)
    expired.start()
    await expired._task
    await expired.close()
    legacy = DelayedVoiceWaiting(language="en", response_ready=lambda: False, dispatch=spoken.append)
    legacy.start()
    await legacy._task
    await legacy.close()
    assert delays == [0.5, 0.0, 1.5]
    assert spoken == ["Laisse-moi y réfléchir un instant.", "Lass mich kurz darüber nachdenken.",
                      "Let me think about that."]


def _consumer_waiting_tracker(dispatched):
    from backend.apps.ai.assistant_speech.streaming import ImmutableSpeechBoundaryTracker

    async def handoff(segment):
        dispatched.append(segment)

    return ImmutableSpeechBoundaryTracker(
        metadata={"chat_id": "chat", "assistant_message_id": "assistant-turn", "source_version": 1,
                  "voice_mode": True, "voice_call_id": "call", "voice_turn_id": "user-turn", "language": "de"},
        dispatch_speech=handoff,
    )


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
async def test_elapsed_budget_queues_once_through_original_consumer_tracker_only():
    import time

    dispatched = []
    started_at = time.monotonic() - 10
    # An elapsed worker budget creates no speech or waiting task by itself.
    await asyncio.sleep(0)
    assert dispatched == []
    tracker = _consumer_waiting_tracker(dispatched)
    waiting = DelayedVoiceWaiting(
        language="de-DE", started_at=started_at,
        response_ready=lambda: tracker.has_response_segments,
        dispatch=lambda text: tracker.dispatch_projected_segment(
            sequence=-1, kind="waiting_confirmation", speakable_text=text,
        ),
    )
    waiting.start()
    waiting.start()
    await asyncio.wait_for(waiting._task, timeout=0.1)
    await waiting.close()
    await tracker.wait_for_handoff()
    assert len(dispatched) == 1
    assert dispatched[0]["kind"] == "waiting_confirmation"
    assert dispatched[0]["sequence"] == -1
    assert dispatched[0]["speakable_text"] == "Lass mich kurz darüber nachdenken."
    assert dispatched[0]["voice_call_id"] == "call"
    assert tracker.has_response_segments is False


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
async def test_expired_budget_still_yields_to_ready_prose_or_owner_cancellation():
    import time

    for has_prose in (False, True):
        dispatched = []
        tracker = _consumer_waiting_tracker(dispatched)
        waiting = DelayedVoiceWaiting(
            language="de", started_at=time.monotonic() - 10,
            response_ready=lambda: tracker.has_response_segments,
            dispatch=lambda text: tracker.dispatch_projected_segment(
                sequence=-1, kind="waiting_confirmation", speakable_text=text,
            ),
        )
        waiting.start()
        if has_prose:
            tracker.dispatch_projected_segment(sequence=0, kind="voice_prose_clause", speakable_text="Die Antwort.")
            await asyncio.wait_for(waiting._task, timeout=0.1)
        # A cancelled/rejected owner drains this same original consumer timer.
        await waiting.close()
        await tracker.wait_for_handoff()
        assert [segment["kind"] for segment in dispatched] == (["voice_prose_clause"] if has_prose else [])


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
async def test_expired_budget_never_falls_back_for_unknown_language():
    import time

    dispatched = []
    tracker = _consumer_waiting_tracker(dispatched)
    waiting = DelayedVoiceWaiting(
        language="zz", started_at=time.monotonic() - 10,
        response_ready=lambda: tracker.has_response_segments,
        dispatch=lambda text: tracker.dispatch_projected_segment(
            sequence=-1, kind="waiting_confirmation", speakable_text=text,
        ),
    )
    waiting.start()
    await asyncio.sleep(0)
    await waiting.close()
    await tracker.wait_for_handoff()
    assert dispatched == []
