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
STARTUP_SECONDS = 45
SETTLEMENT_SECONDS = 8
UNREAD_PREFIX = re.compile(r"^●[1-9]\+?\s+")
SIDEBAR_CONTROLS = {"show more", "load more", "new chat", "＋ new chat"}
STARTUP_STAGE_LINE = re.compile(rb"OPENMATES_STARTUP_STAGE ([a-z_]+) ([a-z_]+) ([0-9]{1,10})")
STARTUP_STAGE_NAMES = {
    "selector_request", "selector_decode", "cold_sidebar_request", "cold_sidebar_decode",
    "cold_sidebar_envelope", "cold_sidebar_id", "cold_sidebar_wrappers", "cold_sidebar_timestamp",
    "cold_sidebar_render", "cold_sidebar_persist", "cold_sidebar_projection", "cold_sidebar_publish",
    "resume", "reconcile", "hydrate", "live_canonical_read", "opened_recorded", "open_selection_completed",
    "list_convert_id", "list_convert_status", "list_convert_title", "list_convert_created_at",
    "list_convert_updated_at", "list_convert_messages_version", "list_convert_unread_count",
    "list_convert_pinned", "list_convert_archived", "list_convert_has_draft", "list_convert_footer",
    "list_convert_other", "list_meta_sub_chat_settings", "list_meta_shared_by_others",
    "list_meta_last_visible_message", "list_meta_app", "list_meta_sub_chat_wait",
    "list_meta_sub_chat_report", "list_meta_parent", "list_meta_is_sub_chat", "list_meta_is_shared",
    "list_meta_is_private", "list_meta_is_hidden", "list_meta_last_message_at", "list_meta_last_edited_at",
    "list_meta_budget_limit", "list_meta_budget_spent", "list_meta_draft_version", "list_meta_team",
    "list_meta_key", "list_meta_icon", "list_meta_active_focus", "list_meta_draft_preview",
}
STARTUP_STAGE_OUTCOMES = {
    "ok", "protocol", "crypto", "offline", "io", "cancelled", "denied", "locked", "invalid",
    "conflict", "other",
}
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
    def __init__(self, process, master, diagnostics_fd=None):
        self.process = process
        self.master = master
        self.diagnostics_fd = diagnostics_fd
        self.output = bytearray()
        self.rows = []

    def send(self, text):
        os.write(self.master, text.encode())

    def click(self, row, column):
        self.send(f"\x1b[<0;{column};{row}M\x1b[<0;{column};{row}m")

    def diagnostic_position(self):
        return os.fstat(self.diagnostics_fd).st_size

    def diagnostics_after(self, position):
        # The child still writes to the same file descriptor. Positional reads
        # observe the trace without seeking or interfering with its writes.
        raw = os.pread(self.diagnostics_fd, 128 * 1024, position)
        return startup_diagnostic_rows(raw[:raw.rfind(b"\n") + 1])

    def wait(self, label, accept, seconds=45, observe_idle=False):
        deadline = time.monotonic() + seconds
        if self.rows and self.process.poll() is None and accept(self.rows):
            return time.monotonic()
        pty_closed = False
        while time.monotonic() < deadline and self.process.poll() is None:
            if not select.select([self.master], [], [], 0.1)[0]:
                if observe_idle and accept(self.rows):
                    return time.monotonic()
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


def startup_diagnostic_rows(raw):
    """Accept only complete, allowlisted records from private native stderr."""
    rows = []
    for line in raw.split(b"\n"):
        if not (match := STARTUP_STAGE_LINE.fullmatch(line)):
            continue
        stage, outcome = (part.decode("ascii") for part in match.groups()[:2])
        if stage in STARTUP_STAGE_NAMES and outcome in STARTUP_STAGE_OUTCOMES:
            rows.append({"stage": stage, "outcome": outcome, "elapsed_ms": int(match[3])})
            if len(rows) == 40:
                break
    return rows


@contextmanager
def open_tui(binary, state, diagnostics):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 44, 140, 0, 0))
    try:
        with tempfile.TemporaryFile(dir=state) as diagnostics_stream:
            try:
                with subprocess.Popen(
                    [str(binary), "--api-url", API_ORIGIN, "--state-dir", str(state),
                     "--encrypted-vault", "tui"],
                    stdin=slave, stdout=slave, stderr=diagnostics_stream, start_new_session=True,
                    env={**os.environ, "TERM": "xterm-256color",
                         "OPENMATES_TEST_STARTUP_PHASE_DIAGNOSTIC": "1"},
                ) as process:
                    os.close(slave)
                    slave = None
                    try:
                        yield Terminal(process, master, diagnostics_stream.fileno())
                    finally:
                        if process.poll() is None:
                            process.terminate()
                            try:
                                process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait()
            finally:
                diagnostics_stream.seek(0)
                raw = diagnostics_stream.read(128 * 1024)
                diagnostics.extend(startup_diagnostic_rows(raw[:raw.rfind(b"\n") + 1]))
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
        ("showing all cached messages", "cache_settled"),
        ("selected chat is no longer available", "selection_unavailable"),
        ("the requested item is unavailable", "selection_unavailable"),
        ("the object changed", "conflict"),
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


def status_severity(status):
    errors = {
        "authentication_failed", "vault_locked", "two_factor_required", "verification_required",
        "encrypted_data_invalid", "invalid_server_response", "forbidden", "expired", "cancelled",
        "local_error", "selection_unavailable", "conflict",
    }
    if status in errors:
        return "error"
    if status in {"offline", "cached_offline", "recovery_pending", "live_updates_delayed"}:
        return "warning"
    return "info"


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
            "stage_durations_ms": {},
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
                "state": state, "status": status, "severity": status_severity(status),
                "at_ms": self.elapsed(),
            })
        self.sample["last_state"] = state
        self.sample["last_status"] = status
        self.sample["last_severity"] = status_severity(status)

    def elapsed(self):
        return round((time.monotonic() - self.started) * 1000)

    def wait(self, terminal, stage, accept, startup=None):
        self.sample["stage"] = stage

        began = time.monotonic()

        def observe(rows):
            self.observe(rows)
            if startup is not None:
                startup.observe(rows)
            return accept(rows)

        try:
            reached = terminal.wait(stage, observe)
        except TerminalWaitError as error:
            self.sample["wait_outcome"] = error.outcome
            raise
        finally:
            self.sample["stage_durations_ms"][stage] = round((time.monotonic() - began) * 1000)
        self.sample["milestones_ms"][stage] = round((reached - self.started) * 1000)
        return reached

    def quit(self, terminal):
        self.sample["stage"] = "clean_exit"
        terminal.quit()
        self.sample["milestones_ms"]["clean_exit"] = self.elapsed()
        self.sample["result"] = "passed"


def recent_chat_entries(rows):
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
            label, unread = UNREAD_PREFIX.subn("", panel[1].strip(" ›"))
            label = " ".join(label.split())
            if label and label.casefold() not in SIDEBAR_CONTROLS:
                cells.append((index, 3, label, bool(unread)))
    return True, cells


def recent_chat_cells(rows):
    visible, entries = recent_chat_entries(rows)
    return visible, [(row, column) for row, column, _, _ in entries]


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


def readable_startup_transcript(rows):
    header = transcript_header(rows)
    if header is None:
        return False
    index, column = header
    previous = False
    for line in rows[index + 2:-10]:
        body = line[column:].strip()
        if not body or body.startswith("· "):
            previous = False
        elif body not in {"Thinking…", "Thought process available in chat export", "● Responding…"}:
            if previous and re.search(r"\w", body):
                return True
            previous = True
    return False


def transcript_title(rows):
    header = transcript_header(rows)
    if header is None:
        return None
    index, column = header
    title = rows[index][column:].removeprefix("‹ Back").removesuffix("Close").strip()
    # Production lays out these fixed controls separately from the title.
    title = re.sub(r"\s+Share\s+Download\s+⧉\s+Copy\s+More$", "", title).strip()
    return " ".join(title.removeprefix("› Chats › ").split()) or None


def same_startup_title(expected, actual):
    if not expected or not actual:
        return False
    # Opening the sidebar can clip the title by one terminal cell.
    shorter, longer = sorted((expected, actual), key=len)
    return expected == actual or len(shorter) >= 40 and len(longer) - len(shorter) <= 1 and longer.startswith(shorter)


class StartupEvidence:
    """Independent startup milestones drawn from actual synchronized PTY paints."""

    def __init__(self, samples, attempt, expected):
        self.started = None
        self.expected = expected  # Screen identity exists only in memory.
        self.sample = {
            "attempt": attempt,
            "mode": "login" if attempt == 0 else "vault_relaunch",
            "selectable_prefix_at_ms": None,
            "ten_distinct_chat_rows_at_ms": None,
            "last_open_first_readable_at_ms": None,
            "authenticated_at_ms": None,
            "sidebar_requested_at_ms": None,
            "sidebar_visible_at_ms": None,
            "max_distinct_chat_rows": 0,
            "target_seeded": expected is not None,
            "native_stages": [],
            "ten_distinct_chat_rows_result": "not_observed",
            "last_open_result": "unseeded" if expected is None else "not_observed",
        }
        samples.append(self.sample)

    def elapsed(self):
        return round((time.monotonic() - self.started) * 1000)

    def observe(self, rows):
        if self.started is None or terminal_auth_state(rows) != "authenticated":
            return
        elapsed = self.elapsed()
        if elapsed > STARTUP_SECONDS * 1000:
            return
        if self.sample["authenticated_at_ms"] is None:
            self.sample["authenticated_at_ms"] = elapsed
        visible, entries = recent_chat_entries(rows)
        if visible and self.sample["sidebar_visible_at_ms"] is None:
            self.sample["sidebar_visible_at_ms"] = elapsed
        labels = {label.casefold() for _, _, label, _ in entries}
        # A badge may clip a few trailing cells. Do not count a clipped title
        # separately when another row displays its longer prefix match.
        longest_first = sorted(labels, key=len, reverse=True)
        distinct = sum(not any(other.startswith(label) and 0 < len(other) - len(label) <= 5
                               for other in longest_first[:index])
                       for index, label in enumerate(longest_first))
        self.sample["max_distinct_chat_rows"] = max(self.sample["max_distinct_chat_rows"], distinct)
        if len(entries) >= 3 and self.sample["selectable_prefix_at_ms"] is None:
            self.sample["selectable_prefix_at_ms"] = elapsed
        if distinct >= 10 and self.sample["ten_distinct_chat_rows_at_ms"] is None:
            self.sample["ten_distinct_chat_rows_at_ms"] = elapsed
        if (self.sample["last_open_first_readable_at_ms"] is None
                and same_startup_title(self.expected, transcript_title(rows)) and readable_startup_transcript(rows)):
            self.sample["last_open_first_readable_at_ms"] = elapsed

    def await_extended(self, terminal, auth):
        def observe(rows):
            auth.observe(rows)
            self.observe(rows)
            return self.sample["ten_distinct_chat_rows_at_ms"] is not None and (
                self.expected is None or self.sample["last_open_first_readable_at_ms"] is not None
            )

        remaining = max(0, STARTUP_SECONDS - (time.monotonic() - self.started))
        began = time.monotonic()
        try:
            terminal.wait("extended startup evidence", observe, seconds=remaining)
        except TerminalWaitError as error:
            self.sample["wait_outcome"] = error.outcome
            if error.outcome != "timeout":
                raise
        finally:
            auth.sample["stage_durations_ms"]["extended_startup"] = round((time.monotonic() - began) * 1000)

    def finish(self, auth):
        self.sample.setdefault("wait_outcome", auth.sample.get("wait_outcome"))
        failure = self.sample["wait_outcome"] or (
            "timeout" if self.started is not None and self.elapsed() >= STARTUP_SECONDS * 1000 else "not_observed"
        )
        ten = self.sample["ten_distinct_chat_rows_at_ms"]
        selected = self.sample["last_open_first_readable_at_ms"]
        self.sample["ten_distinct_chat_rows_result"] = "ready" if ten is not None else failure
        if self.expected is None:
            outcome = "unseeded"
        elif selected is None:
            outcome = failure
        else:
            outcome = "late_after_ten_rows" if ten is not None and selected > ten else "readable"
        self.sample["last_open_result"] = outcome


class OpenEvidence:
    """Capture first-paint milestones without exporting any account text."""

    def __init__(self, samples, candidate_index, rows=(), expected_prefix=None):
        self.started = time.monotonic()
        self.expected_prefix = expected_prefix
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
            transitions.append({"status": status, "severity": status_severity(status), "at_ms": elapsed})
        if status == "opening":
            self.sample.setdefault("selection_received_ms", elapsed)
        header = self.header_text(rows)
        if header is None:
            self.preexisting_header = None
            return False
        if header == self.preexisting_header:
            return False
        if self.expected_prefix is not None and not (transcript_title(rows) or "").startswith(self.expected_prefix):
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
        self.sample["last_severity"] = status_severity(self.sample["last_status"])
        self.sample["visible_chat_rows"] = len(recent_chat_cells(terminal.rows)[1])


def enter_authenticated(terminal, evidence, startup, form, input_text):
    try:
        evidence.wait(terminal, form, lambda rows: terminal_auth_state(rows) == form)
        evidence.sample["stage"] = "submit_credentials"
        payload = input_text()
        startup.started = time.monotonic()
        terminal.send(payload)
        evidence.sample["milestones_ms"]["submit_credentials"] = evidence.elapsed()
        evidence.wait(terminal, "authenticated", lambda rows: terminal_auth_state(rows) == "authenticated", startup)
        evidence.sample["stage"] = "recent_rows"
        if not recent_chat_cells(terminal.rows)[0]:
            startup.sample["sidebar_requested_at_ms"] = startup.elapsed()
            terminal.send("\x02")
        shown = evidence.wait(terminal, "recent_rows", recent, startup)
        elapsed = round((shown - startup.started) * 1000)
        startup.await_extended(terminal, evidence)
        return elapsed
    finally:
        startup.finish(evidence)


def wait_for_recorded_open(terminal, position, diagnostics, *, require_completion=False):
    """Wait for a durable server acknowledgment before qualifying the next launch."""
    began = time.monotonic()
    outcome = None

    def observe(_rows):
        nonlocal outcome
        stages = terminal.diagnostics_after(position)
        recorded = any(event["stage"] == "opened_recorded" and event["outcome"] == "ok" for event in stages)
        completed = any(event["stage"] == "open_selection_completed" for event in stages)
        if recorded and (completed or not require_completion):
            outcome = "recorded"
        elif completed:
            outcome = "not_recorded"
        return outcome is not None

    try:
        terminal.wait("record selected chat open", observe, seconds=SETTLEMENT_SECONDS, observe_idle=True)
    except TerminalWaitError as error:
        outcome = error.outcome
        if error.outcome != "timeout":
            raise
    finally:
        diagnostics["recorded_open_outcome"] = outcome
        diagnostics["recorded_open_wait_ms"] = round((time.monotonic() - began) * 1000)
    return outcome


def seed_last_open(terminal, diagnostics):
    _, entries = recent_chat_entries(terminal.rows)
    current = transcript_title(terminal.rows)
    # Leave the first legacy candidate alone. Avoid opening unread chats,
    # because the native view can mark a visible newest reply as read.
    for row, column, label, unread in entries[1:] + entries[:1]:
        if unread or (current and current.startswith(label)):
            continue
        if sum(entry[2].casefold() == label.casefold() for entry in entries) != 1:
            continue
        position = terminal.diagnostic_position()
        terminal.click(row, column)
        break
    else:
        diagnostics["result"] = "no_distinct_candidate"
        return None
    def selected(rows):
        title = transcript_title(rows)
        return bool(title and title.startswith(label) and (
            readable_startup_transcript(rows) or terminal_status(rows) == "empty_chat"
        ))

    try:
        terminal.wait("deliberate startup seed", selected)
    except TerminalWaitError as error:
        diagnostics["result"] = error.outcome
        if error.outcome != "timeout":
            raise
        return None
    title = transcript_title(terminal.rows)
    readable = readable_startup_transcript(terminal.rows)
    diagnostics["result"] = "readable" if readable else "empty_chat"
    recorded = wait_for_recorded_open(terminal, position, diagnostics)
    return title if readable and recorded == "recorded" else None


def measure(binary, private_output):
    metrics = {
        "auth_attempts": [],
        "startup_samples": [],
        "startup_seed": {"result": "not_attempted"},
        "vault_unlock_to_recent_rows_ms": [],
        "select_to_visible_message_ms": [],
        "open_samples": [],
    }
    try:
        email, password, key = credentials()
        with tempfile.TemporaryDirectory(prefix="native-state-", dir=private_output) as state:
            evidence = AuthEvidence(metrics["auth_attempts"], 0)
            startup = StartupEvidence(metrics["startup_samples"], 0, None)
            with open_tui(binary, Path(state), startup.sample["native_stages"]) as terminal:
                enter_authenticated(terminal, evidence, startup, "login_prompt",
                                    lambda: email + "\t" + password + "\t" + totp(key) + "\t\r")
                evidence.sample["stage"] = "seed_last_open"
                expected = seed_last_open(terminal, metrics["startup_seed"])
                evidence.quit(terminal)

            candidates_seen = set()
            for attempt in range(1, 4):
                auth = AuthEvidence(metrics["auth_attempts"], attempt)
                startup = StartupEvidence(metrics["startup_samples"], attempt, expected)
                with open_tui(binary, Path(state), startup.sample["native_stages"]) as terminal:
                    elapsed = enter_authenticated(terminal, auth, startup, "vault_prompt", lambda: password + "\t\r")
                    metrics["vault_unlock_to_recent_rows_ms"].append(elapsed)

                    auth.sample["stage"] = "open_chat"
                    while True:
                        _, entries = recent_chat_entries(terminal.rows)
                        current = transcript_title(terminal.rows)
                        for candidate_index, (row, column, label, unread) in enumerate(entries):
                            if unread or label in candidates_seen or (current and current.startswith(label)):
                                continue
                            if sum(entry[2].casefold() == label.casefold() for entry in entries) == 1:
                                break
                        else:
                            raise RuntimeError("Ran out of distinct already-read conversations for three timing samples")
                        candidates_seen.add(label)
                        position = terminal.diagnostic_position()
                        evidence = OpenEvidence(metrics["open_samples"], candidate_index, terminal.rows, label)
                        terminal.click(row, column)
                        try:
                            terminal.wait("readable or explicitly empty saved chat", evidence.observe)
                        finally:
                            evidence.finish(terminal)
                        if evidence.sample["result"] == "readable":
                            metrics["select_to_visible_message_ms"].append(evidence.sample["first_readable_message_ms"])
                            title = transcript_title(terminal.rows)
                            recorded = wait_for_recorded_open(terminal, position, evidence.sample)
                            expected = title if recorded == "recorded" else None
                            break
                        # Do not attribute an empty candidate's delayed receipt
                        # to a later click in the same process.
                        recorded = wait_for_recorded_open(
                            terminal, position, evidence.sample, require_completion=True,
                        )
                        if recorded == "timeout":
                            raise RuntimeError("Empty chat open did not finish before the next timing sample")
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

