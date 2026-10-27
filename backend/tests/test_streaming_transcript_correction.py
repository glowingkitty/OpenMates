"""Regression checks for correction overlapping a live dictation stream."""

import asyncio

import pytest

from backend.core.api.app.services import streaming_transcript_correction as streaming


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=message-input.audio.realtime-voxtral3,message-input.audio.editable-transcript
async def test_completed_paragraph_is_reused_and_only_new_speech_is_corrected(
    monkeypatch,
):
    monkeypatch.setattr(streaming, "CORRECTION_BATCH_CHARACTERS", 80)
    calls = []
    progress = asyncio.Event()

    async def correct(raw, language):
        calls.append((raw, language))
        return {
            "transcript": raw.replace("um ", "").replace("uh ", ""),
            "title": "Workshop plans",
            "correction_model": "test",
        }

    async def corrected(_offset):
        progress.set()

    first = "um Reserve the library and keep the budget below five hundred euros.\n\n"
    tail = "uh Finally send the room confirmation to Marta before Thursday."
    worker = streaming.StreamingTranscriptCorrection(correct, corrected)
    worker.append(first + tail[:20])
    try:
        await asyncio.wait_for(progress.wait(), 1)
        assert calls == [(first.strip(), None)]
        worker.append(tail[20:])
        result = await worker.finish(first + tail, "en")
        assert calls == [(first.strip(), None), (tail, "en")]
        assert result["transcript"] == first.strip().removeprefix(
            "um "
        ) + "\n\n" + tail.removeprefix("uh ")
    finally:
        await worker.cancel()


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=message-input.audio.realtime-voxtral3
async def test_timer_corrects_speech_without_waiting_for_another_delta(monkeypatch):
    monkeypatch.setattr(streaming, "CORRECTION_INTERVAL_SECONDS", 0.01)
    progress = asyncio.Event()
    calls = []

    async def correct(raw, _language):
        calls.append(raw)
        return {
            "transcript": "Keep the budget.",
            "title": "Budget",
            "correction_model": "test",
        }

    async def corrected(_offset):
        progress.set()

    worker = streaming.StreamingTranscriptCorrection(correct, corrected)
    worker.append("um keep the budget.")
    try:
        await asyncio.wait_for(progress.wait(), 1)
        result = await worker.finish("um keep the budget.", "en")
        assert calls == ["um keep the budget."]
        assert result["transcript"] == "Keep the budget."
    finally:
        await worker.cancel()


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=message-input.audio.realtime-voxtral3,message-input.recording.lifecycle
async def test_audio_keeps_arriving_during_correction_and_requests_never_overlap(
    monkeypatch,
):
    monkeypatch.setattr(streaming, "CORRECTION_BATCH_CHARACTERS", 30)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []
    in_flight = 0

    async def correct(raw, _language):
        nonlocal in_flight
        in_flight += 1
        assert in_flight == 1
        calls.append(raw)
        entered.set()
        await release.wait()
        in_flight -= 1
        return {"transcript": raw, "title": "Plans", "correction_model": "test"}

    async def progress(_offset):
        pass

    first = "Keep the budget below 500 euros. "
    tail = "Send the confirmation on Thursday."
    worker = streaming.StreamingTranscriptCorrection(correct, progress)
    worker.append(first)
    try:
        await asyncio.wait_for(entered.wait(), 1)
        worker.append(tail)
        finishing = asyncio.create_task(worker.finish(first + tail, "en"))
        await asyncio.sleep(0)
        assert len(calls) == 1
        assert not finishing.done()
        release.set()
        result = await asyncio.wait_for(finishing, 1)
        assert result["transcript"] == (first + tail)
        assert all(len(raw) <= 30 for raw in calls)
    finally:
        await worker.cancel()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "empty", "timeout"])
# contract-test: supporting surface=gui.web assertions=message-input.audio.editable-transcript
async def test_failed_batch_keeps_its_words_and_later_batches_can_succeed(
    monkeypatch, failure
):
    monkeypatch.setattr(streaming, "CORRECTION_BATCH_CHARACTERS", 40)
    monkeypatch.setattr(streaming, "CORRECTION_TIMEOUT_SECONDS", 0.01)
    calls = []

    async def correct(raw, _language):
        calls.append(raw)
        if len(calls) == 1:
            if failure == "exception":
                raise RuntimeError("provider unavailable")
            if failure == "timeout":
                await asyncio.Future()
            return {"transcript": "", "title": "Plans", "correction_model": "test"}
        return {
            "transcript": raw.replace("uh ", ""),
            "title": "Plans",
            "correction_model": "test",
        }

    async def progress(_offset):
        pass

    first = "Keep every requirement in this note.\n\n"
    tail = "uh Send it to Marta."
    worker = streaming.StreamingTranscriptCorrection(correct, progress)
    worker.append(first + tail)
    try:
        result = await worker.finish(first + tail, "en")
        assert calls == [first.strip(), tail]
        assert result["transcript"] == first.strip() + "\n\nSend it to Marta."
    finally:
        await worker.cancel()


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=message-input.recording.lifecycle
async def test_cancelling_recording_cancels_in_flight_correction(monkeypatch):
    monkeypatch.setattr(streaming, "CORRECTION_INTERVAL_SECONDS", 0)
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def correct(_raw, _language):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    async def progress(_offset):
        raise AssertionError("Cancelled correction must never publish a result")

    worker = streaming.StreamingTranscriptCorrection(correct, progress)
    worker.append("Keep my draft.")
    await asyncio.wait_for(entered.wait(), 1)
    await worker.cancel()
    assert cancelled.is_set()


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=message-input.audio.editable-transcript
async def test_final_provider_window_can_extend_last_delta_without_losing_earlier_speech():
    calls = []

    async def correct(raw, _language):
        calls.append(raw)
        return {"transcript": raw, "title": "Plans", "correction_model": "test"}

    async def progress(_offset):
        pass

    worker = streaming.StreamingTranscriptCorrection(correct, progress)
    worker.append("  First keep the budget. Then invite ")
    try:
        result = await worker.finish("First keep the budget. Then invite Marta.", "en")
        assert result["transcript"] == "First keep the budget. Then invite Marta."
        assert calls == ["First keep the budget. Then invite Marta."]
    finally:
        await worker.cancel()


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=message-input.audio.editable-transcript
async def test_all_failed_batches_report_failure_instead_of_claiming_correction():
    async def correct(_raw, _language):
        raise RuntimeError("provider unavailable")

    async def progress(_offset):
        raise AssertionError("Failed batches must not claim correction progress")

    worker = streaming.StreamingTranscriptCorrection(correct, progress)
    worker.append("Keep all of these words.")
    try:
        with pytest.raises(
            RuntimeError, match="No transcript batch could be corrected"
        ):
            await worker.finish("Keep all of these words.", "en")
    finally:
        await worker.cancel()
