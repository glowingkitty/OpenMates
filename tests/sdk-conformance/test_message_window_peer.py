"""Pure synthetic response-plan and independent AES-GCM fixture checks.

No server.start, socket binding, product binary or SDK executes in this suite.
The peer is constructed under a socket constructor trap to enforce that limit.
Only public fixture credentials and encrypted synthetic messages are inspected.
These checks establish fixture integrity, never product or cross-SDK parity.
"""

# contract-test-file: tooling

import base64
import copy
import json
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from message_window_server import CAPABILITY, MessageWindowPeer


def decrypt(value, key):
    raw = base64.b64decode(value, validate=True)
    assert raw[:2] == b"OM"
    return AESGCM(key).decrypt(raw[6:18], raw[18:], None)


class MessageWindowPeerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suite = json.loads(
            (
                Path(__file__).with_name("fixtures") / "session-message-window.json"
            ).read_text()
        )["capabilities"][CAPABILITY]
        cls.vectors = {vector["mode"]: vector for vector in cls.suite["vectors"]
                       if "message_id_overrides" not in vector}

    def peer(self, mode="latest"):
        with patch(
            "message_window_server.ThreadingHTTPServer",
            side_effect=AssertionError("No socket in pure tests"),
        ):
            peer = MessageWindowPeer(
                copy.deepcopy(self.suite), self.vectors[mode], "rust"
            )
        self.assertIsNone(peer.server)
        return peer

    def headers(self):
        return {
            "X-OpenMates-SDK": "rust",
            "Origin": self.suite["protocol"]["app_origin"],
            "Cookie": "auth_refresh_token=" + self.suite["account"]["cookie"],
        }

    def metadata(self, peer):
        return peer.plan(
            "POST",
            "/v1/chats/metadata/batch",
            self.headers(),
            {"chat_ids": [peer.chat_id]},
        )

    def page(self, peer):
        self.metadata(peer)
        # expected_query reflects next request only after the peer increments its
        # GET counter; construct request independently from the vector contract.
        options = (
            peer.vector.get("preflight")
            if peer.counts["window"] == 0 and peer.vector.get("preflight")
            else peer.vector["options"]
        )
        query = {
            "direction": options["direction"],
            "limit": str(options["limit"]),
            "respect_compression_boundary": str(
                options.get("respectCompressionBoundary", True)
            ).lower(),
        }
        if options["direction"] in ("before", "after"):
            query[options["direction"] + "_timestamp"] = options["cursor"]["createdAt"]
            query[options["direction"] + "_message_id"] = options["cursor"]["messageId"]
        if options["direction"] == "around":
            query["anchor_message_id"] = options["anchorMessageId"]
        return peer.plan(
            "GET",
            f"/v1/chats/{peer.chat_id}/messages/window?" + urlencode(query),
            self.headers(),
        )[1]

    def test_construct_status_and_handler_never_bind(self):
        peer = self.peer()
        peer.handler()
        self.assertEqual(
            set(peer.status()),
            {"failure", "checks", "metadata", "window", "identity", "queryMatched"},
        )
        self.assertEqual(peer.plan("GET", "/__test/status", {})[1]["metadata"], 0)
        with self.assertRaises(RuntimeError):
            _ = peer.endpoint

    def test_independent_aes_vectors(self):
        protocol = self.suite["protocol"]
        master = base64.b64decode(self.suite["account"]["master_key"])
        key = decrypt(protocol["metadata"]["encrypted_chat_key"], master)
        self.assertEqual(key, base64.b64decode(protocol["chat_key"]))
        self.assertEqual(
            decrypt(protocol["metadata"]["encrypted_title"], key).decode(),
            "Synthetic bounded chat",
        )
        for index, row in enumerate(protocol["messages"], 1):
            self.assertEqual(
                decrypt(row["encrypted_content"], key).decode(),
                f"Synthetic page message {index} 雪",
            )

    def test_all_four_direction_queries_and_row_order(self):
        for mode in ("latest", "before", "after", "around"):
            with self.subTest(mode=mode):
                peer = self.peer(mode)
                if peer.vector.get("preflight"):
                    self.page(peer)
                result = self.page(peer)
                self.assertEqual(
                    [row["id"] for row in result["messages"]],
                    peer.vector["expected_message_ids"],
                )
                self.assertEqual(
                    peer.counts["window"], peer.vector["expected_window_requests"]
                )
                self.assertEqual(
                    peer.counts["metadata"], peer.vector["expected_metadata_requests"]
                )
                self.assertTrue(peer.status()["queryMatched"])

    def test_identity_cookie_origin_and_bearer_are_exact(self):
        for key, value in (
            ("X-OpenMates-SDK", "unknown"),
            ("Origin", "https://foreign.invalid"),
            ("Cookie", "wrong"),
            ("Authorization", "Bearer synthetic"),
        ):
            with self.subTest(key=key):
                peer = self.peer()
                headers = self.headers()
                headers[key] = value
                with self.assertRaises(AssertionError):
                    peer.plan(
                        "POST",
                        "/v1/chats/metadata/batch",
                        headers,
                        {"chat_ids": [peer.chat_id]},
                    )
                self.assertEqual(peer.counts, {"metadata": 0, "window": 0})

    def test_extra_reads_and_query_parameters_refuse(self):
        peer = self.peer()
        self.page(peer)
        with self.assertRaises(AssertionError):
            self.metadata(peer)
        peer = self.peer()
        self.metadata(peer)
        with self.assertRaises(AssertionError):
            peer.plan(
                "GET",
                f"/v1/chats/{peer.chat_id}/messages/window?direction=latest&limit=100&respect_compression_boundary=false",
                self.headers(),
            )
        with self.assertRaises(AssertionError):
            self.peer().plan("GET", "/v1/ws", self.headers())

    def test_wrong_key_and_tamper_are_genuine_crypto_failures(self):
        master = base64.b64decode(self.suite["account"]["master_key"])
        for mode in ("wrong_key", "tamper"):
            peer = self.peer(mode)
            key = decrypt(peer.metadata()["chats"][0]["encrypted_chat_key"], master)
            page = peer.window()
            with self.assertRaises(InvalidTag):
                decrypt(page["messages"][0]["encrypted_content"], key)

    def test_row_byte_identity_cursor_failure_shapes(self):
        self.assertEqual(len(self.peer("over_rows").window()["messages"]), 21)
        self.assertGreater(self.peer("over_bytes").window()["payload_bytes"], 262144)
        self.assertNotEqual(
            self.peer("wrong_chat").window()["messages"][0]["chat_id"],
            self.suite["protocol"]["chat_id"],
        )
        self.assertEqual(
            self.peer("bad_response_cursor").window()["end_cursor"]["created_at"], -1
        )

    def test_page_local_maps_and_literal_unknown_payloads(self):
        key = base64.b64decode(self.suite["protocol"]["chat_key"])
        for mode in ("page_local_maps", "page_local_unknown"):
            peer = self.peer(mode)
            page = peer.window()
            text = decrypt(page["messages"][0]["encrypted_content"], key).decode()
            self.assertEqual(page["messages"][0]["role"], "user")
            self.assertNotIn("encrypted_pii_mappings", page["messages"][1])
            mappings = json.loads(
                decrypt(page["messages"][0]["encrypted_pii_mappings"], key)
            )
            token = peer.protocol[
                "known_placeholder"
                if mode == "page_local_maps"
                else "unknown_placeholder"
            ]
            self.assertIn(token, text)
            matches = [
                mapping for mapping in mappings if mapping["placeholder"] == token
            ]
            self.assertEqual(len(matches), int(mode == "page_local_maps"))
            self.assertIsNone(peer.vector["expected_error"])

    def test_partial_cache_full_window_then_partial_then_offline(self):
        peer = self.peer("partial_cache")
        self.assertEqual(self.metadata(peer)[0], 200)
        full_query = "direction=latest&limit=100&respect_compression_boundary=false"
        path = f"/v1/chats/{peer.chat_id}/messages/window?"
        before = copy.deepcopy(peer.status())
        messages = copy.deepcopy(peer.protocol["messages"])
        with self.assertRaises(AssertionError):
            peer.plan("GET", path + full_query + "&extra=forbidden", self.headers())
        self.assertEqual(peer.status(), before)
        self.assertEqual(peer.protocol["messages"], messages)
        status, full = peer.plan("GET", path + full_query, self.headers())
        self.assertEqual(status, 200)
        self.assertEqual(len(full["messages"]), 4)
        self.assertFalse(full["has_more_before"])
        self.assertEqual(self.metadata(peer)[0], 200)
        status, partial = peer.plan(
            "GET",
            path + "direction=latest&limit=2&respect_compression_boundary=true",
            self.headers(),
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(partial["messages"]), 2)
        self.assertEqual(len(full["messages"]), 4)
        self.assertEqual(self.metadata(peer)[0], 503)
        self.assertEqual(peer.counts, {"metadata": 3, "window": 2})
        self.assertIn("full-cache-preserved", peer.status()["checks"])
        before = copy.deepcopy(peer.status())
        with self.assertRaises(AssertionError):
            peer.plan("GET", path + full_query, self.headers())
        self.assertEqual(peer.status(), before)

    def test_pending_cancel_control_releases_event_without_read_counts(self):
        peer = self.peer("cancel")
        self.assertFalse(peer.cancel_release.is_set())
        self.assertEqual(self.metadata(peer)[0], 200)
        self.assertEqual(peer.counts, {"metadata": 1, "window": 0})
        self.assertFalse(peer.cancel_release.is_set())
        before = copy.deepcopy(peer.status())
        for body in ({"action": "unknown"}, {"action": "release", "extra": True}):
            with self.assertRaises(AssertionError):
                peer.plan("POST", "/__test/control", {}, body)
            self.assertEqual(peer.status(), before)
            self.assertFalse(peer.cancel_release.is_set())
        status, value = peer.plan("POST", "/__test/control", {}, {"action": "release"})
        self.assertEqual((status, value), (200, {"released": True}))
        self.assertTrue(peer.cancel_release.is_set())
        self.assertEqual(peer.counts, {"metadata": 1, "window": 0})
        self.assertIn("cancellation-barrier-released", peer.status()["checks"])
        with self.assertRaises(AssertionError):
            peer.plan(
                "GET",
                f"/v1/chats/{peer.chat_id}/messages/window?direction=latest&limit=2&respect_compression_boundary=true",
                self.headers(),
            )
        self.assertEqual(peer.counts, {"metadata": 1, "window": 0})
        unstarted = self.peer("cancel")
        unstarted.close()
        self.assertTrue(unstarted.cancel_release.is_set())

    def test_cancel_http_handler_wait_is_finite_without_socket(self):
        peer = self.peer("cancel")
        handler = peer.handler().__new__(peer.handler())
        body = json.dumps({"chat_ids": [peer.chat_id]}).encode()
        handler.path = "/v1/chats/metadata/batch"
        handler.headers = {**self.headers(), "Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.response = Mock()
        with patch.object(peer.cancel_release, "wait", return_value=False) as wait:
            handler.dispatch("POST")
        wait.assert_called_once_with(timeout=5)
        self.assertEqual(handler.response.call_args.args[0], 503)
        self.assertEqual(peer.failure, "fixture-cancel-barrier-timeout")
        self.assertEqual(peer.counts, {"metadata": 1, "window": 0})

    def public_paging(self, peer, page):
        def position(cursor):
            return (
                None
                if cursor is None
                else {
                    "createdAt": cursor["created_at"],
                    "messageId": cursor["message_id"],
                }
            )

        key = base64.b64decode(peer.protocol["chat_key"])
        row = peer.protocol["metadata"]
        return {
            "chat": {
                "id": peer.chat_id,
                "title": decrypt(row["encrypted_title"], key).decode(),
                "category": decrypt(row["encrypted_category"], key).decode(),
            },
            "hasMoreBefore": page["has_more_before"],
            "hasMoreAfter": page["has_more_after"],
            "anchorFound": page["anchor_found"],
            "startCursor": position(page["start_cursor"]),
            "endCursor": position(page["end_cursor"]),
            "serverMessageCount": page["server_message_count"],
            "messagesVersion": page["messages_v"],
            "oversizedMessage": page["oversized_message"],
            "oversizedMessageCursor": position(page["oversized_message_cursor"]),
            "payloadBytes": sum(
                len(
                    json.dumps(row, separators=(",", ":"), ensure_ascii=False).encode(
                        "utf-8"
                    )
                )
                for row in page["messages"]
            ),
            "historyComplete": False,
            "piiRestoration": "page_local",
        }

    def test_literal_public_paging_oracle_for_every_success(self):
        self.assertEqual(len(self.vectors), 25)
        self.assertEqual(self.vectors["private_denied"]["expected_error"], "forbidden")
        self.assertIs(self.vectors["private_denied"]["allow_private_operations"], False)
        for mode, vector in self.vectors.items():
            if vector["expected_error"] is not None:
                continue
            with self.subTest(mode=mode):
                peer = self.peer(mode)
                if vector.get("preflight"):
                    self.page(peer)
                if mode == "partial_cache":
                    self.metadata(peer)
                    peer.plan(
                        "GET",
                        f"/v1/chats/{peer.chat_id}/messages/window?direction=latest&limit=100&respect_compression_boundary=false",
                        self.headers(),
                    )
                page = self.page(peer)
                self.assertEqual(
                    page["payload_bytes"],
                    self.public_paging(peer, page)["payloadBytes"],
                )
                self.assertEqual(
                    self.public_paging(peer, page), vector["expected_public_paging"]
                )

    def test_oracle_comparison_rejects_each_mutated_public_field(self):
        peer = self.peer("latest")
        actual = self.public_paging(peer, self.page(peer))
        expected = peer.vector["expected_public_paging"]
        for field, value in actual.items():
            with self.subTest(field=field):
                changed = copy.deepcopy(actual)
                if type(value) is bool:
                    changed[field] = not value
                elif type(value) is int:
                    changed[field] = value + 1
                elif type(value) is str:
                    changed[field] = value + "-wrong"
                elif value is None:
                    changed[field] = {
                        "createdAt": 0,
                        "messageId": peer.protocol["message_ids"][0],
                    }
                elif field == "chat":
                    changed[field]["id"] = "99999999-9999-4999-8999-999999999999"
                else:
                    changed[field]["createdAt"] += 1
                with self.assertRaises(AssertionError):
                    self.assertEqual(changed, expected)

    def test_around_anchor_guards_alias_missing_and_oversized_shapes(self):
        for mode in (
            "around_wrong_anchor",
            "around_false_nonempty",
            "around_missing",
            "around_alias",
            "around_oversized",
            "around_wrong_oversized_anchor",
        ):
            with self.subTest(mode=mode):
                peer = self.peer(mode)
                page = self.page(peer)
                anchor = peer.vector["options"]["anchorMessageId"]
                if mode == "around_wrong_anchor":
                    self.assertTrue(page["anchor_found"])
                    self.assertFalse(
                        any(
                            anchor in (row["id"], row["client_message_id"])
                            for row in page["messages"]
                        )
                    )
                elif mode == "around_false_nonempty":
                    self.assertFalse(page["anchor_found"])
                    self.assertTrue(page["messages"])
                elif mode == "around_alias":
                    row = page["messages"][-1]
                    self.assertEqual(row["id"], anchor)
                    self.assertNotEqual(row["client_message_id"], anchor)
                    self.assertEqual(
                        page["end_cursor"]["message_id"], row["client_message_id"]
                    )
                else:
                    self.assertEqual(page["messages"], [])
                    self.assertIsNone(page["start_cursor"])
                    self.assertIsNone(page["end_cursor"])
                    self.assertEqual(page["payload_bytes"], 0)
                    oversized = mode != "around_missing"
                    self.assertEqual(page["anchor_found"], oversized)
                    self.assertEqual(page["oversized_message"], oversized)
                    self.assertEqual(page["has_more_before"], oversized)
                    self.assertEqual(page["has_more_after"], oversized)
                    if oversized:
                        self.assertEqual(
                            page["oversized_message_cursor"]["message_id"] == anchor,
                            mode == "around_oversized",
                        )

    def test_opaque_message_vectors_reuse_real_peer_and_all_sdk_identities(self):
        vectors = [v for v in self.suite["vectors"] if "message_id_overrides" in v]
        self.assertEqual(len(vectors), 2)
        for identity in ("rust", "npm", "pip"):
            for vector in vectors:
                with patch("message_window_server.ThreadingHTTPServer", side_effect=AssertionError("No socket in pure tests")):
                    peer = MessageWindowPeer(copy.deepcopy(self.suite), vector, identity)
                self.assertIsNone(peer.server)
                headers = {**self.headers(), "X-OpenMates-SDK": identity}
                self.assertEqual(peer.plan("POST", "/v1/chats/metadata/batch", headers, {"chat_ids": [peer.chat_id]})[0], 200)
                query = {"direction": vector["options"]["direction"], "limit": vector["options"]["limit"], "respect_compression_boundary": "true"}
                if vector["mode"] == "around":
                    query["anchor_message_id"] = vector["options"]["anchorMessageId"]
                page = peer.plan("GET", f"/v1/chats/{peer.chat_id}/messages/window?" + urlencode(query), headers)[1]
                logical = [row["client_message_id"] for row in page["messages"]]
                self.assertEqual(logical, vector["expected_message_ids"])
                self.assertTrue(all(row["id"] != row["client_message_id"] for row in page["messages"]))
                self.assertEqual(self.public_paging(peer, page), vector["expected_public_paging"])
                key = base64.b64decode(peer.protocol["chat_key"])
                for row, expected in zip(page["messages"], vector["expected_messages"]):
                    self.assertEqual(decrypt(row["encrypted_content"], key).decode(), expected["content"])
                self.assertEqual(peer.counts, {"metadata": 1, "window": 1})
                self.assertTrue(peer.status()["queryMatched"])

    def test_invalid_input_auth_have_zero_peer_calls(self):
        for mode in ("bad_input_cursor", "noauth"):
            peer = self.peer(mode)
            self.assertEqual(peer.status()["metadata"], 0)
            self.assertEqual(peer.vector["expected_metadata_requests"], 0)


if __name__ == "__main__":
    unittest.main()
