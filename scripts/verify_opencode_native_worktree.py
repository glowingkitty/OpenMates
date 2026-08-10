#!/usr/bin/env python3
"""Verify native OpenCode session directories in an isolated fixture.

The verifier starts a disposable local OpenCode server with isolated XDG state,
creates a temporary Git repository and detached worktree, and probes directory,
shell, child-session, and move-session behavior without invoking a model.
No project files, user sessions, or normal OpenCode state are modified.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SERVER_TIMEOUT_SECONDS = 30
REQUEST_TIMEOUT_SECONDS = 15
SERVER_URL_PATTERN = re.compile(r"https?://(?:127\.0\.0\.1|localhost):\d+")


def _run(*args: str, cwd: Path) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _request(
    base_url: str,
    method: str,
    path: str,
    *,
    password: str,
    directory: Path | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    query = urllib.parse.urlencode({"directory": str(directory)}) if directory else ""
    url = f"{base_url}{path}{'?' + query if query else ''}"
    body = json.dumps(payload).encode() if payload is not None else None
    token = base64.b64encode(f"opencode:{password}".encode()).decode()
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
    return json.loads(raw) if raw else None


def _start_server(binary: str, env: dict[str, str]) -> tuple[subprocess.Popen[str], str]:
    process = subprocess.Popen(
        [binary, "serve", "--pure", "--hostname", "127.0.0.1", "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    assert process.stdout is not None
    deadline = time.monotonic() + SERVER_TIMEOUT_SECONDS
    output: list[str] = []
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if line:
            output.append(line.rstrip())
            match = SERVER_URL_PATTERN.search(line)
            if match:
                return process, match.group(0)
        elif process.poll() is not None:
            break
        else:
            time.sleep(0.05)
    process.terminate()
    raise RuntimeError(f"OpenCode server did not become ready: {' | '.join(output[-5:])}")


def _stop_server(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def verify() -> dict[str, Any]:
    binary = shutil.which("opencode")
    if not binary:
        raise RuntimeError("opencode binary not found")
    version = subprocess.run([binary, "--version"], check=True, capture_output=True, text=True).stdout.strip()
    password = "isolated-native-worktree-verifier"
    started = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="openmates-opencode-native-") as temp:
        root = Path(temp)
        home = root / "home"
        repo = root / "repo"
        worktree = root / "worktree"
        for directory in [home, repo]:
            directory.mkdir(parents=True)

        _run("git", "init", "-b", "dev", cwd=repo)
        _run("git", "config", "user.email", "verifier@example.invalid", cwd=repo)
        _run("git", "config", "user.name", "OpenCode verifier", cwd=repo)
        (repo / "root-sentinel.txt").write_text("root\n", encoding="utf-8")
        _run("git", "add", "root-sentinel.txt", cwd=repo)
        _run("git", "commit", "-m", "fixture", cwd=repo)
        _run("git", "worktree", "add", "--detach", str(worktree), "HEAD", cwd=repo)
        (worktree / "worktree-only.txt").write_text("worktree\n", encoding="utf-8")

        env = {
            **os.environ,
            "HOME": str(home),
            "XDG_DATA_HOME": str(root / "xdg-data"),
            "XDG_CONFIG_HOME": str(root / "xdg-config"),
            "XDG_CACHE_HOME": str(root / "xdg-cache"),
            "XDG_STATE_HOME": str(root / "xdg-state"),
            "OPENCODE_SERVER_PASSWORD": password,
            "OPENCODE_SERVER_USERNAME": "opencode",
        }
        process, base_url = _start_server(binary, env)
        try:
            path_info = _request(base_url, "GET", "/path", password=password, directory=worktree)
            parent = _request(base_url, "POST", "/session", password=password, directory=worktree, payload={})
            parent_id = parent["id"]
            fetched = _request(base_url, "GET", f"/session/{parent_id}", password=password, directory=worktree)
            child = _request(
                base_url,
                "POST",
                "/session",
                password=password,
                directory=worktree,
                payload={"parentID": parent_id, "title": "native verifier child"},
            )
            shell = _request(
                base_url,
                "POST",
                f"/session/{parent_id}/shell",
                password=password,
                directory=worktree,
                payload={"command": "pwd", "agent": "build"},
            )

            move_supported = False
            move_error = ""
            root_session = _request(base_url, "POST", "/session", password=password, directory=repo, payload={})
            try:
                _request(
                    base_url,
                    "POST",
                    "/experimental/control-plane/move-session",
                    password=password,
                    payload={
                        "sessionID": root_session["id"],
                        "destination": {"directory": str(worktree)},
                        "moveChanges": False,
                    },
                )
                moved = _request(
                    base_url,
                    "GET",
                    f"/session/{root_session['id']}",
                    password=password,
                    directory=worktree,
                )
                move_supported = Path(moved["directory"]).resolve() == worktree.resolve()
            except RuntimeError as exc:
                move_error = str(exc)

            shell_text = json.dumps(shell)
            assert Path(path_info["directory"]).resolve() == worktree.resolve()
            assert Path(fetched["directory"]).resolve() == worktree.resolve()
            assert Path(child["directory"]).resolve() == worktree.resolve()
            assert str(worktree.resolve()) in shell_text
            assert (repo / "root-sentinel.txt").read_text(encoding="utf-8") == "root\n"
            assert _run("git", "status", "--short", cwd=repo) == ""

            return {
                "status": "passed",
                "runtime_version": version,
                "strategy": "move_session" if move_supported else "directory_scoped_creation",
                "capabilities": {
                    "directory_scoped_session": True,
                    "directory_scoped_shell": True,
                    "child_directory": True,
                    "move_session": move_supported,
                    "move_error": move_error,
                },
                "root_clean": True,
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        finally:
            _stop_server(process)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolated", action="store_true", help="Required safety acknowledgement")
    args = parser.parse_args()
    if not args.isolated:
        parser.error("--isolated is required")
    try:
        print(json.dumps(verify(), indent=2, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
