#!/usr/bin/env python3
"""Synthetic one-page session HTTP peer for direct SDK conformance.

Construction and response planning perform no socket or product operations.
Only explicit start() binds an ephemeral IPv4 loopback socket for isolated CI.
All credentials and AES keys are public fixture data, never real account state.
Status exposes closed request counts/checks and SDK identity, never credentials.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CAPABILITY = "session.message-window.v1"


def encrypt(plain, key, label):
    """Deterministic unique fixture-label nonce; never a production key helper."""
    fingerprint = 2166136261
    for byte in key:
        fingerprint = ((fingerprint ^ byte) * 16777619) & 0xFFFFFFFF
    nonce = hashlib.sha256(label.encode() + key + plain).digest()[:12]
    return base64.b64encode(
        b"OM"
        + fingerprint.to_bytes(4, "big")
        + nonce
        + AESGCM(key).encrypt(nonce, plain, None)
    ).decode()


class MessageWindowPeer:
    def __init__(self, suite, vector, identity):
        if identity not in ("rust", "npm", "pip"):
            raise ValueError("Unsupported fixture SDK identity")
        self.suite, self.vector, self.identity = suite, vector, identity
        self.account, self.protocol = suite["account"], suite["protocol"]
        overrides = vector.get("message_id_overrides")
        if overrides is not None:
            assert type(overrides) is dict and set(overrides) == set(
                self.protocol["message_ids"]
            )
            assert all(
                type(value) is str
                and 1 <= len(value) <= 256
                and all(33 <= ord(char) <= 126 for char in value)
                for value in overrides.values()
            )
            self.protocol = copy.deepcopy(self.protocol)
            for row in self.protocol["messages"]:
                logical = overrides[row.get("client_message_id") or row["id"]]
                row["client_message_id"] = logical
                row["message_id"] = logical
            self.protocol["message_ids"] = [
                overrides[value] for value in self.protocol["message_ids"]
            ]
        self.chat_id = self.protocol["chat_id"]
        self.mode = vector["mode"]
        self.counts = {"metadata": 0, "window": 0}
        self.checks, self.failure = set(), None
        self.server, self.thread = None, None
        self.cancel_release = threading.Event()

    @property
    def endpoint(self):
        if self.server is None:
            raise RuntimeError("Synthetic peer has not been explicitly started")
        return f"http://127.0.0.1:{self.server.server_port}"

    def start(self):
        if self.server is not None:
            raise RuntimeError("Synthetic peer already started")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def close(self):
        self.cancel_release.set()
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=3)
            self.server = self.thread = None

    def status(self):
        return {
            "failure": self.failure,
            "checks": sorted(self.checks),
            "metadata": self.counts["metadata"],
            "window": self.counts["window"],
            "identity": self.identity,
            "queryMatched": "exact-window-query" in self.checks,
        }

    def verify_headers(self, headers):
        assert headers.get("X-OpenMates-SDK") == self.identity, "SDK identity"
        assert headers.get("Origin") == self.protocol["app_origin"], "explicit origin"
        assert (
            headers.get("Cookie") == f"auth_refresh_token={self.account['cookie']}"
        ), "session cookie"
        assert headers.get("Authorization") is None, "no bearer escalation"

    def expected_query(self, ordinal=None):
        ordinal = self.counts["window"] if ordinal is None else ordinal
        if self.mode == "partial_cache" and ordinal == 1:
            return {
                "direction": ["latest"],
                "limit": ["100"],
                "respect_compression_boundary": ["false"],
            }
        options = (
            self.vector.get("preflight")
            if ordinal == 1 and self.vector.get("preflight")
            else self.vector["options"]
        )
        direction = options["direction"]
        query = {
            "direction": [direction],
            "limit": [str(options["limit"])],
            "respect_compression_boundary": [
                str(options.get("respectCompressionBoundary", True)).lower()
            ],
        }
        if direction in ("before", "after"):
            cursor = options["cursor"]
            query[f"{direction}_timestamp"] = [str(cursor["createdAt"])]
            query[f"{direction}_message_id"] = [cursor["messageId"]]
        if direction == "around":
            query["anchor_message_id"] = [options["anchorMessageId"]]
        return query

    def metadata(self):
        row = copy.deepcopy(self.protocol["metadata"])
        if self.mode == "wrong_key":
            master = base64.b64decode(self.account["master_key"])
            row["encrypted_chat_key"] = encrypt(
                bytes([91]) * 32, master, "wrong-chat-key"
            )
        return {"chats": [row]}

    def window(self):
        preflight = self.counts["window"] == 1 and self.vector.get("preflight")
        direction = "latest" if preflight else self.vector["options"]["direction"]
        indices = (
            [0, 1]
            if direction == "before"
            else [1, 2]
            if direction == "around"
            else [3]
            if direction == "after"
            else [2, 3]
        )
        if self.mode == "partial_cache" and self.counts["window"] == 1:
            indices = [0, 1, 2, 3]
        rows = [copy.deepcopy(self.protocol["messages"][i]) for i in indices]
        if self.mode == "around_alias":
            rows[-1]["id"] = self.vector["options"]["anchorMessageId"]
        if self.mode in (
            "around_missing",
            "around_oversized",
            "around_wrong_oversized_anchor",
        ):
            rows = []
        key = base64.b64decode(self.protocol["chat_key"])
        if self.mode in ("page_local_maps", "page_local_unknown"):
            token = self.protocol[
                "known_placeholder"
                if self.mode == "page_local_maps"
                else "unknown_placeholder"
            ]
            rows[0]["encrypted_content"] = encrypt(
                f"Hello {token}".encode(), key, "page-token"
            )
            rows[0]["encrypted_thinking_content"] = encrypt(
                f"Think {token}".encode(), key, "thinking-token"
            )
            mapping = [
                {
                    "placeholder": self.protocol["known_placeholder"],
                    "original": self.protocol["known_original"],
                }
            ]
            # Production pages aggregate USER-message maps. The unknown token
            # intentionally has no mapping on any user row of this page.
            rows[0]["encrypted_pii_mappings"] = encrypt(
                json.dumps(mapping).encode(), key, "page-mapping"
            )
        if self.mode == "wrong_chat":
            rows[0]["chat_id"] = "99999999-9999-4999-8999-999999999999"
        if self.mode == "tamper":
            encrypted = bytearray(base64.b64decode(rows[0]["encrypted_content"]))
            encrypted[-1] ^= 1
            rows[0]["encrypted_content"] = base64.b64encode(encrypted).decode()
        if self.mode == "over_rows":
            rows = [copy.deepcopy(rows[0]) for _ in range(21)]
            for index, row in enumerate(rows):
                row["id"] = row["client_message_id"] = (
                    f"20000000-0000-4000-8000-{index:012d}"
                )
        if self.mode == "over_bytes":
            rows[0]["encrypted_content"] = encrypt(
                b"x" * self.protocol["page_max_bytes"], key, "oversize-content"
            )

        def cursor(row):
            return {
                "created_at": row["created_at"],
                "message_id": row["client_message_id"],
            }

        result = {
            "chat_id": self.chat_id,
            "messages": rows,
            "has_more_before": direction != "before"
            and not (self.mode == "partial_cache" and self.counts["window"] == 1),
            "has_more_after": direction in ("before", "around"),
            "start_cursor": cursor(rows[0]) if rows else None,
            "end_cursor": cursor(rows[-1]) if rows else None,
            "anchor_found": True,
            "oversized_message": False,
            "oversized_message_cursor": None,
            "payload_bytes": sum(
                len(json.dumps(row, separators=(",", ":"), ensure_ascii=False).encode())
                for row in rows
            ),
            "server_message_count": 4,
            "messages_v": 4,
            "compression_boundary_timestamp": None,
            "compression_checkpoints": [],
        }
        if self.mode in ("around_missing", "around_false_nonempty"):
            result["anchor_found"] = False
        if self.mode == "around_missing":
            result["has_more_before"] = result["has_more_after"] = False
        if self.mode in ("around_oversized", "around_wrong_oversized_anchor"):
            result["oversized_message"] = True
            index = 0 if self.mode == "around_wrong_oversized_anchor" else 2
            result["oversized_message_cursor"] = cursor(
                self.protocol["messages"][index]
            )
        if self.mode == "bad_response_cursor":
            result["end_cursor"] = {"created_at": -1, "message_id": "invalid"}
        return result

    def plan(self, method, target, headers, body=None):
        """Validate one request and return HTTP status/body without binding IO."""
        route = urlsplit(target)
        if method == "GET" and route.path == "/__test/status" and not route.query:
            return 200, self.status()
        if method == "POST" and route.path == "/__test/control" and not route.query:
            assert self.mode == "cancel", "cancel control only"
            assert body == {"action": "release"}, "closed cancel control"
            assert self.counts == {"metadata": 1, "window": 0}, "pending metadata only"
            self.cancel_release.set()
            self.checks.add("cancellation-barrier-released")
            return 200, {"released": True}
        self.verify_headers(headers)
        if (
            method == "POST"
            and route.path == "/v1/chats/metadata/batch"
            and not route.query
        ):
            ordinal = self.counts["metadata"] + 1
            assert ordinal <= self.vector["expected_metadata_requests"], (
                "bounded metadata requests"
            )
            assert self.counts["metadata"] == self.counts["window"], (
                "previous read completed"
            )
            assert body == {"chat_ids": [self.chat_id]}, "metadata target"
            self.counts["metadata"] = ordinal
            self.checks.update(("explicit-native-session", "bounded-metadata-requests"))
            if self.mode == "partial_cache" and ordinal == 3:
                # Only the SDK runner can prove preservation; this check marks
                # the prescribed outage after the full read and bounded read.
                self.checks.add("full-cache-preserved")
                return 503, {"detail": "SYNTHETIC_OFFLINE"}
            return 200, self.metadata()
        if (
            method == "GET"
            and route.path == f"/v1/chats/{self.chat_id}/messages/window"
        ):
            ordinal = self.counts["window"] + 1
            assert ordinal <= self.vector["expected_window_requests"], (
                "bounded window requests"
            )
            assert self.counts["metadata"] == ordinal, "metadata precedes each window"
            assert parse_qs(route.query, keep_blank_values=True) == self.expected_query(
                ordinal
            ), "exact window query"
            self.counts["window"] = ordinal
            self.checks.update(
                (
                    "explicit-native-session",
                    "bounded-window-requests",
                    "exact-window-query",
                )
            )
            return 200, self.window()
        raise AssertionError("Unexpected synthetic HTTP operation")

    def handler(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def response(self, status, value):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)

            def dispatch(self, method):
                try:
                    body = None
                    if method == "POST":
                        length = int(self.headers.get("Content-Length", "0"))
                        assert 0 < length < 65536, "bounded request"
                        body = json.loads(self.rfile.read(length))
                    status, value = peer.plan(method, self.path, self.headers, body)
                    if (
                        peer.mode == "cancel"
                        and method == "POST"
                        and urlsplit(self.path).path == "/v1/chats/metadata/batch"
                        and status == 200
                        and not peer.cancel_release.wait(timeout=5)
                    ):
                        peer.failure = peer.failure or "fixture-cancel-barrier-timeout"
                        self.response(
                            503, {"detail": "SYNTHETIC_CANCEL_BARRIER_TIMEOUT"}
                        )
                        return
                    self.response(status, value)
                except (BrokenPipeError, ConnectionResetError):
                    # Cancelling the pending request can close its HTTP stream
                    # before the deliberately released metadata response writes.
                    self.close_connection = True
                except (AssertionError, ValueError, KeyError, TypeError):
                    peer.failure = peer.failure or "fixture-protocol"
                    self.response(500, {})

            def do_GET(self):
                self.dispatch("GET")

            def do_POST(self):
                self.dispatch("POST")

        return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).with_name("fixtures") / "session-message-window.json",
    )
    parser.add_argument("--vector", required=True)
    parser.add_argument("--identity", choices=("rust", "npm", "pip"), required=True)
    args = parser.parse_args()
    suite = json.loads(args.fixture.read_text())["capabilities"][CAPABILITY]
    vector = next(vector for vector in suite["vectors"] if vector["id"] == args.vector)
    peer = MessageWindowPeer(suite, vector, args.identity).start()
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        peer.close()


if __name__ == "__main__":
    main()
