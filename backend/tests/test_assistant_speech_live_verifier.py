"""Regression checks for the opt-in assistant speech live verifier.

The live script consumes real provider credits, so unit coverage verifies its
identity lookup and immediate safe-rejection handling without network calls.
"""

from pathlib import Path

# contract-test-file: tooling


def test_live_verifier_resolves_assistant_identity_and_surfaces_rejections() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "scripts/verify_assistant_speech_live_smoke.mjs"
    ).read_text(encoding="utf-8")

    assert 'message?.role === "assistant"' in source
    assert "messageId: assistantMessage.id" in source
    assert "Assistant speech request was rejected" in source
