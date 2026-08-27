#!/usr/bin/env python3
"""Isolated real-runtime verifier for OpenCode presence coordination.

Starts a temporary Git project, project plugin, XDG tree, deterministic local
OpenAI-compatible streaming provider, and random-port OpenCode server. It never
connects to the normal development server or reads normal OpenCode chat data.
Run: python3 scripts/verify_opencode_presence_live.py --isolated.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC_PREFIX = "openmates-presence-live-"
MODEL_ID = "fixture"
PROVIDER_ID = "fixture"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_opencode_bin() -> str | None:
    candidates = [
        os.environ.get("OPENCODE_BIN"),
        str(Path.home() / ".npm-global" / "bin" / "opencode"),
        shutil.which("opencode"),
    ]
    return next((candidate for candidate in candidates if candidate and os.access(candidate, os.X_OK)), None)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _request(method: str, url: str, body: dict | None = None, *, timeout: float = 10) -> object:
    encoded = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=encoded, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def _wait_for(description: str, predicate, *, timeout: float = 15, interval: float = 0.1):
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
            last_error = error
        time.sleep(interval)
    detail = f": {last_error}" if last_error else ""
    raise AssertionError(f"Timed out waiting for {description}{detail}")


def _message_text(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return ""


class FixtureProvider:
    """Deterministic streaming OpenAI-compatible fixture with no external calls."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.warning_seen = threading.Event()
        self.child_tool_seen = threading.Event()
        self.child_tool_outputs: list[str] = []
        self.task_tool_outputs: list[str] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _handler(self):
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_args) -> None:
                return

            def do_GET(self) -> None:
                if self.path.endswith("/models"):
                    self._json({"object": "list", "data": [{"id": MODEL_ID, "object": "model"}]})
                    return
                self._json({"ok": True})

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                messages = payload.get("messages") or []
                serialized = json.dumps(messages, sort_keys=True)
                if "[OpenMates presence conflict]" in serialized:
                    fixture.warning_seen.set()
                fixture.requests.append({"roles": [message.get("role") for message in messages if isinstance(message, dict)], "warning": fixture.warning_seen.is_set()})
                latest_user = max((index for index, message in enumerate(messages) if isinstance(message, dict) and message.get("role") == "user"), default=-1)
                user_text = _message_text(messages[latest_user]) if latest_user >= 0 else ""
                tool_after_user = any(isinstance(message, dict) and message.get("role") == "tool" for message in messages[latest_user + 1 :])
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    if "PRESENCE_TASK" in user_text and not tool_after_user:
                        self._chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": "call_presence_task", "type": "function", "function": {"name": "task", "arguments": '{"description":"Inspect fixture","prompt":"PRESENCE_CHILD","subagent_type":"explore"}'}}]})
                        self._finish("tool_calls")
                    elif "PRESENCE_CHILD" in user_text and not tool_after_user:
                        self._chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": "call_presence_child_bash", "type": "function", "function": {"name": "bash", "arguments": '{"command":"rg -o \\"fixture\\" fixture.txt | wc -l"}'}}]})
                        self._finish("tool_calls")
                    elif "PRESENCE_CHILD" in user_text and tool_after_user:
                        tool_outputs = [
                            _message_text(message).strip()
                            for message in messages
                            if isinstance(message, dict) and message.get("role") == "tool"
                        ]
                        fixture.child_tool_outputs = tool_outputs
                        if "1" in tool_outputs and "OpenMates child ownership guard" not in serialized:
                            fixture.child_tool_seen.set()
                        self._chunk({"role": "assistant", "content": "child inspection complete"})
                        self._finish("stop")
                    elif "PRESENCE_TOOL" in user_text and not tool_after_user:
                        self._chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": "call_presence_read", "type": "function", "function": {"name": "read", "arguments": '{"filePath":"fixture.txt"}'}}]})
                        self._finish("tool_calls")
                    elif "PRESENCE_ABORT" in user_text:
                        for index in range(100):
                            self._chunk({"role": "assistant"} if index == 0 else {"content": "tick"})
                            time.sleep(0.1)
                        self._finish("stop")
                    else:
                        if "PRESENCE_TASK" in user_text and tool_after_user:
                            fixture.task_tool_outputs = [
                                _message_text(message).strip()
                                for message in messages
                                if isinstance(message, dict) and message.get("role") == "tool"
                            ]
                        for index, text in enumerate(("fixture", " stream", " complete")):
                            self._chunk({"role": "assistant", "content": text} if index == 0 else {"content": text})
                            time.sleep(0.12)
                        self._finish("stop")
                except (BrokenPipeError, ConnectionResetError):
                    return

            def _json(self, payload: dict) -> None:
                raw = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _chunk(self, delta: dict) -> None:
                payload = {"id": "chatcmpl-presence", "object": "chat.completion.chunk", "created": 1, "model": MODEL_ID, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
                self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
                self.wfile.flush()

            def _finish(self, reason: str) -> None:
                payload = {"id": "chatcmpl-presence", "object": "chat.completion.chunk", "created": 1, "model": MODEL_ID, "choices": [{"index": 0, "delta": {}, "finish_reason": reason}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
                self.wfile.write(f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n".encode())
                self.wfile.flush()

        return Handler


def _copy_fixture_files(fixture: Path) -> None:
    files = (
        ".opencode/plugins/openmates-hooks.js",
        ".codex/hooks/claude-hook-bridge.sh",
        "scripts/safe_bash_guard.py",
        "scripts/sessions.py",
        "scripts/engineering_control_plane.py",
        "scripts/opencode_presence_store.py",
    )
    for relative_path in files:
        source = PROJECT_ROOT / relative_path
        target = fixture / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copytree(PROJECT_ROOT / ".claude" / "hooks", fixture / ".claude" / "hooks", dirs_exist_ok=True)
    bridge = fixture / ".codex" / "hooks" / "claude-hook-bridge.sh"
    bridge.write_text(
        bridge.read_text(encoding="utf-8").replace("/home/superdev/projects/OpenMates", str(fixture)),
        encoding="utf-8",
    )


def _write_sessions(fixture: Path, mappings: dict[str, tuple[str, Path]], *, lease_owner: str | None = None) -> None:
    now = _utc_now()
    sessions = {}
    for repository_id, (opencode_id, worktree) in mappings.items():
        sessions[repository_id] = {
            "task": f"{SYNTHETIC_PREFIX}{repository_id}",
            "mode": "testing",
            "opencode_session_id": opencode_id,
            "binding_mode": "worktree_routed",
            "last_active": now,
            "modified_files": [],
            "worktree": {"path": str(worktree), "status": "active"},
        }
    edit_leases = {}
    if lease_owner:
        edit_leases["fixture.txt"] = {"session_id": lease_owner, "since": now, "last_updated": now}
    path = fixture / ".claude" / "sessions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"locks": {}, "edit_leases": edit_leases, "sessions": sessions}, indent=2) + "\n", encoding="utf-8")


def _presence(fixture: Path) -> dict:
    path = fixture / ".opencode" / "presence.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"sessions": {}}


def _create_session(base_url: str, fixture: Path, title: str) -> dict:
    body = {"title": title}
    query = urllib.parse.urlencode({"directory": str(fixture)})
    return _request("POST", f"{base_url}/session?{query}", body)


def _prompt(base_url: str, fixture: Path, session_id: str, text: str) -> None:
    query = urllib.parse.urlencode({"directory": str(fixture)})
    body = {
        "model": {"providerID": PROVIDER_ID, "modelID": MODEL_ID},
        "parts": [{"type": "text", "text": text}],
    }
    _request("POST", f"{base_url}/session/{session_id}/prompt_async?{query}", body)


def _run_isolated() -> dict:
    opencode = _resolve_opencode_bin()
    if not opencode:
        raise AssertionError("OpenCode CLI is not installed")
    provider = FixtureProvider()
    provider.start()
    atexit.register(provider.stop)
    created_sessions: list[str] = []
    events: list[str] = []
    event_trace: list[dict] = []
    result: dict = {}
    process: subprocess.Popen | None = None
    stop_events = threading.Event()
    with tempfile.TemporaryDirectory(prefix=SYNTHETIC_PREFIX) as temporary:
        root = Path(temporary)
        fixture = root / "fixture"
        fixture.mkdir()
        _copy_fixture_files(fixture)
        subprocess.run(["git", "init", "-q"], cwd=fixture, check=True)
        subprocess.run(["git", "config", "user.email", "presence@example.invalid"], cwd=fixture, check=True)
        subprocess.run(["git", "config", "user.name", "Presence Fixture"], cwd=fixture, check=True)
        (fixture / "fixture.txt").write_text("fixture\n", encoding="utf-8")
        config = {
            "$schema": "https://opencode.ai/config.json",
            "model": f"{PROVIDER_ID}/{MODEL_ID}",
            "provider": {
                PROVIDER_ID: {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Presence Fixture",
                    "options": {"baseURL": provider.base_url, "apiKey": "synthetic-fixture-key"},
                    "models": {MODEL_ID: {"name": "Presence Fixture"}},
                }
            },
            "permission": {"read": "ask", "bash": "allow", "task": "allow", "edit": "deny", "write": "deny"},
            "mcp": {},
        }
        (fixture / "opencode.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        _write_sessions(fixture, {})
        for directory in (root / "home", root / "xdg-data", root / "xdg-config", root / "xdg-cache"):
            directory.mkdir()
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"
        env = {
            **os.environ,
            "HOME": str(root / "home"),
            "XDG_DATA_HOME": str(root / "xdg-data"),
            "XDG_CONFIG_HOME": str(root / "xdg-config"),
            "XDG_CACHE_HOME": str(root / "xdg-cache"),
            "OPENMATES_PROJECT_ROOT": str(fixture),
            "OPENMATES_CONTROL_PLANE_RUNTIME": str(fixture),
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
        }
        process_log_path = root / "opencode-server.log"
        process_log = process_log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            [opencode, "serve", "--hostname", "127.0.0.1", "--port", str(port), "--print-logs", "--log-level", "INFO"],
            cwd=fixture,
            env=env,
            stdout=process_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            def server_ready() -> bool:
                if process and process.poll() is not None:
                    process_log.flush()
                    detail = (process_log_path.read_text(encoding="utf-8") or "no OpenCode process output")[-2_000:]
                    raise AssertionError(f"Isolated OpenCode server exited {process.returncode}: {detail}")
                return _request(
                    "GET",
                    f"{base_url}/session?{urllib.parse.urlencode({'directory': str(fixture)})}",
                    timeout=1,
                ) is not None

            try:
                _wait_for("isolated OpenCode server", server_ready, timeout=30)
            except AssertionError as error:
                process_log.flush()
                detail = (process_log_path.read_text(encoding="utf-8") or "no OpenCode process output")[-2_000:]
                raise AssertionError(f"{error}: {detail}") from error

            def collect_events() -> None:
                url = f"{base_url}/event?{urllib.parse.urlencode({'directory': str(fixture)})}"
                try:
                    with urllib.request.urlopen(url, timeout=60) as response:
                        while not stop_events.is_set():
                            line = response.readline().decode().strip()
                            if not line.startswith("data:"):
                                continue
                            payload = json.loads(line[5:].strip())
                            event_type = payload.get("type")
                            if isinstance(event_type, str):
                                events.append(event_type)
                                properties = payload.get("properties") or {}
                                info = properties.get("info") or {}
                                part = properties.get("part") or {}
                                status = properties.get("status") or {}
                                error = properties.get("error") or info.get("error") or {}
                                event_trace.append({
                                    "type": event_type,
                                    "session_id": properties.get("sessionID") or info.get("sessionID") or info.get("id") or part.get("sessionID") or "",
                                    "message_id": info.get("id") or part.get("messageID") or "",
                                    "role": info.get("role") or "",
                                    "completed": bool((info.get("time") or {}).get("completed")),
                                    "status": status.get("type") or "",
                                    "error": error.get("name") or "",
                                })
                except (OSError, ValueError, urllib.error.URLError):
                    return

            event_thread = threading.Thread(target=collect_events, daemon=True)
            event_thread.start()

            first = _create_session(base_url, fixture, f"{SYNTHETIC_PREFIX}first")
            second = _create_session(base_url, fixture, f"{SYNTHETIC_PREFIX}second")
            created_sessions.extend([first["id"], second["id"]])
            first_worktree = fixture / ".openmates-agent-worktrees" / "agent-a111"
            second_worktree = fixture / ".openmates-agent-worktrees" / "agent-b222"
            for worktree in (first_worktree, second_worktree):
                worktree.mkdir(parents=True)
                (worktree / ".git").mkdir()
                (worktree / "fixture.txt").write_text("fixture\n", encoding="utf-8")
            mappings = {"a111": (first["id"], first_worktree), "b222": (second["id"], second_worktree)}
            _write_sessions(fixture, mappings, lease_owner="a111")

            _prompt(base_url, fixture, first["id"], "PRESENCE_ABORT")
            busy = _wait_for("busy presence", lambda: _presence(fixture).get("sessions", {}).get(first["id"], {}).get("execution") == "busy")
            assert busy
            query = urllib.parse.urlencode({"directory": str(fixture)})
            owner_messages_before = _wait_for(
                "owner assistant message before collision snapshot",
                lambda: (
                    messages
                    if len(messages := _request("GET", f"{base_url}/session/{first['id']}/message?{query}")) >= 2
                    else None
                ),
            )
            owner_message_ids = [message["info"]["id"] for message in owner_messages_before]

            _prompt(base_url, fixture, second["id"], "PRESENCE_TOOL")
            permission_id = _wait_for(
                "permission presence",
                lambda: next(iter(_presence(fixture).get("sessions", {}).get(second["id"], {}).get("pending_permission_ids", [])), ""),
            )
            _request("POST", f"{base_url}/session/{second['id']}/permissions/{permission_id}?{query}", {"response": "once"})
            _wait_for("actual read-hook collision output", provider.warning_seen.is_set)
            try:
                completed = _wait_for(
                    "completed idle second session",
                    lambda: (
                        _presence(fixture).get("sessions", {}).get(second["id"], {}).get("execution") == "idle"
                        and _presence(fixture).get("sessions", {}).get(second["id"], {}).get("turn") == "completed"
                    ),
                    timeout=30,
                )
            except AssertionError as error:
                second_record = _presence(fixture).get("sessions", {}).get(second["id"], {})
                second_trace = [entry for entry in event_trace if entry["session_id"] == second["id"]][-30:]
                raise AssertionError(f"{error}; presence={json.dumps(second_record, sort_keys=True)}; events={json.dumps(second_trace, sort_keys=True)}") from error
            assert completed
            owner_messages_after_collision = _request("GET", f"{base_url}/session/{first['id']}/message?{query}")
            assert [message["info"]["id"] for message in owner_messages_after_collision] == owner_message_ids

            _prompt(base_url, fixture, second["id"], "PRESENCE_RESUME")
            _wait_for("resumed second turn", lambda: _presence(fixture).get("sessions", {}).get(second["id"], {}).get("execution") == "busy")
            try:
                _wait_for("resumed completion", lambda: _presence(fixture).get("sessions", {}).get(second["id"], {}).get("execution") == "idle", timeout=30)
            except AssertionError as error:
                second_record = _presence(fixture).get("sessions", {}).get(second["id"], {})
                second_trace = [entry for entry in event_trace if entry["session_id"] == second["id"]][-30:]
                raise AssertionError(f"{error}; presence={json.dumps(second_record, sort_keys=True)}; events={json.dumps(second_trace, sort_keys=True)}") from error

            _prompt(base_url, fixture, second["id"], "PRESENCE_TASK")
            try:
                child_id, child_record = _wait_for(
                    "task child role before parent completion",
                    lambda: next(
                        (
                            (child_id, record)
                            for child_id, record in _presence(fixture).get("sessions", {}).items()
                            if child_id not in {first["id"], second["id"]}
                            and record.get("parent_id") == second["id"]
                            and record.get("child_role") == "read_only"
                        ),
                        None,
                    ),
                )
            except AssertionError as error:
                child_trace = [entry for entry in event_trace if entry["session_id"] not in {first["id"], second["id"]}][-30:]
                raise AssertionError(
                    f"{error}; presence={json.dumps(_presence(fixture), sort_keys=True)}; "
                    f"child_events={json.dumps(child_trace, sort_keys=True)}; "
                    f"provider_requests={json.dumps(provider.requests[-8:], sort_keys=True)}; "
                    f"task_tool_outputs={provider.task_tool_outputs!r}"
                ) from error
            created_sessions.append(child_id)
            assert child_record["parent_id"] == second["id"]
            assert child_record["child_role"] == "read_only"
            try:
                _wait_for("task child read-only shell completion", provider.child_tool_seen.is_set, timeout=30)
            except AssertionError as error:
                raise AssertionError(f"{error}; child_tool_outputs={provider.child_tool_outputs!r}") from error

            _request("POST", f"{base_url}/session/{first['id']}/abort?{query}")
            stopped = _wait_for(
                "aborted presence",
                lambda: _presence(fixture).get("sessions", {}).get(first["id"], {}).get("execution") == "stopped",
            )
            assert stopped

            status = _request("GET", f"{base_url}/session/status?{query}")
            assert isinstance(status, dict)
            authoritative_session = _request("GET", f"{base_url}/session/{second['id']}?{query}")
            authoritative_messages = _request("GET", f"{base_url}/session/{second['id']}/message?{query}")
            assert authoritative_session["id"] == second["id"]
            assert len(authoritative_messages) >= 2
            snapshot = _presence(fixture)
            serialized = json.dumps(snapshot, sort_keys=True)
            for forbidden in ("PRESENCE_ABORT", "PRESENCE_TOOL", "fixture stream complete", "synthetic-fixture-key"):
                assert forbidden not in serialized
            required_events = {"session.status", "message.updated", "message.part.updated", "permission.replied"}
            _wait_for(
                "installed runtime event sequence",
                lambda: required_events.issubset(set(events)) and bool({"permission.updated", "permission.asked"} & set(events)),
            )
            observed_events = required_events | ({"permission.asked"} if "permission.asked" in events else {"permission.updated"})
            result = {
                "status": "passed",
                "opencode_version": subprocess.run([opencode, "--version"], capture_output=True, text=True, check=True).stdout.strip(),
                "sessions_created": len(created_sessions),
                "event_types": sorted(set(events) & observed_events),
                "question_capability": snapshot["sessions"][second["id"]]["capabilities"]["question"],
                "collision_warning_seen": provider.warning_seen.is_set(),
                "task_child_role": child_record["child_role"],
                "task_child_shell_seen": provider.child_tool_seen.is_set(),
                "hook_runtime_hash": child_record.get("hook_runtime_hash"),
                "hook_source_hash": hashlib.sha256(
                    (fixture / ".opencode" / "plugins" / "openmates-hooks.js").read_bytes()
                ).hexdigest(),
                "owner_chat_unchanged": True,
                "bridge_isolated": str(fixture) in (fixture / ".codex" / "hooks" / "claude-hook-bridge.sh").read_text(encoding="utf-8"),
                "normal_server_used": False,
                "external_model_used": False,
            }
            assert result["hook_runtime_hash"] == result["hook_source_hash"]
        finally:
            for session_id in reversed(created_sessions):
                try:
                    query = urllib.parse.urlencode({"directory": str(fixture)})
                    _request("DELETE", f"{base_url}/session/{session_id}?{query}", timeout=2)
                except (OSError, urllib.error.URLError):
                    pass
            stop_events.set()
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            process_log.close()
    atexit.unregister(provider.stop)
    provider.stop()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify OpenCode presence through an isolated real runtime")
    parser.add_argument("--isolated", action="store_true", help="Required: refuse normal OpenCode state and servers")
    args = parser.parse_args()
    if not args.isolated:
        raise SystemExit("Refusing to run without --isolated")
    result = _run_isolated()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
