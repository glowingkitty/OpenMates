"""Voice billing follows reported tokens, never connection time or local VAD."""

from decimal import Decimal

from backend.core.api.app.routes.video_call_experiment import UsageLedger, _credits_for


def audio_usage(input_tokens: int, output_tokens: int = 0) -> dict:
    return {"totalTokenCount": input_tokens + output_tokens,
            "promptTokenCount": input_tokens, "responseTokenCount": output_tokens,
            "promptTokensDetails": [{"modality": "AUDIO", "tokenCount": input_tokens}],
            "responseTokensDetails": [{"modality": "AUDIO", "tokenCount": output_tokens}]}


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.usage.provider-metering
def test_idle_connection_and_empty_usage_cost_zero():
    ledger = UsageLedger()
    assert not ledger.commit_gemini_turn()
    assert ledger.view(600)["credits_accrued"] == 0
    ledger.stage_gemini({"totalTokenCount": 0})
    assert ledger.commit_gemini_turn()
    assert ledger.gemini_cost == 0 and _credits_for(ledger.gemini_cost) == 0


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.usage.provider-metering
def test_reported_silent_and_spoken_audio_tokens_have_identical_price():
    silent, spoken = UsageLedger(), UsageLedger()
    for ledger in (silent, spoken):
        ledger.stage_gemini(audio_usage(1920, 1440))
        assert ledger.commit_gemini_turn()
    assert silent.gemini_cost == spoken.gemini_cost == Decimal("0.02304")
    assert _credits_for(silent.gemini_cost) == 28


# contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.usage.provider-metering
def test_interim_duplicates_commit_once_but_equal_reports_on_distinct_turns_are_rebilled():
    ledger = UsageLedger()
    final = audio_usage(200, 100)
    for snapshot in (audio_usage(100), final, final, audio_usage(150)):
        ledger.stage_gemini(snapshot)
    assert ledger.commit_gemini_turn()
    assert not ledger.commit_gemini_turn()
    assert ledger.gemini_cost == Decimal("0.0018")
    ledger.stage_gemini(final)
    assert ledger.commit_gemini_turn()
    assert ledger.gemini_cost == Decimal("0.0036")
    assert ledger.prompt_tokens == 400 and ledger.response_tokens == 200


# contract-test: supporting surface=gui.web assertions=video-call.usage.provider-metering,video-call.video.source-frame-provenance
def test_camera_provider_image_video_modalities_use_actual_tokens_once():
    ledger = UsageLedger()
    ledger.stage_gemini({"totalTokenCount": 1000, "promptTokenCount": 1000, "responseTokenCount": 0,
        "promptTokensDetails": [{"modality": "IMAGE", "tokenCount": 700}, {"modality": "VIDEO", "tokenCount": 300}]})
    assert ledger.commit_gemini_turn()
    assert not ledger.commit_gemini_turn()
    assert ledger.gemini_cost == Decimal("0.001")
    assert _credits_for(ledger.gemini_cost) == 2
