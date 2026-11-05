"""Independent synthetic HTTP wire oracle; product/native runs only in isolated CI."""

from __future__ import annotations
import argparse
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading


class DirectSkillPeer:
    def __init__(self, suite, vector, identity):
        self.suite, self.vector, self.identity = suite, vector, identity
        self.lock, self.release = threading.Lock(), threading.Event()
        self.failure = None
        self.counts = {
            "auth": 0,
            "skill_posts": 0,
            "retention_posts": 0,
            "downloads": 0,
        }
        self.polls, self.poll_order = {}, []
        self.bodies = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}"

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def status(self):
        with self.lock:
            return {
                **self.counts,
                "polls": dict(self.polls),
                "poll_order": list(self.poll_order),
                "bodies": deepcopy(self.bodies),
                "failure": self.failure,
            }

    def headers(self, handler):
        assert handler.headers.get("X-OpenMates-SDK") == self.identity, "SDK identity"
        assert handler.headers.get("Origin") == self.endpoint, (
            "explicit loopback origin"
        )
        a = self.suite["account"]
        if self.vector["credential"] == "cookie":
            assert (
                handler.headers.get("Cookie") == f"auth_refresh_token={a['cookie']}"
            ), "explicit cookie"
            assert handler.headers.get("Authorization") is None, "no bearer escalation"
        else:
            assert (
                handler.headers.get("Authorization")
                == "Bearer " + a["api_key"].split(".", 1)[0]
            ), "explicit bearer"
            assert handler.headers.get("Cookie") is None, "no cookie discovery"
            assert (
                handler.headers.get("X-OpenMates-Device-Identity") == a["device_id"]
            ), "explicit device"

    def validate_input(self, value):
        expected = deepcopy(self.suite["request"]["input"])
        if (
            self.vector["mode"] == "queued_successor"
            and self.counts["skill_posts"] == 1
        ):
            expected["query"] = "synthetic explicit successor B"
        assert value == expected, (
            "exact explicit input; no prompt/model/provider/private-memory additions"
        )

    def handler(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_):
                pass

            def response(self, status, value):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def dispatch(self, method):
                if self.path == "/__test/status":
                    assert method == "GET"
                    self.response(200, peer.status())
                    return
                if self.path == "/__test/release":
                    assert method == "GET"
                    peer.release.set()
                    self.response(200, {"released": True})
                    return
                peer.headers(self)
                body = None
                if method == "POST":
                    n = int(self.headers.get("Content-Length", "0"))
                    assert 0 < n <= 1024 * 1024, "bounded request"
                    body = json.loads(self.rfile.read(n))
                mode = peer.vector["mode"]
                if self.path == "/v1/auth/session":
                    assert method == "POST" and peer.vector["credential"] == "cookie"
                    assert body == {"session_id": peer.suite["account"]["session_id"]}
                    with peer.lock:
                        peer.counts["auth"] += 1
                        count = peer.counts["auth"]
                    if mode == "auth_denial":
                        self.response(
                            403, {"error": "synthetic-private-server-diagnostic"}
                        )
                        return
                    owner = peer.suite["account"]["owner_id"]
                    if mode == "owner_rotation" and count >= 2:
                        owner = "99999999-9999-4999-8999-999999999999"
                    self.response(
                        200,
                        {
                            "success": True,
                            "ws_token": "synthetic-direct-token",
                            "user": {"id": owner},
                        },
                    )
                    return
                if self.path == "/v1/apps/web/skills/search/details":
                    assert method == "GET" and peer.vector["credential"] == "cookie"
                    assert peer.counts["auth"] >= 1, "genuine initial owner observation"
                    self.response(
                        200,
                        {
                            "app_id": "web",
                            "skill_id": "search",
                            "execution_available": True,
                            "input_schema": {
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                                "required": ["query"],
                                "additionalProperties": False,
                            },
                        },
                    )
                    return
                if self.path == "/v1/apps/web/skills/search":
                    assert method == "POST"
                    with peer.lock:
                        peer.validate_input(body)
                        if peer.vector["credential"] == "cookie":
                            # The core reuses the command's own fresh session
                            # validation for HTTP app-skill requests (dafff9b7dc);
                            # the server still authorizes every request.
                            assert peer.counts["auth"] >= 1, (
                                "authenticated owner observation before billable POST"
                            )
                        peer.counts["skill_posts"] += 1
                        assert (
                            peer.counts["skill_posts"]
                            <= peer.vector["expected_skill_posts"]
                        ), "no paid replay"
                        peer.bodies.append(body)
                    if mode == "cancel_after_dispatch":
                        assert peer.release.wait(15), (
                            "cancel after actual dispatch release"
                        )
                    envelope = {
                        "success": True,
                        "credits_charged": 1,
                        "data": {"task_id": "task_one"},
                    }
                    if mode in {"sync", "file_no_download"}:
                        envelope = peer.vector["expected"]
                    elif mode in {"task_array_order", "pending_a_failed_b"}:
                        envelope = {
                            "success": True,
                            "credits_charged": 2,
                            "data": {"task_ids": ["task_a", "task_b"]},
                        }
                    elif mode.startswith("queued_"):
                        envelope = peer.suite["sync_expected"]
                    self.response(200, envelope)
                    return
                if self.path.startswith("/v1/tasks/"):
                    assert method == "GET"
                    task = self.path.removeprefix("/v1/tasks/")
                    assert task in {"task_one", "task_a", "task_b"}, (
                        "exact original task selector"
                    )
                    with peer.lock:
                        peer.polls[task] = peer.polls.get(task, 0) + 1
                        peer.poll_order.append(task)
                        count = peer.polls[task]
                    if (
                        mode == "failed_task"
                        or mode == "pending_a_failed_b"
                        and task == "task_b"
                    ):
                        self.response(
                            200,
                            {
                                "task_id": task,
                                "status": "failed",
                                "error": "synthetic-private-server-diagnostic",
                            },
                        )
                        return
                    if (
                        mode == "pending_a_failed_b"
                        or mode == "task_array_order"
                        and task == "task_a"
                        and count == 1
                    ):
                        self.response(200, {"task_id": task, "status": "pending"})
                        return
                    value = (
                        {"label": "single", "ordered": [3, 1, 2]}
                        if task == "task_one"
                        else {
                            "label": task[-1].upper(),
                            "ordered": [3, 1, 2] if task == "task_a" else [2, 3, 1],
                        }
                    )
                    self.response(
                        200, {"task_id": task, "status": "completed", "result": value}
                    )
                    return
                if self.path.startswith(
                    ("/v1/embeds/", "/v1/apps/workspace/", "/v1/chats")
                ):
                    with peer.lock:
                        peer.counts[
                            "downloads"
                            if method == "GET" and "/file" in self.path
                            else "retention_posts"
                        ] += 1
                    raise AssertionError(
                        "temporary result must not download or save canonical Apps/chat content"
                    )
                raise AssertionError(
                    "unapproved endpoint; no new credential/profile/protocol discovery"
                )

            def do_POST(self):
                self.safe("POST")

            def do_GET(self):
                self.safe("GET")

            def safe(self, method):
                try:
                    self.dispatch(method)
                except Exception as error:
                    with peer.lock:
                        peer.failure = type(error).__name__ + ":" + str(error)
                    self.response(500, {"error": "synthetic-private-server-diagnostic"})

        return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--vector", required=True)
    parser.add_argument("--identity", choices=["rust", "npm", "pip"], required=True)
    args = parser.parse_args()
    suite = json.loads(Path(args.fixture).read_text())["capabilities"]["sdk.apps"]
    vector = next(v for v in suite["vectors"] if v["id"] == args.vector)
    peer = DirectSkillPeer(suite, vector, args.identity).start()
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    try:
        threading.Event().wait()
    finally:
        peer.stop()


if __name__ == "__main__":
    main()
