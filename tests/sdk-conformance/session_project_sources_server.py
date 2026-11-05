#!/usr/bin/env python3
"""Independent synthetic source-authoring peer; never an SDK/runtime fallback."""

# contract-test-file: tooling
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
from http.server import BaseHTTPRequestHandler
import json
import math
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit

from recovery_server import decrypt, encrypt
from session_work_server import WorkPeer

CAPABILITY = "session.project-source-authoring.v1"


def exact_json_equal(left, right):
    """Compare JSON values without Python's boolean/number coercion."""

    def validate(value):
        if value is None or type(value) in (str, bool, int):
            return
        if type(value) is float and math.isfinite(value):
            return
        if type(value) is list:
            for item in value:
                validate(item)
            return
        if type(value) is dict and all(type(key) is str for key in value):
            for item in value.values():
                validate(item)
            return
        raise ValueError("non-JSON comparison value")

    def equal(a, b):
        if type(a) in (int, float) and type(b) in (int, float):
            return a == b
        if type(a) is not type(b):
            return False
        if type(a) is dict:
            return a.keys() == b.keys() and all(equal(a[key], b[key]) for key in a)
        if type(a) is list:
            return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
        return a == b

    validate(left)
    validate(right)
    return equal(left, right)


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


class SourcesPeer(WorkPeer):
    def __init__(self, suite, vector, identity):
        super().__init__(suite, vector, identity)
        self.project_key = base64.b64decode(suite["project_key_b64"], validate=True)
        self.case = 0
        self.mutation_attempts = 0
        self.source_reads = 0
        self.project_reads = 0
        self.team_reads = 0
        self.accepted = 0
        self.entered = threading.Event()
        self.condition = threading.Condition()
        self.source = None
        self.saved_ciphertext = None

    def status(self):
        return {
            **super().status(),
            "mutation_attempts": self.mutation_attempts,
            "source_reads": self.source_reads,
            "project_reads": self.project_reads,
            "team_reads": self.team_reads,
            "accepted": self.accepted,
            "entered": self.entered.is_set(),
        }

    def selected(self):
        return self.vector["cases"][self.case]

    def scoped(self, raw):
        raw["hashed_project_id"] = hashed(self.suite["project_id"])
        raw["hashed_user_id"] = (
            None if self.vector.get("team") else hashed(self.suite["owner_id"])
        )
        raw["hashed_team_id"] = (
            hashed(self.suite["team"]["team_id"]) if self.vector.get("team") else None
        )
        return raw

    def seed(self, source_id):
        seed = self.suite["seed"]
        return self.scoped(
            {
                **{
                    k: copy.deepcopy(v)
                    for k, v in seed.items()
                    if k not in ("display_name", "metadata")
                },
                "source_id": source_id,
                "encrypted_display_name": encrypt(
                    seed["display_name"].encode(), self.project_key
                ),
                "encrypted_metadata": encrypt(
                    json.dumps(seed["metadata"], ensure_ascii=False).encode(),
                    self.project_key,
                ),
            }
        )

    def control(self, command):
        assert isinstance(command, dict) and len(command) <= 2
        if command["op"] == "case":
            index = command["index"]
            assert type(index) is int and 0 <= index < len(self.vector["cases"])
            self.case = index
            self.source = (
                self.seed(self.selected()["source_id"])
                if self.selected()["operation"] == "patch"
                else None
            )
            if self.source:
                self.saved_ciphertext = (
                    self.source["encrypted_display_name"],
                    self.source["encrypted_metadata"],
                )
        elif command["op"] == "entered":
            assert self.entered.wait(timeout=8), "mutation admission beacon deadline"
        elif command["op"] == "release":
            self.released.set()
        elif command["op"] == "await_expiry":
            deadline = command["deadline_ms"]
            assert (
                type(deadline) is int
                and 0 < deadline - time.time_ns() // 1_000_000 <= 5000
            )
            with self.condition:
                while (remaining := deadline / 1000 - time.time()) > 0:
                    self.condition.wait(timeout=remaining)
        else:
            raise AssertionError("unknown test control")
        return self.status()

    def acknowledge(self, raw, fault):
        value = copy.deepcopy(raw)
        if fault == "missing-source":
            return {}
        if fault == "missing-ciphertext":
            del value["encrypted_metadata"]
        elif fault == "invalid-enum":
            value["source_type"] = "foreign_type"
        elif fault == "negative-timestamp":
            value["created_at"] = -1
        elif fault == "nonobject-metadata":
            value["encrypted_metadata"] = encrypt(b"[]", self.project_key)
        elif fault == "foreign-owner":
            value["hashed_user_id"] = hashed("foreign-owner")
        elif fault == "foreign-project":
            value["hashed_project_id"] = hashed("foreign-project")
        elif fault == "foreign-team":
            value["hashed_team_id"] = hashed("foreign-team")
        elif fault == "personal-owner-in-team":
            value["hashed_user_id"] = hashed(self.suite["owner_id"])
        elif fault == "reencoded-ciphertext":
            value["encrypted_display_name"] = encrypt(
                self.suite["seed"]["display_name"].encode(), self.project_key
            )
        elif fault == "revoked":
            value["status"] = "revoked"
        elif fault == "wrong-source":
            value["source_id"] = "foreign-source"
        elif fault == "wrong-capabilities":
            value["capabilities"] = ["read"]
        elif fault == "wrong-updated-at":
            value["updated_at"] += 1
        elif fault == "wrong-cipher-key":
            value["encrypted_metadata"] = encrypt(b"{}", bytes([42]) * 32)
        return {"source": value}

    def handler(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def response(self, code, value, rotate=False):
                body = json.dumps(value).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                if rotate:
                    peer.cookie = f"synthetic-source-rotation-{peer.requests}"
                    self.send_header(
                        "Set-Cookie",
                        f"auth_refresh_token={peer.cookie}; Path=/; HttpOnly",
                    )
                self.end_headers()
                self.wfile.write(body)

            def body(self):
                length = int(self.headers.get("Content-Length", 0))
                assert 0 <= length <= 1024 * 1024
                return json.loads(self.rfile.read(length)) if length else None

            def handle_request(self):
                try:
                    assert self.client_address[0] == "127.0.0.1"
                    route = urlsplit(self.path)
                    if route.path == "/__test/status":
                        assert self.command == "GET"
                        self.response(200, peer.status())
                        return
                    if route.path == "/__test/control":
                        assert self.command == "POST"
                        self.response(200, peer.control(self.body()))
                        return
                    if peer.vector["mode"] == "read-api-key":
                        assert (
                            self.headers.get("Authorization")
                            == "Bearer sk-api-syntheticsources"
                        )
                        assert self.headers.get("Cookie") is None
                        assert (
                            self.command == "GET"
                            and route.path
                            == f"/v1/projects/{peer.suite['project_id']}/sources"
                        )
                    else:
                        assert self.headers.get("Authorization") is None
                        assert (
                            self.headers.get("Cookie")
                            == f"auth_refresh_token={peer.cookie}"
                        )
                    assert self.headers.get("X-OpenMates-SDK") == peer.identity
                    assert self.headers.get("Upgrade") is None, (
                        "source mutation confers no WS/host authority"
                    )
                    peer.requests += 1
                    assert peer.requests <= 128, "bounded fixture request count"
                    case = peer.selected()
                    fault = case["fault"]
                    if route.path == "/v1/auth/logout":
                        # Internal post-join lifecycle regression only. This is
                        # the real SDK logout route, never a source/host ACK.
                        assert self.command == "POST" and self.body() == {}
                        peer.checks.add("canonical-cookie-owner-logout")
                        self.response(200, {"success": True})
                        return
                    if route.path == "/v1/auth/session":
                        assert self.command == "POST" and self.body() == {
                            "session_id": peer.suite["account"]["session_id"]
                        }
                        self.response(
                            200,
                            {
                                "success": True,
                                "user": {"id": peer.suite["owner_id"]},
                                "ws_token": "synthetic-source-ws",
                            },
                            True,
                        )
                        return
                    team = peer.suite["team"]["team_id"]
                    if route.path == f"/v1/teams/{team}":
                        assert self.command == "GET" and peer.vector.get("team")
                        peer.team_reads += 1
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
                            True,
                        )
                        return
                    assert parse_qs(route.query) == (
                        {"team_id": [team]} if peer.vector.get("team") else {}
                    )
                    base = f"/v1/projects/{peer.suite['project_id']}"
                    if route.path == base:
                        assert self.command == "GET"
                        peer.project_reads += 1
                        project = {
                            "project_id": peer.suite["project_id"],
                            "version": 1,
                            "encrypted_name": encrypt(
                                b"Synthetic Project", peer.project_key
                            ),
                            "encrypted_description": encrypt(
                                b"Synthetic private Project", peer.project_key
                            ),
                        }
                        if peer.vector.get("team"):
                            project["hashed_team_id"] = hashed(team)
                            project["key_wrappers"] = [
                                {
                                    "key_type": "team",
                                    "hashed_team_id": hashed(team),
                                    "team_key_epoch": 2
                                    if fault == "team-epoch2"
                                    else 1,
                                    "encrypted_project_key": encrypt(
                                        peer.project_key, peer.team
                                    ),
                                }
                            ]
                        else:
                            project["encrypted_project_key"] = encrypt(
                                peer.project_key, peer.master
                            )
                        self.response(200, {"project": project}, True)
                        return
                    expected_path = base + "/sources"
                    if case["operation"] in ("list-raw", "list-names"):
                        assert self.command == "GET" and route.path == expected_path
                        assert self.body() is None
                        peer.source_reads += 1
                        if peer.vector["mode"] == "read-cancel" and peer.case == 0:
                            peer.entered.set()
                            assert peer.released.wait(timeout=8), (
                                "original source read release deadline"
                            )
                        code = (
                            403
                            if fault == "http403"
                            else 409
                            if fault == "http409"
                            else 200
                        )
                        self.response(
                            code,
                            case["response"]
                            if code == 200
                            else {"detail": "synthetic-policy-refusal"},
                            True,
                        )
                        return
                    assert self.command == (
                        "POST" if case["operation"] == "create" else "PATCH"
                    )
                    if self.command == "POST":
                        assert route.path == expected_path
                    else:
                        assert route.path.startswith(expected_path + "/")
                        segment = route.path[len(expected_path) + 1 :]
                        assert (
                            "/" not in segment and unquote(segment) == case["source_id"]
                        )
                        assert unquote(segment) not in (".", "..")
                    payload = self.body()
                    peer.mutation_attempts += 1
                    if self.command == "POST":
                        expected = case["input"]
                        assert set(payload) == {
                            "source_id",
                            "source_type",
                            "encrypted_display_name",
                            "encrypted_metadata",
                            "capabilities",
                            "status",
                            "created_at",
                            "updated_at",
                            "last_indexed_at",
                        }
                        assert (
                            decrypt(
                                payload["encrypted_display_name"], peer.project_key
                            ).decode()
                            == expected["display_name"]
                        )
                        assert exact_json_equal(
                            json.loads(
                                decrypt(payload["encrypted_metadata"], peer.project_key)
                            ),
                            expected["metadata"],
                        )
                        assert (
                            len(payload["encrypted_display_name"]) <= 128000
                            and len(payload["encrypted_metadata"]) <= 128000
                        )
                        for key, value in expected.items():
                            if key not in ("display_name", "metadata"):
                                assert payload[key] == value
                        wire = json.dumps(payload)
                        for private in (
                            expected["display_name"],
                            expected["metadata"].get("root"),
                            expected["metadata"].get("binding_root"),
                        ):
                            if private:
                                assert private not in wire
                        peer.source = peer.scoped(copy.deepcopy(payload))
                        peer.checks.update(
                            (
                                "full-arbitrary-metadata-encrypted",
                                "exact-project-key",
                                "no-plaintext-wire",
                            )
                        )
                    else:
                        assert payload == case["input"]
                        assert set(payload) == {"capabilities", "updated_at"}
                        assert (
                            peer.source["encrypted_display_name"],
                            peer.source["encrypted_metadata"],
                        ) == peer.saved_ciphertext
                        peer.source.update(payload)
                        peer.checks.add("patch-retains-identical-encrypted-fields")
                    if fault in ("http403", "http409"):
                        self.response(
                            403 if fault == "http403" else 409,
                            {"detail": "synthetic-policy-refusal"},
                            True,
                        )
                        return
                    peer.accepted += 1
                    if peer.vector["mode"] == "cancel" and peer.case == 0:
                        peer.entered.set()
                        assert peer.released.wait(timeout=8), (
                            "accepted mutation release deadline"
                        )
                    self.response(200, peer.acknowledge(peer.source, fault), True)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as error:
                    peer.failure = type(error).__name__
                    self.response(500, {"failure_code": peer.failure})

            do_GET = handle_request
            do_POST = handle_request
            do_PATCH = handle_request
            do_DELETE = handle_request

        return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--vector", required=True)
    parser.add_argument("--identity", choices=("rust", "npm", "pip"), required=True)
    args = parser.parse_args()
    suite = json.loads(args.fixture.read_text())["capabilities"][CAPABILITY]
    vector = next(v for v in suite["vectors"] if v["id"] == args.vector)
    peer = SourcesPeer(suite, vector, args.identity).start()
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    try:
        threading.Event().wait()
    finally:
        peer.close()


if __name__ == "__main__":
    main()
