#!/usr/bin/env python3
"""Measure the real native TUI on the populated development account."""

import argparse
import base64
import errno
import fcntl
import hmac
import json
import os
from pathlib import Path
import pty
import re
import select
import struct
import subprocess
import tempfile
import termios
import time
from contextlib import contextmanager

if __package__:
    from .cli_video_capture import CliCaptureError, _latest_screen
else:
    from cli_video_capture import CliCaptureError, _latest_screen

API_ORIGIN = "https://api.dev.openmates.org"
MAX_FRAME_BYTES = 4 * 1024 * 1024
FRAME_END = b"\x1b[?2026l"
COMPOSER_PANEL = re.compile(
    r"╭ (?:Message · Enter send · Alt\+Enter newline"
    r"|Cached chat · (?:offline|refreshing) · draft preserved) ─+╮"
)
AUTH_FORM = re.compile(r"^\s*╭ (Sign in to OpenMates|Unlock local vault) ─+╮")
AUTH_COMPOSER = {"Ask anything, or /help", "Ask a follow-up, use @file, or type /help"}


def credentials():
    values = [
        os.environ.pop(f"OPENMATES_PERSONAL_TEST_ACOUNT_{key}", "")
        for key in ("EMAIL", "PASSWORD", "OTP_KEY")
    ]
    if not all(value and value.isprintable() for value in values):
        raise ValueError("Personal DevTest repository secrets are required")
    return values


def totp(key):
    key = key.replace(" ", "").upper()
    secret = base64.b32decode(key + "=" * (-len(key) % 8))
    now = time.time()
    if now % 30 >= 24:
        time.sleep(31 - now % 30)
    digest = hmac.digest(secret, struct.pack(">Q", int(time.time() // 30)), "sha1")
    offset = digest[-1] & 15
    return f"{(int.from_bytes(digest[offset:offset + 4], 'big') & 0x7fffffff) % 1000000:06d}"


class TerminalWaitError(RuntimeError):
    def __init__(self, outcome, message):
        super().__init__(message)
        self.outcome = outcome


class Terminal:
    def __init__(self, process, master):
        self.process = process
        self.master = master
        self.output = bytearray()
        self.rows = []

    def send(self, text):
        os.write(self.master, text.encode())

    def click(self, row, column):
        self.send(f"\x1b[<0;{column};{row}M\x1b[<0;{column};{row}m")

    def wait(self, label, accept, seconds=45):
        deadline = time.monotonic() + seconds
        if self.rows and self.process.poll() is None and accept(self.rows):
            return time.monotonic()
        pty_closed = False
        while time.monotonic() < deadline and self.process.poll() is None:
            if not select.select([self.master], [], [], 0.1)[0]:
                continue
            try:
                incoming = os.read(self.master, 65536)
            except OSError as exc:
                if exc.errno != errno.EIO:
                    raise
                incoming = b""
            if not incoming:
                pty_closed = True
                break
            boundary = max(0, len(self.output) - len(FRAME_END) + 1)
            self.output.extend(incoming)
            if len(self.output) > MAX_FRAME_BYTES:
                raise RuntimeError("Native terminal output exceeded the benchmark limit")
            if self.output.find(FRAME_END, boundary) < 0:
                continue
            try:
                rows, _, _ = _latest_screen(self.output.decode(errors="replace"))
            except CliCaptureError:
                continue
            self.rows = rows
            if accept(rows):
                return time.monotonic()
        sidebar_visible, chat_cells = recent_chat_cells(self.rows)
        outcome = "timeout"
        if self.process.poll() is not None:
            outcome = "process_exited"
        elif pty_closed:
            outcome = "pty_closed"
        raise TerminalWaitError(
            outcome, f"Native terminal did not reach {label} "
            f"(sidebar_visible={sidebar_visible}, visible_chat_rows={len(chat_cells)}, "
            f"auth={terminal_auth_state(self.rows)}, status={terminal_status(self.rows)})"
        )

    def quit(self):
        """Use the native quit command and drain output until the process exits."""
        if self.process.poll() is not None:
            raise RuntimeError("Native terminal exited before clean quit")
        self.send("\x11")  # Ctrl+Q is unconditional, including during a read.
        deadline = time.monotonic() + 8
        while self.process.poll() is None and time.monotonic() < deadline:
            if not select.select([self.master], [], [], 0.1)[0]:
                continue
            try:
                if not os.read(self.master, 65536):
                    break
            except OSError as exc:
                if exc.errno != errno.EIO:
                    raise
                break
        try:
            exit_code = self.process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise RuntimeError("Native terminal did not finish clean quit") from None
        if exit_code != 0:
            raise RuntimeError(f"Native terminal clean quit failed (exit_code={exit_code})")


@contextmanager
def open_tui(binary, state):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 44, 140, 0, 0))
    try:
        with subprocess.Popen(
            [str(binary), "--api-url", API_ORIGIN, "--state-dir", str(state),
             "--encrypted-vault", "tui"],
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
            env={**os.environ, "TERM": "xterm-256color"},
        ) as process:
            os.close(slave)
            slave = None
            try:
                yield Terminal(process, master)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    finally:
        os.close(master)
        if slave is not None:
            os.close(slave)


def terminal_status(rows):
    status = rows[-1].strip().lower() if rows else ""
    for prefix, label in (
        ("signed in", "signed_in"),
        ("signed out", "signed_out"),
        ("submitting", "submitting"),
        ("sign-in failed", "authentication_failed"),
        ("unlock the existing credential store", "vault_locked"),
        ("enter your two-factor authentication code", "two_factor_required"),
        ("verify this device or sign in again", "verification_required"),
        ("opening saved chat", "opening"),
        ("this saved chat has no messages", "empty_chat"),
        ("chat refreshed", "chat_refreshed"),
        ("cached chat · refreshing", "cached_refreshing"),
        ("cached chat · offline", "cached_offline"),
        ("canonical completion recovery pending", "recovery_pending"),
        ("response recovery pending", "recovery_pending"),
        ("offline", "offline"),
        ("live updates delayed", "live_updates_delayed"),
        ("encrypted data could not be authenticated", "encrypted_data_invalid"),
        ("the server returned an invalid or unsupported response", "invalid_server_response"),
        ("this operation is not available", "forbidden"),
        ("this session expired", "expired"),
        ("the operation was cancelled", "cancelled"),
        ("the local operation could not be completed", "local_error"),
    ):
        if status.startswith(prefix):
            return label
    return "other"


def terminal_auth_state(rows):
    for row in rows:
        if match := AUTH_FORM.match(row):
            return "vault_prompt" if match[1] == "Unlock local vault" else "login_prompt"

    # Only the authenticated Chats composer renders either placeholder.
    # The greeting, cached sidebar and sticky footer can all precede admission.
    for index in range(max(0, len(rows) - 11), len(rows) - 2):
        if COMPOSER_PANEL.search(rows[index]):
            cells = rows[index + 1].rsplit("│", 2)
            if len(cells) == 3 and cells[1].strip() in AUTH_COMPOSER:
                return "authenticated"
    return "unconfirmed"


class AuthEvidence:
    """Track launch stages without serializing terminal text or credentials."""

    def __init__(self, samples, attempt):
        self.started = time.monotonic()
        self.sample = {
            "attempt": attempt,
            "mode": "login" if attempt == 0 else "vault_relaunch",
            "stage": "launch",
            "milestones_ms": {},
            "screen_transitions": [],
            "result": "failed",
        }
        samples.append(self.sample)

    def observe(self, rows):
        state, status = terminal_auth_state(rows), terminal_status(rows)
        transitions = self.sample["screen_transitions"]
        if len(transitions) < 20 and (
            not transitions or (transitions[-1]["state"], transitions[-1]["status"]) != (state, status)
        ):
            transitions.append({
                "state": state, "status": status,
                "at_ms": self.elapsed(),
            })
        self.sample["last_state"] = state
        self.sample["last_status"] = status

    def elapsed(self):
        return round((time.monotonic() - self.started) * 1000)

    def wait(self, terminal, stage, accept):
        self.sample["stage"] = stage

        def observe(rows):
            self.observe(rows)
            return accept(rows)

        try:
            reached = terminal.wait(stage, observe)
        except TerminalWaitError as error:
            self.sample["wait_outcome"] = error.outcome
            raise
        self.sample["milestones_ms"][stage] = round((reached - self.started) * 1000)
        return reached

    def quit(self, terminal):
        self.sample["stage"] = "clean_exit"
        terminal.quit()
        self.sample["milestones_ms"]["clean_exit"] = self.elapsed()
        self.sample["result"] = "passed"


def recent_chat_cells(rows):
    for top, row in enumerate(rows):
        if row.startswith("╭ Recent chats ") and "╮" in row:
            break
    else:
        return False, []
    # The first two rows inside the panel are New chat and the gap above rows.
    # The selected marker is optional because saved-memory items are hidden here.
    cells = []
    for index, row in enumerate(rows[top + 3:], start=top + 4):
        if not row.startswith("│"):
            break
        panel = row.split("│", 2)
        if len(panel) == 3 and panel[1].strip(" ›"):
            cells.append((index, 3))
    return True, cells


def recent(rows):
    return len(recent_chat_cells(rows)[1]) >= 3


def transcript_header(rows):
    # The main view starts below the fixed two-row terminal toolbar.
    if len(rows) <= 2:
        return None
    row = rows[2]
    if "‹ Back" in row and row.rstrip().endswith("Close"):
        return 2, row.index("‹ Back")
    return None


def readable_chat(rows):
    header = transcript_header(rows)
    if header is None:
        return False
    index, column = header
    return any(re.search(r"\w", line[column:]) for line in rows[index + 2:-10])


class OpenEvidence:
    """Capture first-paint milestones without exporting any account text."""

    def __init__(self, samples, candidate_index, rows=()):
        self.started = time.monotonic()
        self.preexisting_header = self.header_text(rows)
        self.sample = {"candidate_index": candidate_index, "status_transitions": []}
        samples.append(self.sample)

    @staticmethod
    def header_text(rows):
        header = transcript_header(rows)
        if header is None:
            return None
        index, column = header
        return rows[index][column:].rstrip()

    def observe(self, rows):
        elapsed = round((time.monotonic() - self.started) * 1000)
        status = terminal_status(rows)
        transitions = self.sample["status_transitions"]
        if len(transitions) < 20 and (not transitions or transitions[-1]["status"] != status):
            transitions.append({"status": status, "at_ms": elapsed})
        if status == "opening":
            self.sample.setdefault("selection_received_ms", elapsed)
        header = self.header_text(rows)
        if header is None:
            self.preexisting_header = None
            return False
        if header == self.preexisting_header:
            return False
        self.sample.setdefault("chat_header_ms", elapsed)
        if readable_chat(rows):
            self.sample["first_readable_message_ms"] = elapsed
            self.sample["result"] = "readable"
            return True
        if status == "empty_chat":
            self.sample["result"] = "empty_chat"
            return True
        return False

    def finish(self, terminal):
        self.sample.setdefault("result", "timeout")
        self.sample["last_status"] = terminal_status(terminal.rows)
        self.sample["visible_chat_rows"] = len(recent_chat_cells(terminal.rows)[1])


def enter_authenticated(terminal, evidence, form, input_text):
    evidence.wait(terminal, form, lambda rows: terminal_auth_state(rows) == form)
    evidence.sample["stage"] = "submit_credentials"
    started = time.monotonic()
    terminal.send(input_text())
    evidence.sample["milestones_ms"]["submit_credentials"] = evidence.elapsed()
    evidence.wait(terminal, "authenticated", lambda rows: terminal_auth_state(rows) == "authenticated")
    evidence.sample["stage"] = "recent_rows"
    if not recent_chat_cells(terminal.rows)[0]:
        terminal.send("\x02")
    shown = evidence.wait(terminal, "recent_rows", recent)
    return round((shown - started) * 1000)


def measure(binary, private_output):
    metrics = {
        "auth_attempts": [],
        "vault_unlock_to_recent_rows_ms": [],
        "select_to_visible_message_ms": [],
        "open_samples": [],
    }
    try:
        email, password, key = credentials()
        with tempfile.TemporaryDirectory(prefix="native-state-", dir=private_output) as state:
            evidence = AuthEvidence(metrics["auth_attempts"], 0)
            with open_tui(binary, Path(state)) as terminal:
                enter_authenticated(terminal, evidence, "login_prompt",
                                    lambda: email + "\t" + password + "\t" + totp(key) + "\t\r")
                evidence.quit(terminal)

            candidate_index = 0
            for attempt in range(1, 4):
                auth = AuthEvidence(metrics["auth_attempts"], attempt)
                with open_tui(binary, Path(state)) as terminal:
                    elapsed = enter_authenticated(terminal, auth, "vault_prompt", lambda: password + "\t\r")
                    metrics["vault_unlock_to_recent_rows_ms"].append(elapsed)

                    auth.sample["stage"] = "open_chat"
                    while True:
                        _, visible_cells = recent_chat_cells(terminal.rows)
                        if candidate_index >= len(visible_cells):
                            raise RuntimeError("Ran out of visible saved conversations for three timing samples")
                        selection = visible_cells[candidate_index]
                        evidence = OpenEvidence(metrics["open_samples"], candidate_index, terminal.rows)
                        candidate_index += 1
                        terminal.click(*selection)
                        try:
                            terminal.wait("readable or explicitly empty saved chat", evidence.observe)
                        finally:
                            evidence.finish(terminal)
                        if evidence.sample["result"] == "readable":
                            metrics["select_to_visible_message_ms"].append(evidence.sample["first_readable_message_ms"])
                            break
                    auth.quit(terminal)
    finally:
        (private_output / "terminal-timings.json").write_text(json.dumps(metrics) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("private_output", type=Path)
    args = parser.parse_args()
    measure(args.binary.resolve(strict=True), args.private_output.resolve(strict=True))


if __name__ == "__main__":
    main()

