"""Local recording completion/failure must never select external transcription."""

import json

import pytest

from backend.apps.ai.processing.audio_recording_guard import (
    has_transcribed_web_audio_recording,
    remove_audio_transcribe_for_transcribed_recordings,
    should_block_local_audio_transcription,
)


def recording(status="complete", transcript="", **extra):
    return {
        "type": "audio-recording", "transcription_source": "local",
        "transcription_status": status, "transcript": transcript,
        "filename": "voice.m4a", "embed_ref": "voice.m4a", **extra,
    }


def message(*records, format="toon"):
    blocks = []
    for record in records:
        content = json.dumps(record) if format == "json" else "\n".join(
            f"{key}: {json.dumps(value)}" for key, value in record.items()
        )
        blocks.append(f"```{format}\n{content}\n```")
    return {"role": "user", "content": "\n".join(blocks)}


MANUAL_AUDIO = {
    "type": "file-attachment", "mime_type": "audio/mpeg",
    "filename": "interview.mp3", "embed_ref": "interview.mp3", "s3_key": "manual-key",
}


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
@pytest.mark.parametrize("format", ["toon", "json"])
@pytest.mark.parametrize("status,transcript", [("complete", ""), ("complete", "Hello"), ("failed", None)])
def test_local_recordings_never_enable_external_fallback(format, status, transcript):
    history = [message(recording(status, transcript), format=format)]
    assert has_transcribed_web_audio_recording(history)
    assert remove_audio_transcribe_for_transcribed_recordings(
        ["audio-transcribe", "web-search"], history,
    ) == (["web-search"], True)
    assert should_block_local_audio_transcription(
        {"requests": [{"filename": "voice.m4a"}]}, history,
    )


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
@pytest.mark.parametrize("format", ["toon", "json"])
@pytest.mark.parametrize("status,transcript", [("complete", ""), ("complete", "Hello"), ("failed", None)])
def test_mixed_history_blocks_local_target_but_allows_explicit_manual_attachment(format, status, transcript):
    # Both embeds may occur in one message; their metadata must remain separate.
    history = [message(recording(status, transcript, s3_key="local-key"), MANUAL_AUDIO, format=format)]
    assert not has_transcribed_web_audio_recording(history)
    assert remove_audio_transcribe_for_transcribed_recordings(
        ["audio-transcribe", "web-search"], history,
    ) == (["audio-transcribe", "web-search"], False)
    for target in ({"filename": "voice.m4a"}, {"embed_ref": "voice.m4a"}, {"s3_key": "local-key"}):
        assert should_block_local_audio_transcription({"requests": [target]}, history)
    assert not should_block_local_audio_transcription(
        {"requests": [{"filename": "interview.mp3", "s3_key": "manual-key"}]}, history,
    )


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
@pytest.mark.parametrize("arguments", [
    None, {}, {"requests": []}, {"requests": [{}]},
    {"requests": [{"filename": "unknown.mp3"}]},
    {"requests": [{"filename": "interview.mp3"}, {"filename": "voice.m4a"}]},
    {"requests": [{"filename": "interview.mp3", "s3_key": "local-key"}]},
    {"requests": [{"filename": "interview.mp3", "s3_key": "unknown-key"}]},
])
def test_ambiguous_and_mixed_batches_cannot_forward_local_audio(arguments):
    history = [message(recording("failed", None, s3_key="local-key")), message(MANUAL_AUDIO)]
    assert should_block_local_audio_transcription(arguments, history)


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
def test_recording_filename_collision_does_not_authorize_manual_fallback():
    history = [message(recording("failed", None)), message({**MANUAL_AUDIO, "filename": "voice.m4a"})]
    assert should_block_local_audio_transcription({"requests": [{"filename": "voice.m4a"}]}, history)


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
def test_manual_audio_and_legacy_untranscribed_recordings_keep_existing_routing():
    history = [message({"type": "audio-recording", "transcript": None}), message(MANUAL_AUDIO)]
    assert not should_block_local_audio_transcription({"requests": [{"filename": "interview.mp3"}]}, history)


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
def test_failed_local_recording_does_not_borrow_a_manual_transcript_or_filename():
    history = [message(recording("failed", None), {**MANUAL_AUDIO, "transcript": "Manual context"})]
    assert should_block_local_audio_transcription({"requests": [{"filename": "voice.m4a"}]}, history)
    assert not should_block_local_audio_transcription({"requests": [{"filename": "interview.mp3"}]}, history)


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
def test_local_authority_does_not_depend_on_toon_field_order():
    history = [{"content": "```toon\ntranscription_source: local\nfilename: voice.m4a\n"
                            "transcription_status: failed\ntranscript: null\ntype: audio-recording\n```"}]
    assert has_transcribed_web_audio_recording(history)
    assert should_block_local_audio_transcription({"requests": [{"filename": "voice.m4a"}]}, history)
