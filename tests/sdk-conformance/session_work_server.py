#!/usr/bin/env python3
"""Shared test-only cookie CRUD peer; synthetic ephemeral loopback only."""

from __future__ import annotations

import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit
import uuid

from recovery_server import decrypt

CAPABILITY = "session.work-crud.v1"


class WorkPeer:
    def __init__(self, suite, vector, identity):
        assert identity in ("rust", "npm", "pip")
        self.suite, self.vector, self.identity = suite, vector, identity
        self.master = base64.b64decode(suite["account"]["master_key"])
        self.team = base64.b64decode(suite["team"]["team_key_b64"])
        self.rows, self.keys = {}, {}
        self.failure, self.requests, self.writes = None, 0, 0
        self.cookie = suite["account"]["cookie"]
        self.checks = set()
        self.blocked = False
        self.released = threading.Event()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        self.server.daemon_threads = True

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def close(self):
        self.released.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def status(self):
        return {
            "failure": self.failure,
            "requests": self.requests,
            "writes": self.writes,
            "cookie": self.cookie,
            "checks": sorted(self.checks),
            "blocked": self.blocked,
        }

    def validate_create(self, family, payload, raw):
        name = "title" if family == "tasks" else "name"
        object_id = payload["task_id" if family == "tasks" else "project_id"]
        assert str(uuid.UUID(object_id)) == object_id
        wrapping = self.team if self.vector.get("team") else self.master
        wrapped = f"encrypted_{'task' if family == 'tasks' else 'project'}_key"
        if self.vector.get("team"):
            wrappers = payload["key_wrappers"]
            assert len(wrappers) == 1
            assert (
                wrappers[0]["key_type"] == "team" and wrappers[0]["team_key_epoch"] == 1
            )
            assert (
                wrappers[0]["hashed_team_id"]
                == hashlib.sha256(self.suite["team"]["team_id"].encode()).hexdigest()
            )
            key = decrypt(wrappers[0][wrapped], wrapping)
        else:
            assert not payload.get("key_wrappers")
            key = decrypt(payload[wrapped], wrapping)
        assert len(key) == 32 and key not in (self.master, self.team)
        self.keys[object_id] = key
        assert (
            decrypt(payload[f"encrypted_{name}"], key).decode()
            == self.suite["input"][family][name]
        )
        assert (
            decrypt(payload["encrypted_description"], key).decode()
            == "Synthetic client-only description"
        )
        if family == "tasks":
            assert json.loads(decrypt(payload["encrypted_labels"], key)) == ["private"]
            assert payload["due_at"] == 2000000000
            assert payload["assignee_type"] != "openmates"
            assert "plaintext_title" not in payload
        else:
            assert payload["write_mode"] == "always_ask"
            assert "settings" not in payload and "default_focus" not in payload
            focus = json.loads(decrypt(payload["encrypted_settings"], key))
            assert set(focus) == {"default_focus"}
            assert focus["default_focus"]["focus_id"] == payload["default_focus_id"]
            assert focus["default_focus"]["source"] == "generated"
        for secret in (
            self.suite["input"][family][name],
            "Synthetic client-only description",
            self.suite["account"]["master_key"],
            base64.b64encode(key).decode(),
        ):
            assert secret not in raw
        self.checks.update(
            ("encrypted-private-fields", "scope-bound-wrapper", "fresh-object-key")
        )

    def handler(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def response(self, status, value, rotate=True):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                if rotate:
                    peer.cookie = f"synthetic-work-rotation-{peer.requests}"
                    self.send_header(
                        "Set-Cookie",
                        f"auth_refresh_token={peer.cookie}; Path=/; HttpOnly; SameSite=Strict",
                    )
                self.end_headers()
                self.wfile.write(raw)

            def handle_request(self):
                route = urlsplit(self.path)
                query = parse_qs(route.query)
                if route.path == "/__test/status":
                    self.response(200, peer.status(), False)
                    return
                if route.path == "/__test/release":
                    peer.released.set()
                    self.response(200, {}, False)
                    return
                try:
                    assert self.headers.get("Authorization") is None
                    assert (
                        self.headers.get("Cookie")
                        == f"auth_refresh_token={peer.cookie}"
                    )
                    assert self.headers.get("X-OpenMates-SDK") == peer.identity
                    peer.requests += 1
                    peer.checks.add("cookie-only-identity-and-rotation")
                    team = peer.suite["team"]["team_id"]
                    if route.path == f"/v1/teams/{team}":
                        assert peer.vector.get("team") and self.command == "GET"
                        self.response(
                            200,
                            {
                                "team": {
                                    "team_id": team,
                                    "encrypted_team_key": peer.suite["team"][
                                        "encrypted_team_key"
                                    ],
                                }
                            },
                        )
                        return
                    family = (
                        "tasks"
                        if route.path.startswith("/v1/user-tasks")
                        else "projects"
                    )
                    base = "/v1/user-tasks" if family == "tasks" else "/v1/projects"
                    assert route.path == base or route.path.startswith(base + "/")
                    expected_team = (
                        [team]
                        if peer.vector.get("team")
                        and not (family == "tasks" and self.command == "POST")
                        else None
                    )
                    assert query.get("team_id") == expected_team, (
                        "explicit scope overrides ambient Team"
                    )
                    object_id = route.path.removeprefix(base).strip("/")
                    singular = "task" if family == "tasks" else "project"
                    if self.command == "GET":
                        if peer.vector["mode"] == "cancel" and not peer.blocked:
                            peer.blocked = True
                            assert peer.released.wait(timeout=10), (
                                "test release deadline"
                            )
                        if object_id:
                            self.response(200, {singular: peer.rows[object_id]})
                        else:
                            self.response(
                                200,
                                {family: list(peer.rows.values()), "complete": True},
                            )
                        return
                    if self.command == "DELETE":
                        assert object_id in peer.rows
                        if family == "tasks":
                            assert query["version"] == [
                                str(peer.rows[object_id]["version"])
                            ]
                        else:
                            assert query["confirmation_project_id"] == [object_id]
                        del peer.rows[object_id]
                        peer.writes += 1
                        peer.checks.add("canonical-confirmed-delete")
                        self.response(200, {"deleted": True})
                        return
                    length = int(self.headers["Content-Length"])
                    assert 0 < length < 65536
                    raw = self.rfile.read(length).decode()
                    payload = json.loads(raw)
                    assert not ({"model", "provider", "settings"} & payload.keys())
                    if self.command == "POST":
                        assert not object_id
                        peer.validate_create(family, payload, raw)
                        object_id = payload[f"{singular}_id"]
                        payload.setdefault("version", 1)
                        peer.rows[object_id] = payload
                    elif self.command == "PATCH":
                        current = peer.rows[object_id]
                        if family == "tasks":
                            assert payload["version"] == current["version"]
                            assert "due_at" in payload and payload["due_at"] is None
                            assert payload["status"] == "in_progress"
                        else:
                            assert payload["archived"] is True
                        name = "title" if family == "tasks" else "name"
                        assert (
                            decrypt(
                                payload[f"encrypted_{name}"], peer.keys[object_id]
                            ).decode()
                            == "Synthetic updated private text"
                        )
                        assert "Synthetic updated private text" not in raw
                        current.update(payload)
                        current["version"] += 1
                        peer.checks.add("versioned-encrypted-update")
                    else:
                        raise AssertionError("unexpected method")
                    peer.writes += 1
                    self.response(200, {singular: peer.rows[object_id]})
                except Exception:
                    peer.failure = peer.failure or "work-protocol-assertion"
                    self.response(
                        500, {"detail": "synthetic-private-server-diagnostic"}, False
                    )

            do_GET = handle_request
            do_POST = handle_request
            do_PATCH = handle_request
            do_DELETE = handle_request

        return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--vector", required=True)
    parser.add_argument("--identity", required=True)
    args = parser.parse_args()
    suite = json.loads(Path(args.fixture).read_bytes())["capabilities"][CAPABILITY]
    vector = next(v for v in suite["vectors"] if v["id"] == args.vector)
    if vector["mode"].startswith("saved_"):
        from session_saved_stream_peer import SavedStreamPeer

        peer = SavedStreamPeer(suite, vector, args.identity).start()
    else:
        peer = WorkPeer(suite, vector, args.identity).start()
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    try:
        threading.Event().wait()
    finally:
        peer.close()


if __name__ == "__main__":
    main()
