#!/usr/bin/env python3
"""One synthetic peer for encrypted Plans and consented Workflow protocols."""

from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit
import uuid

from recovery_server import decrypt, encrypt
from session_work_server import WorkPeer

CAPABILITY = "session.plans-workflows.v1"


class PlansWorkflowsPeer(WorkPeer):
    def __init__(self, suite, vector, identity):
        super().__init__(suite, vector, identity)
        self.project_key = bytes(range(96, 128))
        self.run_posts, self.polls, self.cancel_posts = 0, 0, 0

    def status(self):
        return {
            **super().status(),
            "run_posts": self.run_posts,
            "polls": self.polls,
            "cancel_posts": self.cancel_posts,
        }

    def plan_create(self, payload, raw):
        plan_id = payload["plan_id"]
        assert str(uuid.UUID(plan_id)) == plan_id
        wrappers = payload["key_wrappers"]
        assert len(wrappers) == 2
        master = next(w for w in wrappers if w["key_type"] == "master")
        project = next(w for w in wrappers if w["key_type"] == "project")
        assert (
            project["hashed_project_id"]
            == hashlib.sha256(self.suite["project_id"].encode()).hexdigest()
        )
        key = decrypt(master["encrypted_plan_key"], self.master)
        assert decrypt(project["encrypted_plan_key"], self.project_key) == key
        assert len(key) == 32 and key not in (self.master, self.project_key)
        for name in ("title", "goal", "scope_in"):
            expected = self.suite["input"]["plan"][name]
            assert decrypt(payload["encrypted_" + name], key).decode() == expected
            assert expected not in raw
        flows = json.loads(decrypt(payload["encrypted_user_flows"], key))
        assert flows == self.suite["input"]["plan"]["user_flows"]
        assert "Synthetic private flow" not in raw
        assert json.loads(decrypt(payload["encrypted_linked_project_ids"], key)) == [
            self.suite["project_id"]
        ]
        assert payload["linked_project_ids"] == [self.suite["project_id"]]
        self.keys[plan_id] = key
        self.checks.update(
            (
                "encrypted-plan-private-fields",
                "plan-master-project-wrappers",
                "typed-flow-roundtrip",
            )
        )

    def workflow_create(self, payload):
        wrapping = self.team if self.vector.get("team") else self.master
        assert payload["title"] == self.suite["input"]["workflow"]["title"]
        assert payload["graph"] == self.suite["input"]["workflow"]["graph"]
        assert "slug" not in payload
        assert (
            decrypt(payload["encrypted_slug"], wrapping).decode()
            == "synthetic-workflow"
        )
        assert payload["team_id"] == (
            self.suite["team"]["team_id"] if self.vector.get("team") else None
        )
        self.checks.update(
            (
                "canonical-server-visible-definition",
                "encrypted-workflow-slug",
                "opaque-variable-names-preserved",
            )
        )

    def run(self, status):
        run = {
            "id": self.suite["run_id"],
            "workflow_id": self.suite["workflow_id"],
            "status": status,
        }
        if status == "completed":
            run["output_summary"] = {
                "deliveries": {
                    "end": {
                        "delivery_id": "11111111-1111-4111-8111-111111111111",
                        "chat_id": "22222222-2222-4222-8222-222222222222",
                        "message_id": "33333333-3333-4333-8333-333333333333",
                        "status": "acknowledged",
                    }
                }
            }
        return run

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
                    peer.cookie = f"synthetic-plans-workflows-{peer.requests}"
                    self.send_header(
                        "Set-Cookie",
                        f"auth_refresh_token={peer.cookie}; Path=/; HttpOnly; SameSite=Strict",
                    )
                self.end_headers()
                self.wfile.write(raw)

            def body(self):
                size = int(self.headers["Content-Length"])
                assert 0 < size < 262144
                raw = self.rfile.read(size).decode()
                assert peer.suite["account"]["master_key"] not in raw
                payload = json.loads(raw)
                assert not ({"model", "provider"} & payload.keys())
                return payload, raw

            def request(self):
                route = urlsplit(self.path)
                query = parse_qs(route.query)
                if route.path == "/__test/status":
                    self.response(200, peer.status(), False)
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
                    if route.path == f"/v1/teams/{peer.suite['team']['team_id']}":
                        assert peer.vector.get("team") and self.command == "GET"
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
                        return
                    if route.path == f"/v1/projects/{peer.suite['project_id']}":
                        assert self.command == "GET" and not query
                        self.response(
                            200,
                            {
                                "project": {
                                    "project_id": peer.suite["project_id"],
                                    "encrypted_project_key": encrypt(
                                        peer.project_key, peer.master
                                    ),
                                }
                            },
                        )
                        return
                    is_plan = route.path.startswith("/v1/user-plans")
                    base = "/v1/user-plans" if is_plan else "/v1/workflows"
                    assert route.path == base or route.path.startswith(base + "/")
                    assert query.get("team_id") == (
                        [peer.suite["team"]["team_id"]]
                        if peer.vector.get("team")
                        else None
                    )
                    suffix = route.path.removeprefix(base).strip("/")
                    singular, plural = (
                        ("plan", "plans") if is_plan else ("workflow", "workflows")
                    )
                    if "/runs/" in suffix or suffix.endswith("/run"):
                        self.workflow_run(suffix, query)
                        return
                    if self.command == "GET":
                        value = (
                            {singular: peer.rows[suffix]}
                            if suffix
                            else {plural: list(peer.rows.values())}
                        )
                        self.response(200, value)
                        return
                    if self.command == "DELETE":
                        assert suffix in peer.rows
                        if is_plan:
                            assert query["version"] == [
                                str(peer.rows[suffix]["version"])
                            ]
                        del peer.rows[suffix]
                        peer.writes += 1
                        peer.checks.add("confirmed-versioned-delete")
                        self.response(200, {"deleted": True})
                        return
                    payload, raw = self.body()
                    if self.command == "POST":
                        assert not suffix
                        if is_plan:
                            peer.plan_create(payload, raw)
                            object_id = payload["plan_id"]
                        else:
                            peer.workflow_create(payload)
                            object_id = peer.suite["workflow_id"]
                            payload["id"] = object_id
                        payload.setdefault("version", 1)
                        peer.rows[object_id] = payload
                    elif self.command == "PATCH":
                        current = peer.rows[suffix]
                        if is_plan:
                            assert payload["version"] == current["version"]
                            assert payload["planner_focus_id"] is None
                            assert (
                                decrypt(
                                    payload["encrypted_goal"], peer.keys[suffix]
                                ).decode()
                                == "Synthetic revised private goal"
                            )
                            assert "Synthetic revised private goal" not in raw
                            assert payload["status"] == "active"
                        else:
                            assert payload["title"] == "Synthetic revised Workflow"
                            assert payload["enabled"] is False
                        current.update(payload)
                        current["version"] += 1
                        object_id = suffix
                        peer.checks.add("typed-versioned-update")
                    else:
                        raise AssertionError("unexpected CRUD method")
                    peer.writes += 1
                    self.response(200, {singular: peer.rows[object_id]})
                except Exception:
                    peer.failure = peer.failure or "plans-workflows-protocol-assertion"
                    self.response(
                        500, {"detail": "synthetic-private-server-diagnostic"}, False
                    )

            def workflow_run(self, suffix, query):
                assert not query and not peer.vector.get("team")
                flow = peer.suite["workflow_id"]
                run = peer.suite["run_id"]
                if suffix == f"{flow}/run":
                    assert self.command == "POST"
                    peer.run_posts += 1
                    assert peer.run_posts == 1, "wait must never re-dispatch"
                    payload, _raw = self.body()
                    assert (
                        self.headers.get("Idempotency-Key")
                        == peer.suite["input"]["run"]["idempotency_key"]
                    )
                    expected = dict(peer.suite["input"]["run"])
                    del expected["idempotency_key"]
                    assert payload == expected, (
                        "automatic routing and opaque user input preserved"
                    )
                    peer.checks.update(
                        (
                            "stable-run-idempotency",
                            "no-invented-routing",
                            "opaque-variable-names-preserved",
                        )
                    )
                    if peer.vector["mode"] == "http_error":
                        self.response(
                            403, {"detail": "synthetic-private-server-diagnostic"}
                        )
                    else:
                        self.response(200, {"run": peer.run("queued")})
                elif suffix == f"{flow}/runs/{run}/cancel":
                    assert self.command == "POST" and self.body()[0] == {}
                    peer.cancel_posts += 1
                    assert peer.cancel_posts == 1
                    self.response(200, {"status": "cancellation_requested"})
                else:
                    assert suffix == f"{flow}/runs/{run}" and self.command == "GET"
                    peer.polls += 1
                    mode = peer.vector["mode"]
                    state = "failed" if mode == "failed" else "running"
                    if mode == "run" and peer.polls >= 2:
                        state = "completed"
                    if peer.cancel_posts:
                        state = "cancelled"
                    value = peer.run(state)
                    if mode == "bad_identity":
                        value["id"] = "99999999-9999-4999-8999-999999999999"
                    peer.checks.add("canonical-run-reread")
                    self.response(200, {"run": value})

            do_GET = request
            do_POST = request
            do_PATCH = request
            do_DELETE = request

        return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--vector", required=True)
    parser.add_argument("--identity", required=True)
    args = parser.parse_args()
    suite = json.loads(Path(args.fixture).read_bytes())["capabilities"][CAPABILITY]
    vector = next(v for v in suite["vectors"] if v["id"] == args.vector)
    peer = PlansWorkflowsPeer(suite, vector, args.identity).start()
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    try:
        threading.Event().wait()
    finally:
        peer.close()


if __name__ == "__main__":
    main()
