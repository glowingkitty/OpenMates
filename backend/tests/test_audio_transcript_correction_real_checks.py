"""Keep live correction probes sensitive to stale intent and omitted constraints."""
# contract-test-file: infrastructure

import pytest

from backend.scripts.test_audio_transcript_correction_real import SAMPLES, quality_failures


DETAILED_LANDING_CORRECTION = (
    "Also, I realized that the landing page still shows the old embed preview style. "
    "We must fix that, so the example embed preview that animates at the top shows the "
    "correct new layout. Ideally, we implement a long-term solution where the UI is "
    "automatically synchronized, so it will never be out of date with the web app. "
    "And of course, the embed preview shown on the landing page must also show an actual "
    "event image. We can use a real example chat event for that, or we can make one up. "
    "Also works."
)


@pytest.mark.parametrize(("case_id", "corrected"), [
    ("en_final_date_and_recipient",
     "Schedule the review for Thursday at ten. Invite Bob. Keep it online and don't send invites yet."),
    ("en_final_action", "Archive the draft. Keep the published report unchanged."),
    ("en_preserve_contrast_and_alternatives",
     "Don't cancel the meeting; reschedule it. Ideally Thursday, but Friday also works. Keep the room booking."),
    ("en_contextual_alignment_error",
     "Put the screenshot exactly in the horizontal center of the card, with equal empty space on the left and right."),
    ("en_contextual_technical_spelling",
     "Please commit the fix to GitHub and check the TypeScript errors in the pull request."),
    ("en_preserve_ambiguous_minimum", "Keep the minimum height, or remove it. I haven't decided yet."),
    ("en_preserve_ambiguous_number",
     "Use 15 or 50 pixels for the minimum height; I'm not sure which number I said."),
    ("en_preserve_deliberate_minimum",
     "Keep the preview at a minimum height of 300 pixels and a maximum height of 500 pixels, "
     "even when it has only two rows. The extra space is deliberately reserved for controls."),
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
    ("en_contextual_alignment_error", "The screenshot should be left-aligned with equal space on the left and right."),
    ("en_contextual_technical_spelling", "Please commit the fix to get hub and check the type script errors in the pull request."),
    ("en_preserve_ambiguous_minimum", "Remove the minimum height."),
    ("en_preserve_ambiguous_number", "Use 15 pixels for the minimum height."),
    ("en_preserve_deliberate_minimum", "Use a maximum height of 500 pixels and shrink to fit two rows and controls."),
])
def test_retracted_requests_or_missing_qualifications_fail(case_id, incorrect):
    sample = next(sample for sample in SAMPLES if sample["id"] == case_id)
    assert quality_failures(sample, incorrect)


def test_literal_landing_page_transcript_is_not_a_cleaned_result():
    sample = next(sample for sample in SAMPLES if sample["id"] == "en_landing_page_concise")
    assert any(issue.startswith("superseded_or_filler:")
               for issue in quality_failures(sample, sample["raw"]))


def test_detailed_landing_page_correction_is_accepted_without_a_word_budget():
    sample = next(sample for sample in SAMPLES if sample["id"] == "en_landing_page_concise")
    assert quality_failures(sample, DETAILED_LANDING_CORRECTION) == []


@pytest.mark.parametrize("detail", ["Ideally", "event image", "web app", "real example chat", "make one up"])
def test_shortening_cannot_drop_useful_landing_page_details(detail):
    sample = next(sample for sample in SAMPLES if sample["id"] == "en_landing_page_concise")
    assert detail in DETAILED_LANDING_CORRECTION
    shortened = DETAILED_LANDING_CORRECTION.replace(detail, "")
    assert any(issue.startswith("missing:") for issue in quality_failures(sample, shortened))


def test_landing_page_probe_accepts_equivalent_make_one_up_word_order():
    sample = next(sample for sample in SAMPLES if sample["id"] == "en_landing_page_concise")
    corrected = (
        "Update the animated embed preview at the top of the landing page to the new layout. "
        "Ideally, automatically sync its UI with the web app. Include an actual event image "
        "from a real example chat, or make one up."
    )
    assert quality_failures(sample, corrected) == []
