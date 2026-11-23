"""Short Discord push text helpers of scripts/discord_summary.py (tooling test, no network)."""
# contract-test-file: tooling

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord_summary as ds  # noqa: E402

BAD = ("Check production health now: ✅ Production is healthy: emails are going out (Brevo accepted sends at "
       "12:14 and 12:34 UTC, Brevo API reachable from prod, no send errors); both alerts were false alarms - "
       "Brevo's events-stats API timed out 12:28-12:40")
GOOD = "Production is healthy: both alerts were false alarms (Brevo stats timeout, runner error). No fix needed."


def test_good_example_fits_and_bad_example_does_not():
    assert ds.counted_length(GOOD) <= ds.SUMMARY_MAX < ds.counted_length(BAD)


def test_clean_text_strips_icons_markdown_ids_and_list_markers():
    text = "✅ **Done** with `fix` and [the docs](https://example.org/x): see TASK-119, abc1234ef, chat 0c808c39-d681-4369-99a8-8cb7cce7056d."
    cleaned = ds.clean_text(text)
    assert cleaned == "Done with fix and the docs."
    assert "✅" not in cleaned and "TASK" not in cleaned and "abc1234ef" not in cleaned and "0c808c39" not in cleaned
    assert ds.clean_text("- one\n- two\n3. three") == "one two three"
    assert ds.clean_text("❓ ✅ Both icons") == "Both icons"
    assert ds.clean_text("# Heading text") == "Heading text"


def test_clean_text_keeps_normal_words_and_links():
    assert ds.clean_text("Deploy facade changes to dev") == "Deploy facade changes to dev"
    link = "https://example.org/a/b?x=1"
    assert link in ds.clean_text(f"Video {link} ready")


def test_title_prefix_repeated_in_the_text_is_dropped():
    assert ds.clean_text("Check production health now: Production is healthy.", "Check production health now") == \
        "Production is healthy."


def test_title_is_shortened_at_a_word_boundary_without_task_id():
    title = ds.short_title("TASK-1063: Project encryption architecture review for agentic coding")
    assert len(title) <= ds.TITLE_MAX and title.endswith("…") and title.startswith("Project encryption")
    assert " …" not in title and ds.short_title("") == "unnamed chat"


def test_links_count_as_one_character_and_are_never_cut():
    link = "https://example.org/" + "a" * 200
    assert ds.counted_length(f"Proof {link}") == len("Proof ") + 1
    assert link in ds.cut(f"Proof {link} " + "word " * 60, 60)


def test_fit_accepts_short_text_unchanged():
    assert ds.fit(GOOD, ds.SUMMARY_MAX, rejections=0) == GOOD


@pytest.mark.parametrize("rejections", [0, 1])
def test_fit_rejects_with_a_rewrite_instruction_before_any_fallback(rejections):
    with pytest.raises(ds.SummaryTooLong, match="rewrite it in under 110 characters, one sentence"):
        ds.fit(BAD, ds.SUMMARY_MAX, rejections=rejections, shorten=lambda *_: pytest.fail("model called early"))


def test_fallback_chain_model_then_word_boundary_cut():
    notes = []
    assert ds.fit(BAD, 110, rejections=2, shorten=lambda t, n: "**Production** is healthy; false alarms.",
                  note=notes.append) == "Production is healthy; false alarms."
    assert "fallback model" in notes[0]

    def failing(*_):
        raise ds.ShortenFailed("offline")

    cut = ds.fit(BAD, 110, rejections=2, shorten=failing, note=notes.append)
    assert len(cut) <= 110 and cut.endswith("…") and "offline" in notes[-1]
    assert ds.fit(BAD, 110, rejections=5) == ds.cut(BAD, 110)  # no model configured: cut
    still_long = ds.fit(BAD, 110, rejections=2, shorten=lambda t, n: BAD)
    assert len(still_long) <= 110 and still_long.endswith("…")


def test_alert_is_one_icon_one_line_within_the_limit():
    text = ds.alert("🚨", "Prod email failing: " + "Brevo account check timed out. " * 20)
    assert text.startswith("🚨 ") and text.count("🚨") == 1 and len(text) <= ds.ALERT_MAX and text.endswith("…")
    assert ds.alert("✅", "✅ Prod email recovered.") == "✅ Prod email recovered."
