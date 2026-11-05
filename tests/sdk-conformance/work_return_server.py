#!/usr/bin/env python3
"""Synthetic Personal work reads for private Rust post-join lifecycle regressions."""

# contract-test-file: tooling
from __future__ import annotations

import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs, urlsplit

from recovery_server import encrypt

FAMILIES = {
    "tasks": "/v1/user-tasks",
    "plans": "/v1/user-plans",
    "projects": "/v1/projects",
    "workflows": "/v1/workflows",
}


def account(index):
    """Public synthetic keys; no installed profile or real account input."""
    return {
        "owner": f"{index + 1:08d}-1111-4111-8111-111111111111",
        "session": f"synthetic-return-session-{index}",
        "cookie": f"synthetic-return-cookie-{index}",
        "key": bytes(range(index * 32, index * 32 + 32)),
        "marker": f"Synthetic return private account {index}",
    }


class WorkReturnPeer:
    def __init__(self, family, identity):
        assert family in FAMILIES and identity in ("rust", "npm", "pip")
        self.family, self.identity = family, identity
        self.accounts = [account(0), account(1)]
        self.active = 0
        self.requests = self.reads = self.logouts = self.replacements = 0
        self.failure = None
        self.lock = threading.Lock()
        self.server = self.thread = None

    def status(self):
        return {
            "failure": self.failure,
            "requests": self.requests,
            "reads": self.reads,
            "logouts": self.logouts,
            "replacements": self.replacements,
            "generation": self.active,
        }

    def session(self, index, endpoint):
        a = self.accounts[index]
        return {
            "api_url": endpoint,
            "session_id": a["session"],
            "cookies": {"auth_refresh_token": a["cookie"]},
            "ws_token": None,
            "master_key": base64.b64encode(a["key"]).decode(),
            "hashed_email": "synthetic-return-email",
            "user_email_salt": "synthetic-return-salt",
            "email_encryption_key": None,
            "created_at": 1,
            "paired_session_expires_at": None,
            "active_team_id": None,
        }

    def row(self):
        a = self.accounts[self.active]
        key = bytes(range(64 + self.active * 32, 96 + self.active * 32))
        object_id = f"{self.active + 3:08d}-2222-4222-8222-222222222222"

        def text(value):
            return encrypt(value.encode(), key)

        owner_hash = hashlib.sha256(a["owner"].encode()).hexdigest()
        if self.family == "tasks":
            return {
                "task_id": object_id,
                "version": 1,
                "status": "todo",
                "priority": 0,
                "hashed_user_id": owner_hash,
                "encrypted_task_key": encrypt(key, a["key"]),
                "encrypted_title": text(a["marker"]),
                "encrypted_labels": text("[]"),
                "encrypted_linked_project_ids": text("[]"),
            }
        if self.family == "projects":
            return {
                "project_id": object_id,
                "version": 1,
                "archived": False,
                "hashed_user_id": owner_hash,
                "encrypted_project_key": encrypt(key, a["key"]),
                "encrypted_name": text(a["marker"]),
                "key_wrappers": [],
            }
        if self.family == "plans":
            return {
                "plan_id": object_id,
                "version": 1,
                "status": "draft",
                "hashed_user_id": owner_hash,
                "key_wrappers": [
                    {"key_type": "master", "encrypted_plan_key": encrypt(key, a["key"])}
                ],
                "encrypted_title": text(a["marker"]),
                "encrypted_user_flows": text("[]"),
                "encrypted_linked_project_ids": text("[]"),
            }
        # Workflow definitions are canonically server-visible; only slug is encrypted.
        return {
            "id": object_id,
            "title": a["marker"],
            "enabled": False,
            "graph": {"version": 1, "trigger_node_id": None, "nodes": [], "edges": []},
            "encrypted_slug": encrypt(a["marker"].encode(), a["key"]),
        }

    def dispatch(self, method, target, headers, body):
        """Pure request oracle, also used by focused no-socket unit fixtures."""
        with self.lock:
            try:
                route = urlsplit(target)
                query = parse_qs(route.query, keep_blank_values=True)
                if route.path == "/__test/status":
                    assert method == "GET" and not query and body is None
                    return 200, self.status()
                if route.path == "/__test/control":
                    assert method == "POST" and not query and body == {"op": "replace"}
                    assert self.active == 0, "replacement is single-use"
                    self.active = 1
                    self.replacements += 1
                    return 200, {"replaced": True}
                a = self.accounts[self.active]
                assert headers.get("Authorization") is None
                assert headers.get("Cookie") == f"auth_refresh_token={a['cookie']}"
                assert headers.get("X-OpenMates-SDK") == self.identity
                self.requests += 1
                assert self.requests <= 128
                if route.path == "/v1/auth/session":
                    assert (
                        method == "POST"
                        and not query
                        and body == {"session_id": a["session"]}
                    )
                    return 200, {
                        "success": True,
                        "user": {"id": a["owner"]},
                        "ws_token": f"synthetic-return-ws-{self.active}",
                    }
                if route.path == "/v1/auth/logout":
                    assert method == "POST" and not query and body == {}
                    self.logouts += 1
                    return 200, {"success": True}
                assert (
                    method == "GET"
                    and route.path == FAMILIES[self.family]
                    and body is None
                )
                # Exact current default Personal list routes. No Team/generic filters.
                assert query == (
                    {"limit": ["500"], "paginate": ["true"]}
                    if self.family == "tasks"
                    else {}
                )
                self.reads += 1
                return 200, {self.family: [self.row()], "complete": True}
            except Exception:
                self.failure = self.failure or "work-return-protocol-assertion"
                return 500, {"detail": "synthetic-work-return-refused"}

    def start(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def request(self):
                try:
                    self.connection.settimeout(5)
                    length = int(self.headers.get("Content-Length", "0"))
                    assert 0 <= length <= 65536
                    assert self.headers.get("Transfer-Encoding") is None
                    body = json.loads(self.rfile.read(length)) if length else None
                    status, value = peer.dispatch(
                        self.command, self.path, self.headers, body
                    )
                except Exception:
                    peer.failure = peer.failure or "work-return-http-assertion"
                    status, value = 500, {"detail": "synthetic-work-return-refused"}
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                self.wfile.write(raw)

            do_GET = do_POST = request

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=3)
            assert not self.thread.is_alive(), "fixture shutdown deadline"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", choices=FAMILIES, required=True)
    parser.add_argument("--identity", choices=("rust", "npm", "pip"), required=True)
    args = parser.parse_args()
    peer = WorkReturnPeer(args.family, args.identity).start()
    endpoint = f"http://127.0.0.1:{peer.server.server_port}"
    print(
        json.dumps(
            {
                "endpoint": endpoint,
                "initial_session": peer.session(0, endpoint),
                "replacement_session": peer.session(1, endpoint),
                "initial_private_marker": peer.accounts[0]["marker"],
                "replacement_private_marker": peer.accounts[1]["marker"],
            }
        ),
        flush=True,
    )
    try:
        threading.Event().wait()
    finally:
        peer.close()


if __name__ == "__main__":
    main()
