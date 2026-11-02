"""Pure genuine-ciphertext/cache-window checks, never SDK or listener execution."""

# contract-test-file: tooling
import ast
import base64
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import cache_settlement_peer as cache
from essential_session_server import EssentialPeer
from recovery_server import decrypt

ROOT = Path(__file__).resolve().parent


class CachePeerRowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suite = json.loads(
            (ROOT / "fixtures/session-cache-preferred-settlement.json").read_text()
        )["capabilities"][cache.CAPABILITY]

    def peer(self, identity="rust"):
        # Keep actual peer constructors/crypto, replace only listener creation.
        with patch("recovery_server.ThreadingHTTPServer"):
            return cache.CacheSettlementPeer(
                self.suite, {"id": "selected-exact-ack"}, identity
            )

    def test_every_adapter_peer_owns_exact40_genuine_rows_in_canonical_order(self):
        key = base64.b64decode(self.suite["protocol"]["initial_chat_key"])
        for identity in ("rust", "npm", "pip"):
            peer = self.peer(identity)
            self.assertEqual(peer.version, 40)
            self.assertEqual(len(peer.messages), 40)
            for index, row in enumerate(peer.messages, 1):
                self.assertEqual(row["id"], f"10000000-0000-4000-8000-{index:012d}")
                self.assertEqual(row["client_message_id"], row["id"])
                self.assertEqual(row["chat_id"], peer.chat_id)
                self.assertEqual(row["created_at"], index)
                self.assertEqual(row["role"], "user" if index % 2 else "assistant")
                self.assertEqual(
                    decrypt(row["encrypted_content"], key).decode(),
                    f"Synthetic cache row {index:03d} 雪",
                )
                self.assertEqual(
                    decrypt(row["encrypted_sender_name"], key), b"Fixture sender"
                )
                self.assertNotIn("content", row)

    def test_complete100_and_latest20_have_truthful_distinct_counts_and_cursors(self):
        peer = self.peer()
        full = cache.message_window(
            peer.messages,
            peer.chat_id,
            peer.version,
            {
                "direction": ["latest"],
                "limit": ["100"],
                "respect_compression_boundary": ["false"],
            },
        )
        recent = cache.message_window(
            peer.messages,
            peer.chat_id,
            peer.version,
            {
                "direction": ["latest"],
                "limit": ["20"],
                "respect_compression_boundary": ["false"],
            },
        )
        self.assertEqual(full["messages"], peer.messages)
        self.assertFalse(full["has_more_before"])
        self.assertEqual(recent["messages"], peer.messages[20:])
        self.assertTrue(recent["has_more_before"])
        for page in (full, recent):
            self.assertEqual(page["server_message_count"], 40)
            self.assertEqual(page["messages_v"], 40)
            self.assertEqual(
                page["start_cursor"]["message_id"], page["messages"][0]["id"]
            )
            self.assertEqual(
                page["start_cursor"]["created_at"], page["messages"][0]["created_at"]
            )
            self.assertEqual(
                page["end_cursor"]["message_id"], page["messages"][-1]["id"]
            )
            self.assertEqual(
                page["payload_bytes"],
                sum(
                    len(
                        json.dumps(
                            row, separators=(",", ":"), ensure_ascii=False
                        ).encode()
                    )
                    for row in page["messages"]
                ),
            )

    def test_before_latest20_boundary_returns_exact_older20_without_duplicate(self):
        peer = self.peer()
        page = cache.message_window(
            peer.messages,
            peer.chat_id,
            peer.version,
            {
                "direction": ["before"],
                "limit": ["20"],
                "respect_compression_boundary": ["false"],
                "before_timestamp": ["21"],
                "before_message_id": [peer.messages[20]["id"]],
            },
        )
        self.assertEqual(page["messages"], peer.messages[:20])
        self.assertFalse(page["has_more_before"])
        self.assertTrue(page["has_more_after"])

    def test_old_essential_monitor_stays_empty_and_is_not_modified(self):
        with patch("recovery_server.ThreadingHTTPServer"):
            peer = EssentialPeer(self.suite, {"mode": "monitor"}, "rust")
        self.assertEqual(peer.messages, [])
        self.assertEqual(peer.version, 5)

    def test_real_http_handler_uses_bounded_cache_page_without_binding_io(self):
        peer = self.peer()
        handler = object.__new__(peer.handler())
        handler.path = f"/v1/chats/{peer.chat_id}/messages/window?direction=latest&limit=20&respect_compression_boundary=false"
        captured = []
        handler.response = lambda status, body: captured.append((status, body))
        with patch.object(peer, "headers") as headers:
            handler.do_GET()
        headers.assert_called_once_with(handler)
        self.assertEqual(captured[0][0], 200)
        self.assertEqual(captured[0][1]["messages"], peer.messages[20:])

    def test_actual_python_driver_oracle_rejects_missing_reordered_or_changed_rows(
        self,
    ):
        tree = ast.parse(
            (ROOT / "runners/session-cache-preferred-settlement.py").read_text()
        )
        node = next(
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "assert_owned_rows"
        )
        scope = {}
        exec(
            compile(
                ast.Module(body=[node], type_ignores=[]), "pure_cache_rows", "exec"
            ),
            scope,
        )
        chat = {
            "messages": [
                {
                    "id": f"10000000-0000-4000-8000-{index:012d}",
                    "content": f"Synthetic cache row {index:03d} 雪",
                    "role": "user" if index % 2 else "assistant",
                    "sender": "Fixture sender",
                    "thinking": "",
                    "embeds": [],
                }
                for index in range(1, 41)
            ]
        }
        scope["assert_owned_rows"](chat)
        for change in ("missing", "reordered", "id", "content", "role"):
            value = copy.deepcopy(chat)
            if change == "missing":
                value["messages"].pop(0)
            elif change == "reordered":
                value["messages"].reverse()
            else:
                value["messages"][0][change] = "synthetic-wrong"
            with self.assertRaises(AssertionError):
                scope["assert_owned_rows"](value)


if __name__ == "__main__":
    unittest.main()
