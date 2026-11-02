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
        self.used = set()
        self.unplanned_openers = set()
        self.requests = vector.get("requests_by_language", {}).get(
            identity, vector["requests"]
        )

    def status(self):
        return {
            **super().status(),
            "exact": self.exact,
            "consumed": self.next,
            "unplanned_openers": sorted(self.unplanned_openers),
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
            if self.mode == "details":
                # The held metadata POST's concurrent first window may already
                # have been requested; the client cannot use it until the held
                # metadata admits the read.
                assert self.counts.keys() == expected.keys()
                assert self.counts["metadata"] == expected["metadata"]
                assert (
                    expected["window"]
                    <= self.counts["window"]
                    <= expected["window"] + 1
                )
            else:
                assert self.counts == expected
            self.cancel_release.set()
            self.checks.add(
                "successor-barrier-released"
                if successor
                else "cancellation-barrier-released"
            )
            return 200, {"released": True}
        self.verify_headers(headers)
        index = self.match_planned(method, route, body)
        if index is None:
            return self.unplanned_opener(method, route, body)
        step = self.requests[index]
        self.used.add(index)
        self.next = len(self.used)
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

    @staticmethod
    def opener_kind(method, path):
        """Rich details open with one metadata POST, first messages window and
        first embeds window issued concurrently (open-chat latency); later
        continuation pages depend on earlier replies and stay ordered."""
        if method == "POST" and path == "/v1/chats/metadata/batch":
            return "metadata"
        if (
            method == "GET"
            and path.startswith("/v1/embeds/chats/")
            and path.endswith("/window")
        ):
            return "embeds"
        if (
            method == "GET"
            and path.startswith("/v1/chats/")
            and path.endswith("/messages/window")
        ):
            return "window"
        return None

    def match_planned(self, method, route, body):
        """Exact planned step for this request, or None when it is unplanned.

        Outside details mode the plan is consumed strictly in order. In details
        mode the first planned step of each opener kind within the current
        metadata batch may arrive in any order; every other step is still
        consumed in plan order.
        """
        query = parse_qs(route.query, keep_blank_values=True)
        unused = [i for i in range(len(self.requests)) if i not in self.used]
        if self.mode == "details" and unused:
            # Each metadata POST opens a batch; the first step of each opener
            # kind inside the current batch may arrive in any order.
            batches, batch = [], 0
            for step in self.requests:
                batch += self.opener_kind(step["method"], step["path"]) == "metadata"
                batches.append(batch)
            current = batches[unused[0]]
            first_of_kind = {}
            for i, step in enumerate(self.requests):
                kind = self.opener_kind(step["method"], step["path"])
                if kind is not None and batches[i] == current:
                    first_of_kind.setdefault(kind, i)
            candidates = sorted(
                {unused[0]} | {i for i in first_of_kind.values() if i in unused}
            )
        else:
            candidates = unused[:1]
        for i in candidates:
            step = self.requests[i]
            if (method, route.path) == (step["method"], step["path"]):
                assert query == step.get("query", {}), "exact query"
                assert body == step.get("body"), "exact body"
                return i
        return None

    def unplanned_opener(self, method, route, body):
        """A refusal plan stops after metadata, but the concurrent opener may
        already have requested the first window/embeds page. Answer once per
        kind with an empty, plaintext-free page; the runner still requires the
        typed refusal and no output, so the page can never be used."""
        kind = self.opener_kind(method, route.path)
        planned = {self.opener_kind(s["method"], s["path"]) for s in self.requests}
        allowed = (
            self.mode == "details"
            and kind in ("window", "embeds")
            and kind not in planned
            and kind not in self.unplanned_openers
            and body is None
        )
        if not allowed:
            unused = len(self.used) < len(self.requests)
            raise AssertionError(
                "exact route order" if unused else "bounded planned IO"
            )
        self.unplanned_openers.add(kind)
        chat = route.path.split("/")[3 if kind == "window" else 4]
        assert chat == self.chat_id, "opener for the selected chat only"
        self.checks.add("unused-concurrent-opener")
        if kind == "window":
            return 200, {
                "chat_id": chat,
                "messages": [],
                "has_more_before": False,
                "has_more_after": False,
                "start_cursor": None,
                "end_cursor": None,
                "oversized_message": False,
                "payload_bytes": 0,
            }
        return 200, {
            "chat_id": chat,
            "embeds": [],
            "has_more_before": False,
            "start_cursor": None,
            "oversized_embed_id": None,
        }


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
