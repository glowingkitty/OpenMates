#!/usr/bin/env python3
"""Closed synthetic protocol plan for bounded saved reads, no ambient credentials.
Constructing a peer never binds IO; managed runners explicitly start it.
"""

from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit
from message_window_server import MessageWindowPeer

CAPABILITY = "session.saved-chat-read.v1"


def planned_reply(step):
    value = copy.deepcopy(step["reply"])
    if "replyExpansion" in step:
        assert step["replyExpansion"] == "exact-over-two-mib"
        # Invalid bounded response must fail before any decryption. Keep the
        # shared fixture compact while all real adapters receive >2MiB bytes.
        value["message"]["encrypted_content"] = "x" * (2 * 1024 * 1024 + 1)
    return value


class SavedChatReadPeer(MessageWindowPeer):
    def __init__(self, suite, vector, identity):
        super().__init__(suite, vector, identity)
        self.details_embeds = 0
        self.exact = 0
        self.next = 0
        self.requests = vector.get("requests_by_language", {}).get(
            identity, vector["requests"]
        )

    def status(self):
        return {
            **super().status(),
            "exact": self.exact,
            "consumed": self.next,
            **(
                {"details_embeds": self.details_embeds}
                if self.mode == "details"
                else {}
            ),
        }

    def plan(self, method, target, headers, body=None):
        route = urlsplit(target)
        if method == "GET" and route.path == "/__test/status" and not route.query:
            return 200, self.status()
        if method == "POST" and route.path == "/__test/control" and not route.query:
            successor = (
                self.vector.get("foreign_final") == "successor"
                and self.identity != "rust"
            )
            assert (
                self.mode == "cancel"
                or self.vector.get("exactAction") == "cancel"
                or self.vector.get("full_action") == "inflight_cancel"
                or self.vector.get("details_action") == "inflight_cancel"
                or successor
            ) and body == {"action": "release"}
            expected = (
                {"metadata": 3, "window": 2}
                if successor
                else (
                    {"metadata": 2, "window": 1}
                    if self.vector.get("exactAction") == "cancel"
                    else {"metadata": 1, "window": 0}
                )
            )
            expected = self.vector.get("cancel_expected_counts", expected)
            assert self.counts == expected
            self.cancel_release.set()
            self.checks.add(
                "successor-barrier-released"
                if successor
                else "cancellation-barrier-released"
            )
            return 200, {"released": True}
        self.verify_headers(headers)
        assert self.next < len(self.requests), "bounded planned IO"
        step = self.requests[self.next]
        assert (method, route.path) == (step["method"], step["path"]), (
            "exact route order"
        )
        assert parse_qs(route.query, keep_blank_values=True) == step.get("query", {}), (
            "exact query"
        )
        assert body == step.get("body"), "exact body"
        self.next += 1
        self.checks.add("explicit-native-session")
        if self.mode == "details":
            self.checks.add("selected-rich-read")
        if self.mode == "full":
            self.checks.add("explicit-full-read")
        if method == "POST":
            self.counts["metadata"] += 1
            self.checks.add("bounded-metadata-requests")
        elif self.mode == "details" and route.path.startswith("/v1/embeds/"):
            self.details_embeds += 1
            self.checks.add("selected-embed-inventory")
        elif route.path.endswith("/window"):
            self.counts["window"] += 1
            self.checks.update(("bounded-window-requests", "exact-window-query"))
        else:
            self.exact += 1
            self.checks.add("explicit-exact-read")
        if (
            step.get("holdForCancel") or step.get("holdForSuccessor")
        ) and self.server is not None:
            if not self.cancel_release.wait(timeout=5):
                self.failure = "fixture-cancel-barrier-timeout"
                return 503, {"detail": "SYNTHETIC_CANCEL_BARRIER_TIMEOUT"}
        return step.get("status", 200), planned_reply(step)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--vector", required=True)
    parser.add_argument("--identity", choices=("rust", "npm", "pip"), required=True)
    args = parser.parse_args()
    suite = json.loads(args.fixture.read_text())["capabilities"][CAPABILITY]
    vector = next(v for v in suite["vectors"] if v["id"] == args.vector)
    peer = SavedChatReadPeer(suite, vector, args.identity).start()
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        peer.close()


if __name__ == "__main__":
    main()
