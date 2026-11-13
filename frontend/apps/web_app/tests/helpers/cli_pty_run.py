#!/usr/bin/env python3
"""Run one command on a pseudo-terminal, bridging piped stdin/stdout.

The native OpenMates CLI refuses pairing and secret prompts without a terminal.
Playwright specs drive login through pipes, so this wrapper gives the command a
real PTY. Input newlines become carriage returns because the CLI puts the
terminal in raw mode for the PIN prompt. Output is the merged terminal stream.
Usage: cli_pty_run.py <command> [args...]; exits with the command's status.
"""
import os
import pty
import select
import signal
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: cli_pty_run.py <command> [args...]", file=sys.stderr)
        return 2
    pid, master = pty.fork()
    if pid == 0:
        os.execvp(sys.argv[1], sys.argv[1:])
    signal.signal(signal.SIGTERM, lambda *_: os.kill(pid, signal.SIGTERM))
    stdin_open = True
    while True:
        readable = [master] + ([0] if stdin_open else [])
        ready, _, _ = select.select(readable, [], [])
        if 0 in ready:
            data = os.read(0, 4096)
            if data:
                os.write(master, data.replace(b"\n", b"\r"))
            else:
                stdin_open = False
        if master in ready:
            try:
                data = os.read(master, 4096)
            except OSError:
                break
            if not data:
                break
            os.write(1, data)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


if __name__ == "__main__":
    sys.exit(main())
