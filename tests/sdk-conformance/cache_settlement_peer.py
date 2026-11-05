"""Owned encrypted cache peer for native/three-SDK cache policy regressions.

Uses only the existing synthetic Cookie, keys, crypto envelope and window wire
protocol. Essential/recovery fixtures retain their original empty-history state.
"""

import argparse
import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from essential_session_server import EssentialPeer
from recovery_server import encrypt

CAPABILITY = "session.cache-preferred-settlement.v1"
ROW_COUNT = 40


def owned_rows(chat_id, key):
    return [
        {
            "id": f"10000000-0000-4000-8000-{index:012d}",
            "client_message_id": f"10000000-0000-4000-8000-{index:012d}",
            "chat_id": chat_id,
            "role": "user" if index % 2 else "assistant",
            "created_at": index,
            "encrypted_content": encrypt(
                f"Synthetic cache row {index:03d} 雪".encode(), key
            ),
            "encrypted_sender_name": encrypt(b"Fixture sender", key),
        }
        for index in range(1, ROW_COUNT + 1)
    ]


def message_window(rows, chat_id, messages_v, query):
    assert set(query) <= {
        "direction",
        "limit",
        "respect_compression_boundary",
        "before_timestamp",
        "before_message_id",
    }
    assert query["direction"] in (["latest"], ["before"])
    assert len(query["limit"]) == 1
    limit = int(query["limit"][0])
    assert 1 <= limit <= 100
    assert query["respect_compression_boundary"] in (["false"], ["true"])
    end = len(rows)
    if query["direction"] == ["before"]:
        boundary = (int(query["before_timestamp"][0]), query["before_message_id"][0])
        end = next(
            (
                index
                for index, row in enumerate(rows)
                if (row["created_at"], row["client_message_id"]) >= boundary
            ),
            len(rows),
        )
    else:
        assert "before_timestamp" not in query and "before_message_id" not in query
    start = max(0, end - limit)
    selected = copy.deepcopy(rows[start:end])

    def cursor(row):
        return {"created_at": row["created_at"], "message_id": row["client_message_id"]}

    return {
        "chat_id": chat_id,
        "messages": selected,
        "has_more_before": start > 0,
        "has_more_after": end < len(rows),
        "start_cursor": cursor(selected[0]) if selected else None,
        "end_cursor": cursor(selected[-1]) if selected else None,
        "server_message_count": len(rows),
        "messages_v": messages_v,
        "anchor_found": True,
        "oversized_message": False,
        "oversized_message_cursor": None,
        "payload_bytes": sum(
            len(json.dumps(row, separators=(",", ":"), ensure_ascii=False).encode())
            for row in selected
        ),
        "compression_boundary_timestamp": None,
        "compression_checkpoints": [],
    }


class CacheSettlementPeer(EssentialPeer):
    def __init__(self, suite, vector, identity):
        super().__init__(suite, {"id": vector["id"], "mode": "monitor"}, identity)
        self.messages = owned_rows(self.chat_id, self.key)
        self.version = len(self.messages)

    def handler(self):
        parent = super().handler()
        peer = self

        class Handler(parent):
            def do_GET(self):
                route = urlsplit(self.path)
                if route.path == f"/v1/chats/{peer.chat_id}/messages/window":
                    peer.headers(self)
                    page = message_window(
                        peer.messages, peer.chat_id, peer.version, parse_qs(route.query)
                    )
                    self.response(200, page)
                    peer.mark("canonical-message-reread")
                    return
                super().do_GET()

        return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--capability", required=True, choices=[CAPABILITY])
    parser.add_argument("--vector", required=True)
    parser.add_argument("--identity", required=True, choices=["rust", "npm", "pip"])
    args = parser.parse_args()
    suite = json.loads(args.fixture.read_bytes())["capabilities"][CAPABILITY]
    assert args.vector in {v["id"] for v in suite["vectors"]}
    peer = CacheSettlementPeer(suite, {"id": args.vector}, args.identity)
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    try:
        peer.server.serve_forever()
    finally:
        peer.server.server_close()


if __name__ == "__main__":
    main()
