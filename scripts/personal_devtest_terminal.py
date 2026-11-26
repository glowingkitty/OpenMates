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

from cli_video_capture import CliCaptureError, _latest_screen

API_ORIGIN = "https://api.dev.openmates.org"
MAX_FRAME_BYTES = 4 * 1024 * 1024


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
        while time.monotonic() < deadline and self.process.poll() is None:
            if not select.select([self.master], [], [], 0.1)[0]:
                continue
            try:
                incoming = os.read(self.master, 65536)
            except OSError as exc:
                if exc.errno != errno.EIO:
                    raise
                break
            self.output.extend(incoming)
            if len(self.output) > MAX_FRAME_BYTES:
                raise RuntimeError("Native terminal output exceeded the benchmark limit")
            if b"\x1b[?2026l" not in incoming and not self.output.endswith(b"\x1b[?2026l"):
                continue
            try:
                rows, _, _ = _latest_screen(self.output.decode(errors="replace"))
            except CliCaptureError:
                continue
            self.rows = rows
            if accept(rows):
                return time.monotonic()
        sidebar_visible, chat_cells = recent_chat_cells(self.rows)
        raise RuntimeError(
            f"Native terminal did not reach {label} "
            f"(sidebar_visible={sidebar_visible}, visible_chat_rows={len(chat_cells)}, "
            f"status={terminal_status(self.rows)})"
        )


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


def readable_chat(rows):
    for index, row in enumerate(rows):
        if "‹ Back" in row and "Close" in row:
            transcript_start = row.index("‹ Back")
            return any(
                re.search(r"\w", line[transcript_start:])
                for line in rows[index + 2:-10]
            )
    return False


def measure(binary, private_output):
    email, password, key = credentials()
    with tempfile.TemporaryDirectory(prefix="native-state-", dir=private_output) as state:
        with open_tui(binary, Path(state)) as terminal:
            terminal.wait("sign-in form", lambda rows: any("Sign in to OpenMates" in row for row in rows))
            terminal.send(email + "\t" + password + "\t" + totp(key) + "\t\r")
            terminal.wait("authenticated session", lambda rows: any("Signed in" in row for row in rows))
            terminal.send("\x02")
            terminal.wait("recent chats", recent)

        recent_ms = []
        message_ms = []
        for index in range(3):
            with open_tui(binary, Path(state)) as terminal:
                terminal.wait("vault unlock", lambda rows: any("Unlock local vault" in row for row in rows))
                start = time.monotonic()
                terminal.send(password + "\t\r")
                terminal.wait("restored session", lambda rows: any("Signed in" in row for row in rows))
                terminal.send("\x02")
                shown = terminal.wait("restored recent chats", recent)
                recent_ms.append(round((shown - start) * 1000))
                selection = recent_chat_cells(terminal.rows)[1][index]
                opening = time.monotonic()
                terminal.click(*selection)
                shown = terminal.wait("readable saved chat", readable_chat)
                message_ms.append(round((shown - opening) * 1000))
        metrics = {"vault_unlock_to_recent_rows_ms": recent_ms, "select_to_visible_message_ms": message_ms}
        (private_output / "terminal-timings.json").write_text(json.dumps(metrics) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("private_output", type=Path)
    args = parser.parse_args()
    measure(args.binary.resolve(strict=True), args.private_output.resolve(strict=True))


if __name__ == "__main__":
    main()

