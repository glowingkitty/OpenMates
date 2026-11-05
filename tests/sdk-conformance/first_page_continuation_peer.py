"""Authored UNRUN first-page family peer. Only synthetic loopback protocols.

Reuses existing explicit identity/Cookie/auth/crypto fixture. Its140 encrypted
rows require latest100 then before40. A local request log proves no duplicate
latest or older request before first-page continuation; no product control route.
"""

import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from cache_settlement_peer import CacheSettlementPeer, message_window, CAPABILITY
from recovery_server import encrypt


class FirstPagePeer(CacheSettlementPeer):
    def __init__(self, suite, identity, request_log, message_id_mode="uuid"):
        super().__init__(suite, {"id": "first-page-exact-ack"}, identity)
        self.request_log = request_log
        self.message_id_mode = message_id_mode
        self.messages = [
            {
                "id": f"10000000-0000-4000-8000-{index:012d}",
                "client_message_id": f"10000000-0000-4000-8000-{index:012d}",
                "chat_id": self.chat_id,
                "role": "user" if index % 2 else "assistant",
                "created_at": index,
                "encrypted_content": encrypt(
                    f"Synthetic first-page row {index:03d} 雪".encode(), self.key
                ),
                "encrypted_sender_name": encrypt(b"Fixture sender", self.key),
            }
            for index in range(1, 141)
        ]
        if message_id_mode != "uuid":
            for index, row in enumerate(self.messages, 1):
                logical = (
                    (self.chat_id.replace("-", "")[:10] + "-" + row["id"])
                    if message_id_mode == "composite"
                    else f"legacy_msg_{index:04d}"
                )
                row["client_message_id"] = logical
                row["message_id"] = logical
        self.version = len(self.messages)

    def handler(self):
        parent = super().handler()
        peer = self

        class Handler(parent):
            def do_GET(self):
                route = urlsplit(self.path)
                if route.path == f"/v1/chats/{peer.chat_id}/messages/window":
                    peer.headers(self)
                    query = parse_qs(route.query)
                    page = message_window(
                        peer.messages, peer.chat_id, peer.version, query
                    )
                    request = {
                        "direction": query["direction"][0],
                        "limit": int(query["limit"][0]),
                    }
                    if peer.message_id_mode != "uuid" and query["direction"] == [
                        "before"
                    ]:
                        request["cursor_message_id"] = query["before_message_id"][0]
                    with peer.request_log.open("a", encoding="utf-8") as log:
                        log.write(json.dumps(request) + "\n")
                        log.flush()
                    self.response(200, page)
                    return
                super().do_GET()

        return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument(
        "--capability",
        choices=[CAPABILITY, "session.chat-first-page-continuation.v1"],
        default=CAPABILITY,
    )
    parser.add_argument("--request-log", type=Path, required=True)
    parser.add_argument("--identity", choices=["rust", "npm", "pip"], required=True)
    parser.add_argument(
        "--message-id-mode", choices=["uuid", "composite", "opaque"], default="uuid"
    )
    args = parser.parse_args()
    suite = json.loads(args.fixture.read_bytes())["capabilities"][args.capability]
    peer = FirstPagePeer(suite, args.identity, args.request_log, args.message_id_mode)
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    try:
        peer.server.serve_forever()
    finally:
        peer.server.server_close()


if __name__ == "__main__":
    main()
