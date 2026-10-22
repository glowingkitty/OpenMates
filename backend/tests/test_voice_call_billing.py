"""Voice STT bills accepted audio duration; normal chat and TTS bill separately."""
from types import SimpleNamespace

import pytest

from backend.core.api.app.routes import voice_call as route


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.usage.provider-metering
def test_idle_connection_costs_zero_and_pcm_rounds_once_per_call():
    ledger = route.SpeechUsageLedger()
    assert ledger.view(600)["credits_accrued"] == 0
    ledger.audio_bytes = 2
    assert ledger.credits == route.REALTIME_CREDITS_PER_MINUTE
    ledger.audio_bytes = 32000 * 60
    assert ledger.billed_minutes == 1
    ledger.audio_bytes += 2
    assert ledger.billed_minutes == 2
    # There is no old per-turn/context/visual token ledger to charge again.
    assert not hasattr(ledger, "gemini_cost")
    assert "gemini_input_tokens" not in ledger.view(600)


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.usage.provider-metering
async def test_cumulative_duration_charges_only_new_minutes_with_stable_retry_identity(monkeypatch):
    monkeypatch.setattr(route, "is_payment_enabled", lambda: True)
    calls = []
    fail = True

    class Billing:
        async def charge_user_credits(self, **kwargs):
            nonlocal fail
            calls.append(kwargs)
            if fail:
                fail = False
                raise RuntimeError("Lost billing receipt")
            return {"charged_credits": kwargs["credits_to_deduct"]}

    monkeypatch.setattr(route, "_billing", lambda _: Billing())
    ledger = route.SpeechUsageLedger()
    ledger.audio_bytes = 3200
    args = dict(user_id="owner", user_hash="owner-hash", call_id="call", chat_id="chat")
    with pytest.raises(RuntimeError):
        await route._charge_voice(SimpleNamespace(), ledger, **args)
    assert ledger.charged == 0
    await route._charge_voice(SimpleNamespace(), ledger, **args)
    await route._charge_voice(SimpleNamespace(), ledger, **args)
    assert len(calls) == 2
    assert calls[0]["idempotency_key"] == calls[1]["idempotency_key"] == "voice-call:call:stt:1"
    assert calls[1]["credits_to_deduct"] == route.REALTIME_CREDITS_PER_MINUTE
    ledger.audio_bytes = 32000 * 60 + 2
    await route._charge_voice(SimpleNamespace(), ledger, **args)
    assert calls[-1]["credits_to_deduct"] == route.REALTIME_CREDITS_PER_MINUTE
    assert calls[-1]["idempotency_key"] == "voice-call:call:stt:2"
    assert calls[-1]["usage_details"]["model_used"] == "voxtral-mini-transcribe-realtime-3-0"
    assert ledger.charged == 2 * route.REALTIME_CREDITS_PER_MINUTE


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.usage.provider-metering
async def test_partial_charge_cannot_mark_unpaid_duration_settled(monkeypatch):
    monkeypatch.setattr(route, "is_payment_enabled", lambda: True)
    class Billing:
        async def charge_user_credits(self, **kwargs):
            return {"charged_credits": 0}
    monkeypatch.setattr(route, "_billing", lambda _: Billing())
    ledger = route.SpeechUsageLedger()
    ledger.audio_bytes = 3200
    with pytest.raises(RuntimeError, match="incomplete"):
        await route._charge_voice(SimpleNamespace(), ledger, user_id="owner", user_hash="hash", call_id="call", chat_id="chat")
    assert ledger.charged == 0
