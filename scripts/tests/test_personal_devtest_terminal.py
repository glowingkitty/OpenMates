"""Privacy-safe screen classifiers for the Personal DevTest terminal benchmark."""

# contract-test-file: tooling

import os
import pty
import select
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import personal_devtest_terminal as benchmark
from scripts.personal_devtest_terminal import AuthEvidence, OpenEvidence, Terminal, recent_chat_cells


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


def auth_screen(status, composer="Ask anything, or /help", form=None):
    rows = screen(status)
    rows[38] = "              ╭ Message · Enter send · Alt+Enter newline ───────────╮"
    rows[39] = f"              │ {composer:<56} │"
    if form:
        rows[16] = f"     ╭ {form} ───────────╮"
    return rows


def test_authentication_uses_the_composer_after_the_footer_changes():
    assert benchmark.terminal_auth_state(auth_screen("Live updates delayed")) == "authenticated"
    assert benchmark.terminal_auth_state(auth_screen("Signed in", "Sign in to send messages · /login")) == "unconfirmed"
    assert benchmark.terminal_auth_state(auth_screen("Signed in", form="Unlock local vault")) == "vault_prompt"
    assert benchmark.terminal_auth_state(auth_screen("Signed in", form="Sign in to OpenMates")) == "login_prompt"


def test_failed_auth_attempt_preserves_typed_stage_and_redacts_screen():
    samples = []
    auth = AuthEvidence(samples, 2)

    def wait(_stage, observe):
        rows = auth_screen("Sign-in failed. Check your credentials and try again.", "Synthetic user text")
        assert not observe(rows)
        raise benchmark.TerminalWaitError("timeout", "restored session unreachable")

    with pytest.raises(RuntimeError):
        auth.wait(SimpleNamespace(wait=wait), "authenticated",
                  lambda rows: benchmark.terminal_auth_state(rows) == "authenticated")
    assert samples[0]["result"] == "failed"
    assert samples[0]["stage"] == "authenticated"
    assert samples[0]["wait_outcome"] == "timeout"
    assert samples[0]["last_status"] == "authentication_failed"
    assert "Synthetic" not in repr(samples)


def test_preexisting_transcript_does_not_count_as_a_new_open():
    startup = screen("Other", "‹ Back First synthetic chat Close", "First synthetic message")
    evidence = OpenEvidence([], 0, startup)
    assert not evidence.observe(startup)
    assert not evidence.observe(screen("Opening saved chat…", "‹ Back First synthetic chat Close", "First synthetic message"))
    assert evidence.observe(screen("Cached chat · refreshing", "‹ Back Second synthetic chat Close", "Second synthetic message"))


def test_wait_reconstructs_a_synchronized_marker_split_across_reads(monkeypatch):
    rows = auth_screen("Live updates delayed")
    chunks = iter([b"prefix\x1b[?20", b"26lnew frame"])
    monkeypatch.setattr(benchmark.os, "read", lambda *_: next(chunks))
    monkeypatch.setattr(benchmark.select, "select", lambda *_: ([1], [], []))
    monkeypatch.setattr(benchmark, "_latest_screen", lambda _output: (rows, 140, 44))
    terminal = Terminal(SimpleNamespace(poll=lambda: None), 1)

    terminal.wait("authenticated", lambda rows: benchmark.terminal_auth_state(rows) == "authenticated")
    assert terminal.rows == rows


def test_clean_quit_sends_native_ctrl_q_and_drains_the_pty():
    master, slave = pty.openpty()
    try:
        with subprocess.Popen(
            [sys.executable, "-c", "import os, tty; tty.setraw(0); os.write(1, b'ready'); "
                                   "assert os.read(0, 1) == bytes([17]); os.write(1, b' ' * 100000)"],
            stdin=slave, stdout=slave,
        ) as process:
            assert select.select([master], [], [], 3)[0]
            assert os.read(master, 5) == b"ready"
            Terminal(process, master).quit()
            assert process.returncode == 0
    finally:
        os.close(slave)
        os.close(master)


def startup_screen(labels, title=None, body=None, status="Live updates delayed"):
    rows = auth_screen(status)
    rows[2] = "╭ Recent chats · 1284 total ╮"
    if title:
        rows[2] += f"  ‹ Back › Chats › {title}   Share Download ⧉ Copy More Close"
    sidebar_width = 28
    for index in range(5, 28):
        label = labels[index - 5] if index - 5 < len(labels) else ""
        rows[index] = f"│ {label:<25}│"
    if title:
        rows[5] += " " * (rows[2].index("‹ Back") - sidebar_width) + "You"
    if body:
        rows[6] += " " * (rows[2].index("‹ Back") - sidebar_width) + body
    return rows


def test_startup_distinguishes_ten_actual_chat_rows_from_the_old_prefix(monkeypatch):
    elapsed = iter([1.015, 1.080])
    monkeypatch.setattr(benchmark.time, "monotonic", lambda: next(elapsed))
    samples = []
    startup = benchmark.StartupEvidence(samples, 1, None)
    startup.started = 1.0
    labels = [f"Synthetic topic {i}" for i in range(9)]
    startup.observe(startup_screen(labels + ["› ●9+ Synthetic topic 1", "Show more"]))
    assert samples[0]["selectable_prefix_at_ms"] == 15
    assert samples[0]["ten_distinct_chat_rows_at_ms"] is None
    assert samples[0]["max_distinct_chat_rows"] == 9
    startup.observe(startup_screen(labels + ["Tenth synthetic topic"]))
    assert samples[0]["ten_distinct_chat_rows_at_ms"] == 80
    assert "Synthetic" not in repr(samples)


def test_startup_requires_matching_title_and_message_body(monkeypatch):
    elapsed = iter([1.050, 1.100, 1.300, 1.301])
    monkeypatch.setattr(benchmark.time, "monotonic", lambda: next(elapsed))
    auth = SimpleNamespace(sample={})
    startup = benchmark.StartupEvidence([], 1, "Target synthetic title")
    startup.started = 1.0
    labels = [f"Synthetic topic {i}" for i in range(10)]
    startup.observe(startup_screen(labels, "Other synthetic title", "Some text"))
    startup.observe(startup_screen(labels, "Target synthetic title", "Thinking…"))
    assert startup.sample["last_open_first_readable_at_ms"] is None
    startup.observe(startup_screen(labels, "Target synthetic title", "Visible message"))
    startup.finish(auth)
    assert startup.sample["ten_distinct_chat_rows_at_ms"] == 50
    assert startup.sample["last_open_first_readable_at_ms"] == 300
    assert startup.sample["last_open_result"] == "late_after_ten_rows"
    assert "Target" not in repr(startup.sample)


def test_startup_reports_typed_timeout_after_an_authenticated_empty_list():
    auth = AuthEvidence([], 2)
    startup = benchmark.StartupEvidence([], 2, "Target synthetic title")
    startup.started = benchmark.time.monotonic()
    rows = startup_screen([], status="The server returned an invalid or unsupported response")
    auth.observe(rows)
    startup.observe(rows)
    auth.sample["wait_outcome"] = "timeout"
    startup.finish(auth)
    assert startup.sample["authenticated_at_ms"] is not None
    assert startup.sample["max_distinct_chat_rows"] == 0
    assert startup.sample["ten_distinct_chat_rows_result"] == "timeout"
    assert startup.sample["last_open_result"] == "timeout"
    assert auth.sample["last_status"] == "invalid_server_response"
    assert auth.sample["last_severity"] == "error"
    assert "Target" not in repr(startup.sample)


def test_real_click_timing_ignores_other_transcripts_appearing_after_selection():
    rows = startup_screen(["One", "Two"], "Prior title", "Some text")
    evidence = OpenEvidence([], 1, rows, "Selected title")
    assert not evidence.observe(startup_screen(["One", "Two"], "Other title", "Some text"))
    assert evidence.observe(startup_screen(["One", "Two"], "Selected title", "Some text"))
    assert evidence.sample["result"] == "readable"


def test_private_native_startup_probes_admit_only_fixed_bounded_fields():
    evidence = benchmark.startup_diagnostic_rows(
        b"private native stderr\n"
        b"OPENMATES_STARTUP_STAGE cold_sidebar_request ok 0\n"
        b"OPENMATES_STARTUP_STAGE cold_sidebar_wrappers protocol 120\n"
        b"OPENMATES_STARTUP_STAGE resume protocol 124 private suffix\n"
        b"OPENMATES_STARTUP_STAGE resume private_outcome 124\n"
        b"OPENMATES_STARTUP_STAGE invalid_stage ok 136\n"
        b"OPENMATES_STARTUP_STAGE reconcile ok 123456789012\n"
    )
    assert evidence == [
        {"stage": "cold_sidebar_request", "outcome": "ok", "elapsed_ms": 0},
        {"stage": "cold_sidebar_wrappers", "outcome": "protocol", "elapsed_ms": 120},
    ]
    assert len(benchmark.startup_diagnostic_rows(b"OPENMATES_STARTUP_STAGE resume ok 100\n" * 50)) == 40
