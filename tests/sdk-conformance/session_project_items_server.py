#!/usr/bin/env python3
"""Synthetic loopback-only Project links peer; never a runtime SDK delegate."""

# contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from http.server import BaseHTTPRequestHandler

from recovery_server import decrypt
from session_work_server import WorkPeer

CAPABILITY = "session.project-items.v1"


class ProjectItemsPeer(WorkPeer):
    def __init__(self, suite, vector, identity):
        super().__init__(suite, vector, identity)
        self.detail = copy.deepcopy(
            suite["team_detail" if vector.get("team") else "personal_detail"]
        )
        self.targets = [item["target_id"] for item in suite["expected"]["items"]]
        self.deleted_links = 0
        project = self.detail["project"]
        wrapped = (
            project["key_wrappers"][0]["encrypted_project_key"]
            if vector.get("team")
            else project["encrypted_project_key"]
        )
        key = decrypt(wrapped, self.team if vector.get("team") else self.master)
        assert len(key) == 32 and key not in (self.master, self.team)
        assert (
            decrypt(project["encrypted_name"], key).decode()
            == "Synthetic private Project"
        )
        for row, expected in zip(
            self.detail["items"], suite["expected"]["items"], strict=True
        ):
            assert (
                decrypt(row["target_id_encrypted"], key).decode()
                == expected["target_id"]
            )
            assert (
                decrypt(row["encrypted_display_name"], key).decode()
                == expected["display_name"]
            )
        self.checks.add("independent-aes-project-and-child-fixtures")
        if vector["mode"] == "tamper":
            self.detail["items"][0]["hashed_project_id"] = "foreign-project"
        if vector["mode"] == "permission":
            project["mutation_permissions"] = {
                "manage_any_items": False,
                "manage_own_items": False,
            }

    def status(self):
        return {
            **super().status(),
            "targets": self.targets,
            "deleted_links": self.deleted_links,
            "remaining_links": len(self.detail["items"]),
        }

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
                    peer.cookie = f"synthetic-project-items-rotation-{peer.requests}"
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
                    assert self.headers.get("Origin") == peer.endpoint
                    assert int(self.headers.get("Content-Length", "0")) == 0
                    peer.requests += 1
                    peer.checks.add("cookie-only-identity-and-rotation")
                    team = peer.suite["team"]["team_id"]
                    if route.path == f"/v1/teams/{team}":
                        assert (
                            peer.vector.get("team")
                            and self.command == "GET"
                            and not query
                        )
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
                    assert query.get("team_id") == (
                        [team] if peer.vector.get("team") else None
                    )
                    base = f"/v1/projects/{peer.suite['project_id']}"
                    if self.command == "GET":
                        assert route.path == base
                        if peer.vector["mode"] == "cancel" and not peer.blocked:
                            peer.blocked = True
                            assert peer.released.wait(timeout=10)
                        self.response(200, peer.detail)
                    elif self.command == "DELETE":
                        assert route.path == base + "/items", (
                            "never delete Project or underlying targets"
                        )
                        assert query.get("item_type") == [
                            peer.vector.get("item_type", "chat")
                        ]
                        assert query.get("target_id") == [peer.suite["target_id"]]
                        assert set(query) == (
                            {"item_type", "target_id", "team_id"}
                            if peer.vector.get("team")
                            else {"item_type", "target_id"}
                        )
                        peer.writes += 1
                        peer.checks.add("exact-type-and-target-link-only-delete")
                        if peer.vector["mode"] == "receipt":
                            self.response(200, {"deleted": True, "deleted_count": 0})
                        else:
                            count = 0 if peer.vector["mode"] == "noop" else 1
                            peer.deleted_links += count
                            if count:
                                peer.detail["items"] = [
                                    row
                                    for row in peer.detail["items"]
                                    if row["item_type"]
                                    != peer.vector.get("item_type", "chat")
                                ]
                            self.response(
                                200, {"deleted": count > 0, "deleted_count": count}
                            )
                    else:
                        raise AssertionError("unexpected method")
                except Exception:
                    peer.failure = "Project link protocol assertion failed"
                    self.response(
                        500, {"detail": "synthetic-private-server-diagnostic"}
                    )

            do_GET = handle_request
            do_DELETE = handle_request

        return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--vector", required=True)
    parser.add_argument("--identity", choices=("rust", "npm", "pip"), required=True)
    args = parser.parse_args()
    suite = json.loads(Path(args.fixture).read_bytes())["capabilities"][CAPABILITY]
    vector = next(v for v in suite["vectors"] if v["id"] == args.vector)
    peer = ProjectItemsPeer(suite, vector, args.identity).start()
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    try:
        peer.thread.join()
    finally:
        peer.close()
