"""Keep live correction probes sensitive to stale intent and omitted constraints."""
# contract-test-file: infrastructure

import pytest

from backend.scripts.test_audio_transcript_correction_real import SAMPLES, quality_failures


@pytest.mark.parametrize(("case_id", "corrected"), [
    ("en_final_date_and_recipient",
     "Schedule the review for Thursday at ten. Invite Bob. Keep it online and don't send invites yet."),
    ("en_final_action", "Archive the draft. Keep the published report unchanged."),
    ("en_preserve_contrast_and_alternatives",
     "Don't cancel the meeting; reschedule it. Ideally Thursday, but Friday also works. Keep the room booking."),
])
def test_final_intent_with_remaining_constraints_passes(case_id, corrected):
    sample = next(sample for sample in SAMPLES if sample["id"] == case_id)
    assert quality_failures(sample, corrected) == []


@pytest.mark.parametrize(("case_id", "incorrect"), [
    ("en_final_date_and_recipient",
     "Schedule Tuesday at nine, actually Thursday at ten. Invite Alice, sorry Bob. Keep it online; don't send invites."),
    ("en_final_date_and_recipient", "Schedule Thursday at ten. Invite Bob and send invites online."),
    ("en_final_action", "Delete the draft, actually archive the draft instead. Keep the published report unchanged."),
    ("en_preserve_contrast_and_alternatives", "Reschedule for Thursday. Keep the room booking."),
])
def test_retracted_requests_or_missing_qualifications_fail(case_id, incorrect):
    sample = next(sample for sample in SAMPLES if sample["id"] == case_id)
    assert quality_failures(sample, incorrect)


def test_literal_landing_page_transcript_is_not_a_cleaned_result():
    sample = next(sample for sample in SAMPLES if sample["id"] == "en_landing_page_concise")
    assert "redundant_wording_not_condensed" in quality_failures(sample, sample["raw"])
