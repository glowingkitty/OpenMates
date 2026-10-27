"""Provider-free coverage for split native speech in isolated voice CI."""

# contract-test-file: infrastructure

import base64

import pytest

from backend.shared.testing.voice_call_fixture import (
    IsolatedVoxtralVoiceFixture,
    isolated_voice_completion_fixture,
)


GUARDS = {"CI": "true", "OPENMATES_CI_ISOLATED": "1",
          "OPENMATES_CI_AI_FIXTURES": "1", "MOCK_EXTERNAL_APIS": "true"}


@pytest.fixture
def isolated(monkeypatch):
    for name, value in GUARDS.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("missing", GUARDS)
def test_completion_fixture_requires_every_guard(isolated, monkeypatch, missing):
    monkeypatch.delenv(missing)
    assert isolated_voice_completion_fixture("How do I make") is None
    assert isolated_voice_completion_fixture("How do I make ramen?") is None
    with pytest.raises(RuntimeError, match="unavailable"):
        IsolatedVoxtralVoiceFixture()


def test_completion_fixture_only_classifies_known_microphone_text(isolated):
    assert isolated_voice_completion_fixture("How do I make") == "incomplete"
    assert isolated_voice_completion_fixture("How do I make ramen?") == "complete"
    assert isolated_voice_completion_fixture("Some unrelated request") is None


@pytest.mark.asyncio
async def test_native_boundary_requires_later_voiced_input_to_resume(isolated):
    fixture = IsolatedVoxtralVoiceFixture()
    def voiced(size):
        return base64.b64encode(b"\x00\x01" * (size // 2)).decode()

    await fixture.send_audio(voiced(3200))
    first = [await fixture.receive() for _ in range(3)]
    assert [event["type"] for event in first] == ["turn.start", "transcription.text.delta", "turn.end"]
    assert first[1]["text"] == "How do I make"
    # Even a long silent microphone interval cannot fabricate the continuation.
    await fixture.send_audio(base64.b64encode(bytes(320_000)).decode())
    assert fixture._events.empty()
    await fixture.send_audio(voiced(28_798))
    assert fixture._events.empty()
    await fixture.send_audio(voiced(2))
    second = [await fixture.receive() for _ in range(3)]
    assert [event["type"] for event in second] == ["turn.start", "transcription.text.delta", "turn.end"]
    assert second[1]["text"] == "ramen?"
    await fixture.send_audio(voiced(32000))
    assert fixture._events.empty()


@pytest.mark.asyncio
async def test_large_startup_batch_still_requires_a_later_voiced_chunk(isolated):
    fixture = IsolatedVoxtralVoiceFixture()
    await fixture.send_audio(base64.b64encode(b"\x00\x01" * 16000).decode())
    assert [await fixture.receive() for _ in range(3)][1]["text"] == "How do I make"
    await fixture.send_audio(base64.b64encode(bytes(3200)).decode())
    assert fixture._events.empty()
    await fixture.send_audio(base64.b64encode(b"\x00\x01").decode())
    assert [await fixture.receive() for _ in range(3)][1]["text"] == "ramen?"
