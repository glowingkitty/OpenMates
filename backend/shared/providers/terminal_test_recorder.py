#!/usr/bin/env python3
# backend/shared/providers/terminal_test_recorder.py
#
# Standard-library-only terminal recorder for Code Run test runs of kind "cli".
# It is shipped into the sandbox (or remote worktree) at run time as source text
# (see e2b_cli_test_recorder.py), so it must not import anything from OpenMates.
#
# Usage: terminal_test_recorder.py [--preview-step NAME] [--cols N] [--rows N] -- COMMAND [ARG...]
#
# Runs COMMAND under a pseudo-terminal and writes, into OPENMATES_TEST_RUN_DIR:
#   terminal.cast  asciicast v2 (https://docs.asciinema.org/manual/asciicast/v2/)
#   report.json    {"tests": [...], "steps": [...], "preview_step_index": int?}
# Step convention (documented in docs/plans/agentic-tests-and-git-sync/contracts/test-run.md):
#   ESC ] 777 ; openmates-step ; <command text> BEL        starts a step
#   ESC ] 777 ; openmates-step-end ; <exit code> BEL       optionally ends it with a status
# ST (ESC \) is accepted instead of BEL. Without any marker the whole run is one step.
# Markers stay in the cast (terminals ignore unknown OSC sequences); they are the
# only text removed from a step's `output`, and CRLF is normalised to LF there.
# Oversized output is truncated with an explicit marker, never dropped silently.

from __future__ import annotations

import codecs
import errno
import fcntl
import json
import os
import re
import select
import signal
import struct
import sys
import termios
import time

CAST_MAX_BYTES = 2_000_000
CAST_RESERVE_BYTES = 400  # room for the truncation event
REPORT_MAX_BYTES = 1_000_000
STEP_OUTPUT_MAX_CHARS = 4000
STEP_COMMAND_MAX_CHARS = 1000
STEP_NAME_MAX_CHARS = 300
MAX_STEPS = 500
MAX_TEST_NAME_CHARS = 500
OSC_PREFIX = "\x1b]777;openmates-"
MARKER_RE = re.compile(r"\x1b\]777;openmates-(step|step-end);([^\x07\x1b]{0,2000})(?:\x07|\x1b\\)")
MAX_MARKER_CHARS = 2100
CAST_TRUNCATION_TEXT = "\r\n[openmates: terminal cast truncated, 2 MB limit reached]\r\n"
OUTPUT_TRUNCATION_TEMPLATE = "\n[openmates: step output truncated, {n} more characters]"
STEP_LIMIT_TEXT = "[openmates: step limit reached, later output is appended to this step]"
EXIT_TIMEOUT = 124
EXIT_NOT_FOUND = 127


def truncate_text(text: str, limit: int, template: str = "…") -> str:
    """Cut text to `limit` characters including an explicit truncation marker."""
    if len(text) <= limit:
        return text
    marker = template.format(n=len(text) - limit) if "{n}" in template else template
    keep = max(0, limit - len(marker))
    marker = template.format(n=len(text) - keep) if "{n}" in template else template
    return text[:keep] + marker


class Step:
    def __init__(self, command: str | None, start_ms: int) -> None:
        self.command = command
        self.start_ms = start_ms
        self.end_ms = start_ms
        self.exit_code: int | None = None
        self.parts: list[str] = []
        self.chars = 0

    def add(self, text: str, end_ms: int) -> None:
        if text:
            self.parts.append(text)
            self.chars += len(text)
        self.end_ms = max(self.end_ms, end_ms)


class StepTracker:
    """Splits the decoded output stream into steps using the OSC marker convention."""

    def __init__(self, default_command: str, preview_step: str | None) -> None:
        self.default_command = default_command
        self.preview_step = preview_step
        self.steps: list[Step] = []
        self.current: Step | None = None
        self.pending = ""
        self.has_markers = False
        self.limit_hit = False

    def _open(self, command: str | None, at_ms: int) -> Step:
        step = Step(command, at_ms)
        self.steps.append(step)
        self.current = step
        return step

    def _text(self, text: str, at_ms: int) -> None:
        if not text:
            return
        if self.current is None:
            if not text.strip():
                return  # whitespace before the first marker is not a step
            self._open(None, at_ms)
        assert self.current is not None
        self.current.add(text, at_ms)

    def _marker(self, kind: str, value: str, at_ms: int) -> None:
        self.has_markers = True
        if kind == "step":
            if self.current is not None:
                self.current.end_ms = max(self.current.end_ms, at_ms)
            if len(self.steps) >= MAX_STEPS:
                if not self.limit_hit:
                    self.limit_hit = True
                    self._text(STEP_LIMIT_TEXT + "\n", at_ms)
                return
            self._open(value.strip(), at_ms)
            return
        if self.current is not None:
            self.current.end_ms = max(self.current.end_ms, at_ms)
            try:
                self.current.exit_code = int(value.strip())
            except ValueError:
                self.current.exit_code = 1  # an unreadable status is reported as failure
                self.current.add(f"\n[openmates: invalid step-end status {value.strip()!r}]\n", at_ms)

    def _held_back(self, text: str) -> int:
        """Index from which `text` could be the start of an unfinished marker, else len(text)."""
        start = text.rfind("\x1b")
        if start < 0:
            return len(text)
        tail = text[start:]
        if OSC_PREFIX.startswith(tail):
            return start
        if tail.startswith(OSC_PREFIX) and len(tail) <= MAX_MARKER_CHARS and not MARKER_RE.match(tail):
            return start
        return len(text)

    def feed(self, text: str, at_ms: int, final: bool = False) -> None:
        data = (self.pending + text).replace("\r\n", "\n")
        self.pending = ""
        position = 0
        for match in MARKER_RE.finditer(data):
            self._text(data[position:match.start()], at_ms)
            self._marker(match.group(1), match.group(2), at_ms)
            position = match.end()
        rest = data[position:]
        cut = len(rest) if final else self._held_back(rest)
        self._text(rest[:cut], at_ms)
        self.pending = rest[cut:]

    def finish(self, exit_code: int, end_ms: int) -> list[dict]:
        self.feed("", end_ms, final=True)
        if not self.steps:
            self._open(None, 0)
        last = self.steps[-1]
        last.end_ms = max(last.end_ms, end_ms)
        records = []
        for index, step in enumerate(self.steps):
            command = step.command or (None if self.has_markers else self.default_command)
            code = step.exit_code
            if code is None:
                code = exit_code if step is last else 0
            output = "".join(step.parts)
            if not self.has_markers:
                output = output.strip("\n") if output.strip() else ""
            name = truncate_text(command or f"Step {index + 1}", STEP_NAME_MAX_CHARS)
            record: dict = {
                "name": name,
                "start_ms": step.start_ms,
                "end_ms": max(step.start_ms, step.end_ms),
                "status": "passed" if code == 0 else "failed",
                "error": None if code == 0 else f"exit code {code}",
                "is_preview": self.preview_step is not None and (command or "") == self.preview_step,
                "command": truncate_text(command, STEP_COMMAND_MAX_CHARS) if command else None,
                "output": truncate_text(output, STEP_OUTPUT_MAX_CHARS, OUTPUT_TRUNCATION_TEMPLATE),
            }
            records.append(record)
        return records


class CastWriter:
    """Writes asciicast v2 events, truncating with an explicit final event at the byte cap."""

    def __init__(self, path: str, cols: int, rows: int, command: list[str]) -> None:
        self.file = open(path, "w", encoding="utf-8")
        header = {
            "version": 2, "width": cols, "height": rows, "timestamp": int(time.time()),
            "command": " ".join(command)[:500], "env": {"TERM": "xterm-256color"},
        }
        line = json.dumps(header, ensure_ascii=False) + "\n"
        self.bytes = len(line.encode("utf-8"))
        self.file.write(line)
        self.truncated = False

    def write(self, seconds: float, text: str) -> None:
        if self.truncated or not text:
            return
        line = json.dumps([round(seconds, 6), "o", text], ensure_ascii=False) + "\n"
        size = len(line.encode("utf-8"))
        if self.bytes + size > CAST_MAX_BYTES - CAST_RESERVE_BYTES:
            self.truncated = True
            notice = json.dumps([round(seconds, 6), "o", CAST_TRUNCATION_TEXT]) + "\n"
            self.file.write(notice)
            self.bytes += len(notice.encode("utf-8"))
            return
        self.file.write(line)
        self.bytes += size

    def close(self) -> None:
        self.file.close()


def resolve_output_dir() -> str:
    """OPENMATES_TEST_RUN_DIR is relative to the workspace root; find it from a subdirectory cwd."""
    configured = os.environ.get("OPENMATES_TEST_RUN_DIR", "outputs/test-run")
    if os.path.isabs(configured):
        os.makedirs(configured, exist_ok=True)
        return configured
    directory = os.getcwd()
    while True:
        candidate = os.path.join(directory, configured)
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    path = os.path.join(os.getcwd(), configured)
    os.makedirs(path, exist_ok=True)
    return path


def set_window_size(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def exit_code_from_status(status: int) -> int:
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return 1


def run_in_pty(command: list[str], cols: int, rows: int, on_data, stop_flag: list[bool]) -> int:
    """Run `command` in a pty, calling on_data(text) with decoded output. Returns the exit code."""
    pid, fd = os.forkpty()
    if pid == 0:
        try:
            os.execvp(command[0], command)
        except OSError as exc:
            sys.stderr.write(f"openmates recorder: cannot run {command[0]}: {exc.strerror}\n")
            sys.stderr.flush()
            os._exit(EXIT_NOT_FOUND)
    set_window_size(fd, rows, cols)
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    timed_out = False
    killed_at: float | None = None
    while True:
        if stop_flag[0] and killed_at is None:
            timed_out = True
            killed_at = time.monotonic()
            os.kill(pid, signal.SIGTERM)
        if killed_at is not None and time.monotonic() - killed_at > 3:
            os.kill(pid, signal.SIGKILL)
        ready, _, _ = select.select([fd], [], [], 0.1)
        if not ready:
            continue
        try:
            data = os.read(fd, 65536)
        except OSError as exc:
            if exc.errno == errno.EIO:  # child closed the pty
                break
            raise
        if not data:
            break
        on_data(decoder.decode(data))
    tail = decoder.decode(b"", final=True)
    if tail:
        on_data(tail)
    os.close(fd)
    _, status = os.waitpid(pid, 0)
    return EXIT_TIMEOUT if timed_out else exit_code_from_status(status)


def parse_args(argv: list[str]) -> tuple[dict, list[str]]:
    options = {"preview_step": None, "cols": 100, "rows": 30}
    index = 0
    while index < len(argv) and argv[index] != "--":
        flag = argv[index]
        if flag == "--preview-step" and index + 1 < len(argv):
            options["preview_step"] = argv[index + 1]
        elif flag in ("--cols", "--rows") and index + 1 < len(argv):
            options[flag[2:]] = int(argv[index + 1])
        else:
            raise SystemExit(f"openmates recorder: unknown option {flag}")
        index += 2
    command = argv[index + 1:] if index < len(argv) else []
    if not command:
        raise SystemExit("openmates recorder: no command given after --")
    return options, command


def build_report(records: list[dict], command: list[str], exit_code: int) -> dict:
    test_failed = exit_code != 0 or any(record["status"] == "failed" for record in records)
    name = truncate_text(" ".join(command), MAX_TEST_NAME_CHARS)
    test = {"name": name, "status": "failed" if test_failed else "passed",
            "duration_ms": records[-1]["end_ms"] if records else 0,
            "error": None if not test_failed else f"exit code {exit_code}"}
    report = {"tests": [test], "steps": records}
    preview = next((i for i, record in enumerate(records) if record["is_preview"]), None)
    if preview is not None:
        report["preview_step_index"] = preview
    return report


def encode_report(report: dict) -> str:
    """Serialise the report within REPORT_MAX_BYTES by shrinking step output first."""
    text = json.dumps(report, ensure_ascii=False)
    limit = STEP_OUTPUT_MAX_CHARS
    while len(text.encode("utf-8")) > REPORT_MAX_BYTES and limit > 0:
        limit //= 2
        for step in report["steps"]:
            step["output"] = truncate_text(step["output"], limit, OUTPUT_TRUNCATION_TEMPLATE) if limit else ""
        text = json.dumps(report, ensure_ascii=False)
    return text


def main(argv: list[str]) -> int:
    options, command = parse_args(argv)
    output_dir = resolve_output_dir()
    cast = CastWriter(os.path.join(output_dir, "terminal.cast"), options["cols"], options["rows"], command)
    tracker = StepTracker(" ".join(command), options["preview_step"])
    started = time.monotonic()
    stop_flag = [False]
    signal.signal(signal.SIGTERM, lambda *_: stop_flag.__setitem__(0, True))

    def on_data(text: str) -> None:
        elapsed = time.monotonic() - started
        cast.write(elapsed, text)
        tracker.feed(text, int(elapsed * 1000))

    exit_code = run_in_pty(command, options["cols"], options["rows"], on_data, stop_flag)
    cast.close()
    records = tracker.finish(exit_code, int((time.monotonic() - started) * 1000))
    report = build_report(records, command, exit_code)
    with open(os.path.join(output_dir, "report.json"), "w", encoding="utf-8") as handle:
        handle.write(encode_report(report))
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
