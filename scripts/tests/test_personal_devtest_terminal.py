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
