#!/usr/bin/env python3
"""Synthetic public SSE peer. Test-only, ephemeral IPv4 loopback, no AI."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import uuid

CAPABILITY = "session.anonymous-stream.v1"


class AnonymousPeer:
    def __init__(self, suite, vector, identity):
        assert identity in ("rust", "npm", "pip")
        self.suite, self.vector, self.identity = suite, vector, identity
        self.failure, self.status_gets, self.posts, self.redirects = None, 0, 0, 0
        self.chat_ids, self.user_ids = set(), set()
        self.checks = set()
        self.release = threading.Event()
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
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def status(self):
        return {
            "failure": self.failure,
            "status_gets": self.status_gets,
            "posts": self.posts,
            "redirects": self.redirects,
            "chat_ids": sorted(self.chat_ids),
            "checks": sorted(self.checks),
        }

    def handler(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def response(self, status, value, location=None):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header(
                    "Set-Cookie",
                    "auth_refresh_token=untrusted-anonymous-cookie; Path=/; HttpOnly",
                )
                if location:
                    self.send_header("Location", location)
                self.end_headers()
                self.wfile.write(raw)

            def headers_safe(self):
                for field in (
                    "Cookie",
                    "Authorization",
                    "Origin",
                    "Referer",
                    "X-Device-ID",
                    "X-OpenMates-Device-ID",
                ):
                    assert self.headers.get(field) is None
                assert (
                    self.headers.get("X-OpenMates-Anonymous-ID")
                    == peer.suite["anonymous_id"]
                )
                assert self.headers.get("X-OpenMates-SDK") == peer.identity
                for secret in (
                    peer.suite["account"]["cookie"],
                    peer.suite["account"]["master_key"],
                    peer.suite["account"]["session_id"],
                ):
                    assert secret not in str(self.headers)
                peer.checks.add("public-headers-without-account-identity")

            def do_GET(self):
                if self.path == "/__test/status":
                    self.response(200, peer.status())
                    return
                if self.path == "/__test/release":
                    peer.release.set()
                    self.response(200, {})
                    return
                try:
                    self.headers_safe()
                    if self.path == "/__test/redirect-target":
                        peer.redirects += 1
                        raise AssertionError("anonymous redirects must not be followed")
                    assert self.path == "/v1/anonymous/free-usage/status"
                    peer.status_gets += 1
                    assert self.headers.get("Accept") == "application/json"
                    mode = peer.vector["mode"]
                    if mode == "budget":
                        self.response(
                            429, {"detail": "synthetic-private-server-diagnostic"}
                        )
                    elif mode == "redirect":
                        self.response(
                            302, {}, peer.endpoint + "/__test/redirect-target"
                        )
                    else:
                        self.response(200, {"active": True, "can_send_text": True})
                except Exception:
                    peer.failure = peer.failure or "anonymous-status-protocol"
                    self.response(500, {})

            def do_POST(self):
                try:
                    self.headers_safe()
                    assert self.path == "/v1/anonymous/chat/stream"
                    assert self.headers.get("Accept") == "text/event-stream"
                    length = int(self.headers["Content-Length"])
                    assert 0 < length < 65536
                    raw = self.rfile.read(length).decode()
                    payload = json.loads(raw)
                    assert set(payload) == {
                        "anonymous_id",
                        "client_chat_id",
                        "client_message_id",
                        "plaintext_message",
                        "message_history",
                    }
                    assert (
                        payload["anonymous_id"] == peer.suite["anonymous_id"]
                        and payload["message_history"] == []
                    )
                    assert peer.suite["pii"] not in raw
                    assert payload["plaintext_message"] != peer.suite["text"]
                    assert all(
                        secret not in raw
                        for secret in (
                            peer.suite["account"]["cookie"],
                            peer.suite["account"]["master_key"],
                        )
                    )
                    chat, user = payload["client_chat_id"], payload["client_message_id"]
                    assert chat.startswith("anonymous-") and user.startswith(
                        "anonymous-message-"
                    )
                    assert uuid.UUID(chat.removeprefix("anonymous-")).version == 4
                    assert (
                        uuid.UUID(user.removeprefix("anonymous-message-")).version == 4
                    )
                    assert chat not in peer.chat_ids and user not in peer.user_ids
                    peer.chat_ids.add(chat)
                    peer.user_ids.add(user)
                    peer.posts += 1
                    peer.checks.update(
                        (
                            "local-pii-redaction",
                            "empty-history-fresh-ephemeral-identities",
                            "no-routing-or-durable-capabilities",
                        )
                    )
                    mode = peer.vector["mode"]
                    task, assistant = (
                        f"synthetic-task-{peer.posts}",
                        f"synthetic-answer-{peer.posts}",
                    )
                    bind = {
                        "chat_id": chat,
                        "user_message_id": user,
                        "task_id": task,
                        "message_id": assistant,
                    }
                    events = [
                        {
                            "type": "ai_task_initiated",
                            "chat_id": chat,
                            "user_message_id": user,
                            "ai_task_id": task,
                        },
                        {
                            "type": "ai_typing_started",
                            **bind,
                            "model_name": "fixture-automatic",
                            "category": "synthetic",
                        },
                    ]
                    if mode == "private":
                        events.append(
                            {
                                "type": "request_app_settings_memories",
                                "chat_id": chat,
                                "task_id": task,
                                "request_id": "forbidden-private-context",
                                "items": ["private"],
                            }
                        )
                    else:
                        events.append(
                            {
                                "type": "ai_message_chunk",
                                **bind,
                                "sequence": 1,
                                "full_content_so_far": payload["plaintext_message"],
                                "is_final_chunk": not (
                                    mode == "cancel" and peer.posts == 1
                                ),
                            }
                        )
                        if mode == "malformed":
                            events.append(
                                {
                                    "type": "ai_message_chunk",
                                    **bind,
                                    "sequence": 1,
                                    "full_content_so_far": "duplicate",
                                    "is_final_chunk": True,
                                }
                            )
                        events.extend(
                            [
                                {
                                    "type": "ai_task_ended",
                                    "chatId": chat,
                                    "taskId": task,
                                    "status": "completed",
                                },
                                {
                                    "type": "post_processing_completed",
                                    "chat_id": chat,
                                    "task_id": task,
                                    "follow_up_request_suggestions": [
                                        "Synthetic follow-up"
                                    ],
                                },
                            ]
                        )
                    hold = mode == "cancel" and peer.posts == 1
                    if hold:
                        events = events[:3]
                    data = "".join(
                        "data: " + json.dumps(event) + "\r\n\r\n" for event in events
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header(
                        "Set-Cookie",
                        "auth_refresh_token=untrusted-anonymous-cookie; Path=/; HttpOnly",
                    )
                    if not hold:
                        self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    # Split a CRLF/SSE record across writes to exercise actual streaming.
                    self.wfile.write(data[:7])
                    self.wfile.flush()
                    self.wfile.write(data[7:])
                    self.wfile.flush()
                    if hold:
                        assert peer.release.wait(timeout=10), "fixture cancel release"
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception:
                    peer.failure = peer.failure or "anonymous-send-protocol"
                    self.response(500, {})

        return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--vector", required=True)
    parser.add_argument("--identity", required=True)
    args = parser.parse_args()
    suite = json.loads(Path(args.fixture).read_bytes())["capabilities"][CAPABILITY]
    vector = next(v for v in suite["vectors"] if v["id"] == args.vector)
    peer = AnonymousPeer(suite, vector, args.identity).start()
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    try:
        threading.Event().wait()
    finally:
        peer.close()


if __name__ == "__main__":
    main()
