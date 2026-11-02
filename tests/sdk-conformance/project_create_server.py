#!/usr/bin/env python3
"""One synthetic ephemeral-loopback peer for direct SDK Project creation."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import traceback
from urllib.parse import parse_qs, urlsplit
import uuid

from recovery_server import decrypt, hkdf

CAPABILITY = "protocol.project-create.v1"


class ProjectCreatePeer:
    def __init__(self, suite, vector, identity):
        assert identity in ("rust", "npm", "pip")
        self.suite, self.vector, self.identity = suite, vector, identity
        self.master = base64.b64decode(suite["account"]["master_key_b64"])
        self.team = base64.b64decode(suite["team"]["team_key_b64"])
        self.keys, self.focus_ids, self.project_ids = set(), set(), set()
        self.failure, self.posts, self.checks = None, 0, set()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        self.server.daemon_threads = True
        self.thread = None

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        if self.thread:
            self.thread.join(timeout=3)

    def status(self):
        return {
            "failure": self.failure,
            "posts": self.posts,
            "checks": sorted(self.checks),
        }

    def validate(self, raw, payload):
        required = {
            "project_id",
            "encrypted_name",
            "created_at",
            "updated_at",
            "last_opened_at",
            "write_mode",
            "default_focus_id",
            "encrypted_settings",
        }
        assert required <= payload.keys(), "backend required fields"
        assert payload["write_mode"] == "always_ask", "safe compatibility write policy"
        assert not payload.get("chat_organization_only", False)
        assert "settings" not in payload and "default_focus" not in payload
        project_id, focus_id = payload["project_id"], payload["default_focus_id"]
        assert (
            str(uuid.UUID(project_id)) == project_id
            and uuid.UUID(project_id).version == 4
        )
        assert str(uuid.UUID(focus_id)) == focus_id and uuid.UUID(focus_id).version == 4
        assert (
            project_id not in self.project_ids
            and focus_id not in self.focus_ids
            and project_id != focus_id
        )
        self.project_ids.add(project_id)
        self.focus_ids.add(focus_id)
        if self.vector["team"]:
            wrappers = payload["key_wrappers"]
            assert payload["encrypted_project_key"] is None and len(wrappers) == 1
            wrapper = wrappers[0]
            assert wrapper["key_type"] == "team"
            assert (
                wrapper["hashed_team_id"]
                == hashlib.sha256(self.suite["team"]["team_id"].encode()).hexdigest()
            )
            assert wrapper["team_key_epoch"] == 1 and wrapper["wrapper_version"] == 1
            key = decrypt(wrapper["encrypted_project_key"], self.team)
            lookup_key = self.team
        else:
            assert payload["key_wrappers"] == []
            key = decrypt(payload["encrypted_project_key"], self.master)
            lookup_key = self.master
        assert (
            len(key) == 32
            and key not in (self.master, self.team)
            and key not in self.keys
        )
        self.keys.add(key)
        expected = self.vector["expected"]
        for field in ("name", "description", "icon", "color", "slug"):
            assert (
                decrypt(payload[f"encrypted_{field}"], key).decode() == expected[field]
            )
        assert payload["pinned"] == expected["pinned"]
        index = hkdf(lookup_key, b"", b"openmates-object-slug-index-v1")
        assert (
            payload["slug_lookup_hash"]
            == hmac.new(index, expected["slug"].encode(), hashlib.sha256).hexdigest()
        )
        settings = json.loads(decrypt(payload["encrypted_settings"], key))
        assert settings.keys() == {"default_focus"}
        focus = settings["default_focus"]
        assert focus == {
            "focus_id": focus_id,
            "name": f"Work on {expected['name']}",
            "instructions": f"Help with work in {expected['name']}. Follow the user's instructions and the Project's connected source guidance.",
            "source": "generated",
        }
        assert all(
            isinstance(payload[field], int) and payload[field] > 0
            for field in ("created_at", "updated_at", "last_opened_at")
        )
        for secret in (
            self.suite["account"]["setup_secret"],
            self.suite["account"]["master_key_b64"],
            base64.b64encode(key).decode(),
            expected["name"],
            expected["description"],
        ):
            if secret:
                assert secret not in raw, "private fields stay encrypted locally"
        self.checks.update(
            (
                "backend-required-fields",
                "fresh-project-key-and-focus",
                "canonical-encrypted-default-focus",
                "encrypted-private-fields",
                "scope-bound-key-wrapper",
                "secret-free-wire",
                "safe-write-policy",
            )
        )

    def handler(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def response(self, status, value):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def check_headers(self):
                assert (
                    self.headers.get("Authorization")
                    == "Bearer " + peer.suite["account"]["bearer"]
                )
                assert self.headers.get("X-OpenMates-SDK") == peer.identity
                assert peer.suite["account"]["setup_secret"] not in str(self.headers)
                peer.checks.add("bearer-only-transport")

            def do_GET(self):
                try:
                    if self.path == "/__test/status":
                        self.response(200, peer.status())
                        return
                    self.check_headers()
                    if self.path == f"/v1/teams/{peer.suite['team']['team_id']}":
                        self.response(
                            200,
                            {
                                "team": {
                                    "team_id": peer.suite["team"]["team_id"],
                                    "encrypted_team_key": peer.suite["team"][
                                        "encrypted_team_key"
                                    ],
                                }
                            },
                        )
                    else:
                        raise AssertionError("unexpected request")
                except Exception:
                    peer.failure = peer.failure or "project-get"
                    self.response(500, {})

            def do_POST(self):
                try:
                    self.check_headers()
                    route = urlsplit(self.path)
                    length = int(self.headers["Content-Length"])
                    assert 0 < length < 65536
                    raw = self.rfile.read(length).decode()
                    payload = json.loads(raw)
                    if route.path == "/v1/sdk/session":
                        assert payload == {
                            "sdk_name": peer.identity,
                            "device_identity": "synthetic-project-fixture",
                        }
                        self.response(
                            200, {"key_wrapper": peer.suite["account"]["key_wrapper"]}
                        )
                        return
                    assert route.path == "/v1/projects"
                    expected_query = (
                        {"team_id": [peer.suite["team"]["team_id"]]}
                        if peer.vector["team"]
                        else {}
                    )
                    assert parse_qs(route.query) == expected_query
                    peer.posts += 1
                    assert not peer.vector["error"], "invalid input dispatched"
                    peer.validate(raw, payload)
                    self.response(200, {"project": {**payload, "version": 1}})
                except Exception as error:
                    where = traceback.extract_tb(error.__traceback__)[-1]
                    peer.failure = (
                        peer.failure or f"project-create:{where.name}:{where.lineno}"
                    )
                    self.response(
                        422, {"detail": "synthetic private server diagnostic"}
                    )

        return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--vector", required=True)
    parser.add_argument("--identity", choices=("rust", "npm", "pip"), required=True)
    args = parser.parse_args()
    suite = json.loads(Path(args.fixture).read_bytes())["capabilities"][CAPABILITY]
    vector = next(vector for vector in suite["vectors"] if vector["id"] == args.vector)
    peer = ProjectCreatePeer(suite, vector, args.identity)
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    peer.server.serve_forever()


if __name__ == "__main__":
    main()
