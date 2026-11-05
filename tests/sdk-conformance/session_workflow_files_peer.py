"""Independent encrypted Project workflow-file protocol peer; explicit start only.

No product fallback. Real requests, envelopes, mutations and metadata are checked;
adapter output cannot manufacture the peer's counters or committed plaintext.
"""

from __future__ import annotations
import base64
from copy import deepcopy
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import uuid
from urllib.parse import parse_qs, urlsplit
from recovery_server import decrypt, encrypt
from remote_crypto_peer import IndependentPeer

CAPABILITY = "work.project-workflow-file-sync.v1"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def replacement(path, old, new):
    def rows(value, prefix):
        result = []
        for line in value.splitlines(keepends=True):
            if line.endswith("\n"):
                result.append(prefix + line[:-1])
            else:
                result.extend([prefix + line, "\\ No newline at end of file"])
        return result

    return "\n".join(
        [
            f"--- a/{path}",
            f"+++ b/{path}",
            f"@@ -{1 if old else 0},{len(old.splitlines(keepends=True))} +{1 if new else 0},{len(new.splitlines(keepends=True))} @@",
            *rows(old, "-"),
            *rows(new, "+"),
            "",
        ]
    )


class WorkflowFilesPeer:
    def __init__(self, suite, vector, identity):
        self.s, self.v, self.identity = suite, vector, identity
        self.key = base64.b64decode(suite["project_key_b64"], validate=True)
        self.master = base64.b64decode(suite["account"]["master_key"], validate=True)
        self.cookie = suite["account"]["cookie"]
        self.failure = None
        self.requests = []
        self.approvals = []
        self.mutations = []
        self.saved = None
        self.result_reads = 0
        self.result_returned = False
        self.metadata_committed = False
        self.blocked = threading.Event()
        self.release = threading.Event()
        self.server = self.thread = None
        self.results = {}

    def start(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.release.set()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=3)
            assert not self.thread.is_alive(), "original peer did not terminate"

    def status(self):
        return {
            "failure": self.failure,
            "blocked": self.blocked.is_set(),
            "requests": len(self.requests),
            "mutations": len(self.mutations),
            "metadata_attempts": int(self.saved is not None),
            "metadata_committed": self.metadata_committed,
        }

    def workflow(self):
        version = (
            "version-3"
            if self.v.get("mode") == "version-race" and self.result_returned
            else self.s["expected_version"]
        )
        return {
            "id": self.s["workflow_id"],
            "title": "Updated",
            "description": None,
            "current_version_id": version,
            "source_chat_id": self.s["chat_id"],
            "run_content_retention": "last_5",
            "graph": {"version": 1, "trigger_node_id": None, "nodes": [], "edges": []},
        }

    def item(self):
        binding = {
            "project_id": self.s["project_id"],
            "source_id": self.s["source_id"],
            "folder_path": "workflows",
        }
        if self.v.get("mode") == "update":
            binding.update(
                base_hash=digest(self.s["old_yaml"]),
                saved_content=self.s["old_yaml"],
                file_path=self.s["path"],
            )
        owner = (
            "foreign"
            if self.v.get("mode") == "foreign-item-scope"
            else self.s["owner_id"]
        )
        return {
            "project_item_id": self.s["item_id"],
            "item_type": "workflow",
            "hashed_project_id": digest(self.s["project_id"]),
            "hashed_user_id": digest(owner),
            "hashed_team_id": None,
            "target_id_hash": digest(self.s["workflow_id"]),
            "target_id_encrypted": encrypt(self.s["workflow_id"].encode(), self.key),
            "encrypted_metadata": encrypt(
                json.dumps(
                    {
                        "legacy": {"private": "preserve extra"},
                        "remote_workflow_file": binding,
                    }
                ).encode(),
                self.key,
            ),
        }

    def relay(self, body):
        s = self.s
        assert set(body) == {
            "request_id",
            "requesting_client_id",
            "operation",
            "key_epoch",
            "encrypted_envelope",
            "chat_id",
            "operation_id",
            "proposal_digest",
        }
        for key in ("request_id", "requesting_client_id", "operation_id"):
            assert str(uuid.UUID(body[key])) == body[key]
        assert body["key_epoch"] == 1 and body["chat_id"] == s["chat_id"]
        plain = json.loads(decrypt(body["encrypted_envelope"], self.key))
        assert set(plain) == {
            "requesting_client_id",
            "requester_handshake",
            "operation",
            "arguments",
        }
        assert plain["requesting_client_id"] == body["requesting_client_id"]
        assert (
            set(plain["arguments"]) == {"chat_id", "mutation"}
            and plain["arguments"]["chat_id"] == s["chat_id"]
        )
        mutation = plain["arguments"]["mutation"]
        assert (
            mutation["operation"] == plain["operation"] == body["operation"]
            and mutation["operation_id"] == body["operation_id"]
        )
        assert mutation["path"] == s["path"]
        if self.v.get("mode") == "update":
            assert mutation["operation"] == "update_file" and mutation[
                "expected_base"
            ] == digest(s["old_yaml"])
            assert set(mutation) == {
                "operation",
                "operation_id",
                "path",
                "expected_base",
                "patch",
            }
            assert mutation["patch"] == replacement(
                s["path"], s["old_yaml"], s["expected_yaml"]
            )
        else:
            assert (
                mutation["operation"] == "create_file"
                and mutation["expected_base"] is None
            )
            assert set(mutation) == {
                "operation",
                "operation_id",
                "path",
                "expected_base",
                "content",
            }
            assert mutation["content"] == s["expected_yaml"]
        tuple_ = [
            "openmates-project-file-proposal-v1",
            s["project_id"],
            s["chat_id"],
            mutation["operation"],
            mutation["operation_id"],
            mutation["path"],
            mutation["expected_base"],
            mutation.get("content"),
            mutation.get("patch"),
        ]
        expected = hmac.digest(
            self.key,
            json.dumps(tuple_, ensure_ascii=False, separators=(",", ":")).encode(),
            "sha256",
        ).hex()
        assert body["proposal_digest"] == expected
        if self.v.get("mode") != "apply-and-show":
            assert self.approvals == [
                {
                    "chat_id": s["chat_id"],
                    "operation_id": mutation["operation_id"],
                    "proposal_digest": expected,
                }
            ]
        identity = {
            "ownerId": s["owner_id"],
            "projectId": s["project_id"],
            "sourceId": s["source_id"],
            "sourceSessionId": s["source_session_id"],
            "requestingClientId": body["requesting_client_id"],
            "keyEpoch": 1,
        }
        source = IndependentPeer(self.key, identity, "source")
        source.accept(plain["requester_handshake"])
        mode = self.v.get("mode")
        result = {"status": mode if mode in {"queued", "conflict"} else "completed"}
        if mode in {"tuple-ack", "bad-after-hash"}:
            result = {
                "status": "applied",
                "path": s["path"],
                "operation": mutation["operation"],
                "operation_id": mutation["operation_id"],
                "after_hash": digest(s["expected_yaml"])
                if mode == "tuple-ack"
                else "0" * 64,
            }
        envelope = source.seal(
            body["request_id"],
            json.dumps({"ok": True, "result": result}, separators=(",", ":")).encode(),
        )
        self.results[body["request_id"]] = (
            body["requesting_client_id"],
            json.dumps({"source_handshake": source.handshake, "envelope": envelope}),
        )
        self.mutations.append(deepcopy(mutation))
        return {"source_session_id": s["source_session_id"], "key_epoch": 1}

    def dispatch(self, method, route, headers, body):
        s, mode = self.s, self.v.get("mode")
        assert headers.get("Cookie") == "auth_refresh_token=" + self.cookie
        assert (
            headers.get("X-OpenMates-SDK") == self.identity
            and headers.get("Origin") == s["app_origin"]
        )
        assert not headers.get("Authorization")
        self.requests.append((method, route.path))
        assert len(self.requests) <= 24
        project = f"/v1/projects/{s['project_id']}"
        if method == "GET" and route.path == f"/v1/workflows/{s['workflow_id']}":
            return 200, {"workflow": self.workflow()}, None
        if method == "GET" and route.path == "/v1/projects":
            return (
                200,
                {
                    "projects": [
                        {
                            "project_id": s["project_id"],
                            "hashed_user_id": digest(s["owner_id"]),
                            "hashed_team_id": None,
                            "encrypted_project_key": encrypt(self.key, self.master),
                            "encrypted_name": encrypt(b"Fixture", self.key),
                        }
                    ]
                },
                None,
            )
        if method == "GET" and route.path == project + "/items":
            return 200, {"folders": [], "items": [self.item()]}, None
        if method == "GET" and route.path == project + "/sources":
            return (
                200,
                {
                    "sources": []
                    if mode == "source-missing"
                    else [
                        {
                            "source_id": s["source_id"],
                            "status": "disconnected"
                            if mode == "source-offline"
                            else "connected",
                            "source_session_id": s["source_session_id"],
                            "key_epoch": 1,
                        }
                    ]
                },
                None,
            )
        if method == "GET" and route.path == "/v1/projects/focus/current":
            assert parse_qs(route.query) == {"chat_id": [s["chat_id"]]}
            return (
                200,
                {
                    "focus": {
                        "project_id": s["team_id"]
                        if mode == "focus-mismatch"
                        else s["project_id"]
                    }
                },
                None,
            )
        if method == "GET" and route.path == project + "/settings":
            return (
                200,
                {
                    "settings": {
                        "write_mode": "apply_and_show"
                        if mode == "apply-and-show"
                        else "always_ask"
                    }
                },
                None,
            )
        if method == "POST" and route.path == project + "/write-approvals":
            assert set(body) == {"chat_id", "operation_id", "proposal_digest"}
            self.approvals.append(body)
            return 200, {"success": True}, None
        if method == "POST" and route.path == "/v1/auth/session":
            assert body == {"session_id": s["account"]["session_id"]}
            return (
                200,
                {
                    "success": True,
                    "ws_token": "synthetic-workflow-token",
                    "user": {"id": s["owner_id"]},
                },
                None,
            )
        base = project + f"/sources/{s['source_id']}/requests"
        if method == "POST" and route.path == base:
            return 200, self.relay(body), None
        if method == "GET" and route.path.startswith(base + "/"):
            self.result_reads += 1
            if mode in {"pending-404", "unknown-404"} and self.result_reads == 1:
                self.cookie = "synthetic-cookie-b"
                return (
                    404,
                    {
                        "detail": "request_not_found"
                        if mode == "pending-404"
                        else "Source not found"
                    },
                    "auth_refresh_token=" + self.cookie,
                )
            if mode == "cancel-held":
                self.blocked.set()
                assert self.release.wait(timeout=8), "held result was not released"
            client, envelope = self.results[route.path.rsplit("/", 1)[1]]
            assert parse_qs(route.query) == {"requesting_client_id": [client]}
            self.result_returned = True
            return 200, {"status": "completed", "encrypted_envelope": envelope}, None
        if method == "PATCH" and route.path == project + f"/items/{s['item_id']}":
            assert (
                set(body) == {"encrypted_metadata", "updated_at"}
                and type(body["updated_at"]) is int
            )
            self.saved = json.loads(decrypt(body["encrypted_metadata"], self.key))
            assert self.saved["legacy"] == {"private": "preserve extra"}
            if mode == "metadata-denied":
                return 500, {"detail": "private metadata denial"}, None
            self.metadata_committed = True
            return 200, {"item": {}}, None
        raise AssertionError("unexpected method/route; no mutation fallback")

    def check(self, observed):
        assert self.failure is None
        v, s = self.v, self.s
        if v.get("sdk_error"):
            assert observed == {"ok": False, "error": v["sdk_error"]}
            if v.get("early"):
                assert not self.requests
            if v.get("mode") in {"cancel-held", "foreign-item-scope", "wrong-master"}:
                assert self.saved is None
            return
        assert observed == {
            "ok": True,
            "value": [
                {
                    "project_id": s["project_id"],
                    "status": v["status"],
                    **({"error": v["error"]} if "error" in v else {}),
                }
            ],
        }
        assert (
            self.metadata_committed and self.saved["remote_file_status"] == v["status"]
        )
        binding = self.saved["remote_workflow_file"]
        if v["status"] == "saved" or v.get("mode") == "version-race":
            assert binding["saved_content"] == s["expected_yaml"] and binding[
                "base_hash"
            ] == digest(s["expected_yaml"])
            assert binding["workflow_version_id"] == s["expected_version"]
        elif v.get("mode") != "update":
            assert "base_hash" not in binding
        if v.get("mode") == "unknown-404":
            assert self.result_reads == 1
        if v.get("mode") == "pending-404":
            assert self.result_reads == 2
        if v["id"] in {
            "approval-pending",
            "unapproved-exact-path",
            "source-offline",
            "source-missing",
            "focus-mismatch",
        }:
            assert not self.mutations

    def handler(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def handle_request(self):
                route = urlsplit(self.path)
                length = int(self.headers.get("Content-Length", "0"))
                assert 0 <= length <= 1024 * 1024
                body = json.loads(self.rfile.read(length)) if length else None
                try:
                    if route.path == "/__test/status":
                        status, value, cookie = 200, peer.status(), None
                    elif route.path == "/__test/release" and self.command == "POST":
                        peer.release.set()
                        status, value, cookie = 200, peer.status(), None
                    else:
                        status, value, cookie = peer.dispatch(
                            self.command, route, self.headers, body
                        )
                except Exception:
                    peer.failure = "workflow_file_peer_protocol"
                    status, value, cookie = (
                        500,
                        {"detail": "synthetic peer refusal"},
                        None,
                    )
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                if cookie:
                    self.send_header("Set-Cookie", cookie)
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = do_PATCH = handle_request

        return Handler
