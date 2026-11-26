"""Privacy-safe screen classifiers for the Personal DevTest terminal benchmark."""

# contract-test-file: tooling

from types import SimpleNamespace

from scripts.personal_devtest_terminal import OpenEvidence, recent_chat_cells


def screen(status, header="", body=""):
    rows = [""] * 44
    rows[2] = f"╭ Recent chats · 1284 total ╮  {header}"
    rows[3] = "│ ＋ New chat               │"
    rows[4] = "│                           │"
    rows[5] = f"│ › Synthetic title         │ {body}"
    rows[-1] = f" {status}  │  Ctrl+K actions · F1 help"
    return rows


def test_sidebar_click_targets_the_displayed_row_with_one_based_terminal_coordinates():
    assert recent_chat_cells(screen("Signed in")) == (True, [(6, 3)])


def test_open_evidence_records_milestones_without_transcript_or_title():
    samples = []
    evidence = OpenEvidence(samples, 0)
    assert not evidence.observe(screen("Opening saved chat…"))
    rendered = screen("Cached chat · refreshing", "‹ Back Synthetic title Close", "Synthetic transcript text")
    assert evidence.observe(rendered)
    evidence.finish(SimpleNamespace(rows=rendered))
    assert evidence.sample["result"] == "readable"
    assert evidence.sample["selection_received_ms"] <= evidence.sample["chat_header_ms"]
    assert evidence.sample["chat_header_ms"] <= evidence.sample["first_readable_message_ms"]
    assert "Synthetic" not in repr(samples)


def test_empty_chat_does_not_qualify_as_a_readable_message():
    evidence = OpenEvidence([], 0)
    assert evidence.observe(screen("This saved chat has no messages", "‹ Back Synthetic title Close"))
    assert evidence.sample["result"] == "empty_chat"
    assert "first_readable_message_ms" not in evidence.sample


def test_background_status_without_open_header_is_a_timeout():
    evidence = OpenEvidence([], 0)
    rows = screen("Live updates delayed", body="Synthetic transcript text")
    assert not evidence.observe(rows)
    evidence.finish(SimpleNamespace(rows=rows))
    assert evidence.sample["result"] == "timeout"
    assert evidence.sample["last_status"] == "live_updates_delayed"
    assert "chat_header_ms" not in evidence.sample
