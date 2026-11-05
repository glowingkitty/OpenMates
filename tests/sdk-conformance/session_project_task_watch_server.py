#!/usr/bin/env python3
"""Independent bounded synthetic Cookie Project/source HTTP and task-only WS peer.

Test control is loopback-only and never exposed by a library. No product server,
provider, CLI, local profile, host presence, fake application ACK or mutation.
"""

# contract-test-file: tooling
from __future__ import annotations

import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid

from recovery_server import WebSocket, encrypt

CAPABILITY = "session.project-task-watch.v1"
DEADLINE = 8
MAX_BODY = 16 * 1024 * 1024


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


class WatchPeer:
    def __init__(self, suite, vector, identity):
        assert identity in ("rust", "npm", "pip")
        self.suite, self.vector, self.identity = suite, vector, identity
        self.master = base64.b64decode(suite["account"]["master_key"], validate=True)
        self.team_key = base64.b64decode(suite["team"]["team_key_b64"], validate=True)
        self.project_key = base64.b64decode(suite["project_key_b64"], validate=True)
        self.condition = threading.Condition(threading.RLock())
        self.failure = None
        self.cookie = suite["account"]["cookie"]
        self.rotate_next = False
        self.deny_source = False
        self.hold_upgrade = False
        self.hold_list = False
        self.stopped = False
        self.ttl_deadline = None
        self.counts = {
            "requests": 0,
            "upgrades": 0,
            "subscriptions": 0,
            "list_entered": 0,
            "source_requests": 0,
            "client_messages": 0,
        }
        self.resumes, self.sockets, self.past_sockets = [], {}, {}
        self.connections, self.past_connections, self.aliases = {}, {}, {}
        self.checks = set()
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
        with self.condition:
            self.stopped = True
            self.condition.notify_all()
            sockets = list(self.sockets.values())
        for ws in sockets:
            try:
                ws.handler.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(DEADLINE)

    def status(self):
        with self.condition:
            return {
                "failure": self.failure,
                **self.counts,
                "resumes": self.resumes[:],
                "active_generations": sorted(self.connections),
                "cookie": self.cookie,
                "checks": sorted(self.checks),
            }

    def wait(self, predicate):
        with self.condition:
            assert self.condition.wait_for(
                lambda: self.stopped or self.failure or predicate(), DEADLINE
            ), "bounded peer beacon"
            assert not self.stopped and self.failure is None, "peer failed or closed"

    def task(self, index, corruption=None):
        task_id = str(uuid.UUID(int=index + 1))
        key = hashlib.sha256(f"synthetic-watch-task-{index}".encode()).digest()
        wrapper = {
            "key_type": "project",
            "hashed_project_id": hashed(self.suite["project_id"]),
            "hashed_task_id": hashed(task_id),
            "hashed_user_id": hashed(self.suite["owner_id"]),
            "encrypted_task_key": encrypt(key, self.project_key),
            "expires_at": None,
        }
        row = {
            "task_id": task_id,
            "version": 1,
            "status": "todo",
            "hashed_user_id": hashed(self.suite["owner_id"]),
            "hashed_team_id": hashed(self.suite["team"]["team_id"])
            if self.vector.get("team")
            else None,
            "encrypted_title": encrypt(f"Synthetic watch Task {index}".encode(), key),
            "encrypted_description": encrypt(b"Synthetic private description", key),
            "key_wrappers": [wrapper],
            "dependencies": [],
            "opaque_fixture_metadata": {"preserved": True},
        }
        if corruption == "owner":
            row["hashed_user_id"] = hashed("foreign-owner")
        elif corruption == "project":
            wrapper["hashed_project_id"] = hashed("foreign-project")
        elif corruption == "team":
            row["hashed_team_id"] = hashed("foreign-team")
        elif corruption == "expired":
            wrapper["expires_at"] = 1
        elif corruption == "ciphertext":
            row["encrypted_title"] = row["encrypted_title"][:-4] + "AAAA"
        return row

    def frame(
        self, batch, cursor, tasks, part=0, final=True, reset=False, removed=None
    ):
        return {
            "project_id": self.suite["project_id"],
            "batch_id": batch,
            "part": part,
            "final": final,
            "reset": reset,
            "cursor": cursor,
            "tasks": tasks,
            "removed_task_ids": removed or [],
        }

    def register_socket(self, ws):
        with self.condition:
            index = 0
            while chr(97 + index) in self.sockets:
                index += 1
            name = chr(97 + index)
            self.counts["subscriptions"] += 1
            generation = self.counts["subscriptions"]
            self.sockets[name] = ws
            self.past_sockets[name] = ws
            self.connections[generation] = ws
            self.past_connections[generation] = ws
            self.condition.notify_all()
            return name, generation

    def remove_socket(self, name, generation, ws):
        with self.condition:
            if self.sockets.get(name) is ws:
                del self.sockets[name]
            if self.connections.get(generation) is ws:
                del self.connections[generation]
            self.condition.notify_all()

    def target(self, command, past=False):
        name = command["watch"]
        if "generation" in command:
            generation = command["generation"]
            assert type(generation) is int and generation > 0
            assert self.aliases.get(name) == generation, (
                "stale logical watch generation"
            )
            table = self.past_connections if past else self.connections
            assert generation in table, "bound watch connection is not live"
            return table[generation]
        # Existing private actor tests use physical names; public adapters bind
        # exact observed generations and never enter this legacy fixture seam.
        return (self.past_sockets if past else self.sockets)[name]

    def send(self, command, kind):
        if "generation" not in command:
            self.wait(lambda: command["watch"] in self.sockets)
        with self.condition:
            ws = self.target(command)
            if kind == "partial":
                ws.send(
                    "project_task_sync",
                    self.frame(
                        "baseline",
                        "epoch:1",
                        [self.task(i) for i in range(20)],
                        final=False,
                        reset=True,
                    ),
                )
            elif kind == "final":
                ws.send(
                    "project_task_sync",
                    self.frame(
                        "baseline", "epoch:1", [self.task(20)], part=1, reset=True
                    ),
                )
            elif kind == "baseline":
                ws.send(
                    "project_task_sync",
                    self.frame(
                        "baseline",
                        "epoch:1",
                        [self.task(i) for i in range(20)],
                        final=False,
                        reset=True,
                    ),
                )
                self.checks.add("multipart-first20-dispatched")
                ws.send(
                    "project_task_sync",
                    self.frame(
                        "baseline", "epoch:1", [self.task(20)], part=1, reset=True
                    ),
                )
            elif kind == "ttl":
                task = self.task(0)
                self.ttl_deadline = int(time.time()) + 3
                task["key_wrappers"][0]["expires_at"] = self.ttl_deadline
                ws.send(
                    "project_task_sync",
                    self.frame("ttl", "epoch:1", [task], reset=True),
                )
            elif kind == "delta":
                ws.send(
                    "project_task_sync",
                    self.frame(
                        "delta",
                        "epoch:2",
                        [self.task(21)],
                        removed=[str(uuid.UUID(int=1))],
                    ),
                )
            elif kind == "empty":
                ws.send("project_task_sync", self.frame("empty", "epoch:1", []))
            elif kind.startswith("bad-"):
                ws.send(
                    "project_task_sync",
                    self.frame("bad", "epoch:1", [self.task(0, kind[4:])], reset=True),
                )
            else:
                raise AssertionError("unknown frame kind")

    def control(self, command):
        assert isinstance(command, dict) and len(command) <= 4
        op = command["op"]
        if op == "bind_watch":
            assert type(command["after"]) is int and command["after"] >= 0
            assert command["source_id"] == self.suite["source_id"], (
                "foreign source binding"
            )
            after = command["after"]

            def available():
                return [
                    generation
                    for generation in self.connections
                    if generation > after
                    and not any(
                        other != command["watch"] and bound == generation
                        for other, bound in self.aliases.items()
                    )
                ]

            self.wait(lambda: bool(available()))
            with self.condition:
                candidates = available()
                assert len(candidates) == 1, "ambiguous connection generation"
                generation = candidates[0]
                previous = self.aliases.get(command["watch"])
                assert previous is None or previous not in self.connections, (
                    "logical alias still live"
                )
                assert not any(
                    other != command["watch"] and bound == generation
                    for other, bound in self.aliases.items()
                ), "connection already claimed"
                self.aliases[command["watch"]] = generation
                return {
                    **self.status(),
                    "generation": generation,
                    "source_id": self.suite["source_id"],
                    "project_id": self.suite["project_id"],
                }
        elif op == "ttl_elapsed":
            assert self.ttl_deadline is not None
            with self.condition:
                remaining = self.ttl_deadline - time.time()
                while remaining > 0:
                    self.condition.wait(timeout=remaining)
                    remaining = self.ttl_deadline - time.time()
                assert time.time() >= self.ttl_deadline, (
                    "actual wrapper TTL clock boundary"
                )
        elif op == "closed":
            self.wait(
                lambda: (
                    command["generation"] not in self.connections
                    if "generation" in command
                    else command["watch"] not in self.sockets
                )
            )
        elif op == "beacon":
            assert command["key"] in self.counts
            self.wait(lambda: self.counts[command["key"]] >= command["minimum"])
        elif op == "send":
            self.send(command, command["kind"])
        elif op == "late_force_logout":
            with self.condition:
                ws = self.target(command, past=True)
                try:
                    ws.send("force_logout", {"reason": "synthetic-old-transport"})
                except OSError:
                    pass  # Reset may already have closed the old transport.
                self.checks.add("old-transport-control-attempted-after-reset")
        elif op in ("drop", "revoke", "force_logout", "idle_flood"):
            if "generation" not in command:
                self.wait(lambda: command["watch"] in self.sockets)
            with self.condition:
                ws = self.target(command)
                if op == "drop":
                    ws.handler.connection.shutdown(socket.SHUT_RDWR)
                elif op == "revoke":
                    ws.send(
                        "project_task_sync_error",
                        {
                            "project_id": self.suite["project_id"],
                            "code": "access_revoked",
                        },
                    )
                elif op == "force_logout":
                    ws.send("force_logout", {"reason": "synthetic-fixture"})
                else:
                    # Finite bounded flood, not a timing sleep or hidden actor hook.
                    for i in range(1024):
                        ws.send("synthetic_idle", {"sequence": i})
        elif op in (
            "deny_source",
            "hold_upgrade",
            "release_upgrade",
            "hold_list",
            "release_list",
            "rotate",
        ):
            with self.condition:
                if op == "deny_source":
                    self.deny_source = True
                elif op == "rotate":
                    self.rotate_next = True
                elif op.endswith("upgrade"):
                    self.hold_upgrade = op == "hold_upgrade"
                else:
                    self.hold_list = op == "hold_list"
                self.condition.notify_all()
        else:
            raise AssertionError("unknown control operation")
        return self.status()

    def handler(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def response(self, status, body):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                if peer.rotate_next and not self.path.startswith("/__test/"):
                    peer.rotate_next = False
                    peer.cookie = "synthetic-watch-rotated"
                    self.send_header(
                        "Set-Cookie",
                        f"auth_refresh_token={peer.cookie}; Path=/; HttpOnly",
                    )
                self.end_headers()
                self.wfile.write(raw)

            def body(self):
                size = int(self.headers.get("Content-Length", "0"))
                assert 0 <= size <= MAX_BODY
                return json.loads(self.rfile.read(size)) if size else None

            def handle_request(self):
                try:
                    assert self.client_address[0] == "127.0.0.1"
                    route = urlsplit(self.path)
                    query = parse_qs(route.query, keep_blank_values=True)
                    if route.path == "/__test/status":
                        assert self.command == "GET"
                        self.response(200, peer.status())
                        return
                    if route.path == "/__test/control":
                        assert self.command == "POST"
                        self.response(200, peer.control(self.body()))
                        return
                    assert self.headers.get("Authorization") is None
                    assert (
                        self.headers.get("Cookie")
                        == f"auth_refresh_token={peer.cookie}"
                    )
                    assert self.headers.get("X-OpenMates-SDK") == peer.identity
                    assert self.headers.get("Origin") in (
                        None,
                        "https://app.example.invalid",
                    )
                    if route.path == "/v1/ws":
                        try:
                            self.websocket(query)
                        finally:
                            # The upgraded stream is never reused as HTTP.
                            self.close_connection = True
                        return
                    with peer.condition:
                        peer.counts["requests"] += 1
                        peer.condition.notify_all()
                    assert (
                        route.path != "/v1/ws" and self.headers.get("Upgrade") is None
                    )
                    if route.path == "/v1/auth/session":
                        assert self.command == "POST" and self.body() == {
                            "session_id": peer.suite["account"]["session_id"]
                        }
                        self.response(
                            200,
                            {
                                "success": True,
                                "ws_token": "synthetic-watch-ws",
                                "user": {
                                    "id": peer.suite["owner_id"],
                                    "username": "synthetic-watch",
                                },
                            },
                        )
                        return
                    assert self.command == "GET", (
                        "no mutation, host registration or invented ACK"
                    )
                    team = peer.suite["team"]["team_id"]
                    if route.path == f"/v1/teams/{team}":
                        assert peer.vector.get("team")
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
                    assert query == (
                        {"team_id": [team]} if peer.vector.get("team") else {}
                    )
                    if route.path == "/v1/projects":
                        with peer.condition:
                            peer.counts["list_entered"] += 1
                            peer.condition.notify_all()
                        peer.wait(lambda: not peer.hold_list)
                        self.response(200, {"projects": []})
                        return
                    base = f"/v1/projects/{peer.suite['project_id']}"
                    if route.path == base:
                        project = {
                            "project_id": peer.suite["project_id"],
                            "version": 1,
                            "encrypted_name": encrypt(
                                b"Synthetic watch Project", peer.project_key
                            ),
                            "encrypted_description": encrypt(
                                b"Synthetic watch description", peer.project_key
                            ),
                        }
                        if peer.vector.get("team"):
                            project["hashed_team_id"] = hashed(team)
                            project["key_wrappers"] = [
                                {
                                    "key_type": "team",
                                    "team_key_epoch": 1,
                                    "hashed_team_id": hashed(team),
                                    "encrypted_project_key": encrypt(
                                        peer.project_key, peer.team_key
                                    ),
                                }
                            ]
                        else:
                            project["encrypted_project_key"] = encrypt(
                                peer.project_key, peer.master
                            )
                        self.response(200, {"project": project})
                    elif route.path == base + "/sources":
                        with peer.condition:
                            peer.counts["source_requests"] += 1
                            peer.condition.notify_all()
                        if peer.deny_source:
                            self.response(403, {"detail": "synthetic-source-denied"})
                        else:
                            self.response(
                                200,
                                {
                                    "sources": [
                                        {
                                            "source_id": peer.suite["source_id"],
                                            "status": "offline",
                                        }
                                    ]
                                },
                            )
                    else:
                        raise AssertionError("unapproved canonical route")
                except (BrokenPipeError, ConnectionResetError, EOFError):
                    pass
                except Exception as error:
                    with peer.condition:
                        peer.failure = type(error).__name__
                        peer.condition.notify_all()
                    try:
                        self.response(
                            500,
                            {"error": "fixture_rejected", "failure_code": peer.failure},
                        )
                    except OSError:
                        pass

            def websocket(self, query):
                assert self.command == "GET"
                assert set(query) == {"token", "sessionId", "client_capabilities"}
                assert query["token"] == ["synthetic-watch-ws"] and query[
                    "client_capabilities"
                ] == [""]
                assert str(uuid.UUID(query["sessionId"][0])) == query["sessionId"][0]
                with peer.condition:
                    peer.counts["upgrades"] += 1
                    peer.condition.notify_all()
                peer.wait(lambda: not peer.hold_upgrade)
                assert self.headers.get("Upgrade", "").lower() == "websocket"
                accept = base64.b64encode(
                    hashlib.sha1(
                        (
                            self.headers["Sec-WebSocket-Key"]
                            + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                        ).encode()
                    ).digest()
                ).decode()
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.end_headers()
                ws = WebSocket(self)
                self.connection.settimeout(DEADLINE)
                assert ws.receive() == {
                    "type": "native_client_lifecycle",
                    "payload": {
                        "client_type": peer.identity,
                        "is_foreground": False,
                        "interactive": False,
                    },
                }
                sub = ws.receive()
                assert sub["type"] == "project_task_sync_subscribe"
                expected = {
                    "bindings": [
                        {
                            "project_id": peer.suite["project_id"],
                            "source_id": peer.suite["source_id"],
                            "cursor": sub["payload"]["bindings"][0]["cursor"],
                        }
                    ]
                }
                if peer.vector.get("team"):
                    expected["team_id"] = peer.suite["team"]["team_id"]
                assert sub["payload"] == expected
                with peer.condition:
                    name, generation = peer.register_socket(ws)
                    peer.resumes.append(expected["bindings"][0]["cursor"])
                    peer.checks.update(
                        ("cookie-source-project-auth", "task-only-no-host-no-wire-ack")
                    )
                try:
                    while not peer.stopped:
                        try:
                            msg = ws.receive()
                        except socket.timeout:
                            continue
                        if msg is None:
                            break
                        if msg.get("type") == "ping":
                            assert set(msg) <= {"type", "payload"}
                            ws.send("pong", {})
                        else:
                            with peer.condition:
                                peer.counts["client_messages"] += 1
                            raise AssertionError("no invented ACK or host/job messages")
                except (EOFError, OSError):
                    pass
                finally:
                    peer.remove_socket(name, generation, ws)

            do_GET = handle_request
            do_POST = handle_request
            do_DELETE = handle_request
            do_PATCH = handle_request

        return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--vector", required=True)
    parser.add_argument("--identity", choices=("rust", "npm", "pip"), required=True)
    args = parser.parse_args()
    suite = json.loads(args.fixture.read_text())["capabilities"][CAPABILITY]
    vector = next(v for v in suite["vectors"] if v["id"] == args.vector)
    peer = WatchPeer(suite, vector, args.identity).start()
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        peer.close()


if __name__ == "__main__":
    main()
