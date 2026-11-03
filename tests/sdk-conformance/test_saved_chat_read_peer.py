"""Pure closed-peer and independent AES fixture proof; no sockets or product runtime."""

# contract-test-file: tooling
import base64
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import jsonschema
from saved_chat_read_server import CAPABILITY, SavedChatReadPeer, planned_reply

ROOT = Path(__file__).parent
FIXTURE = ROOT / "fixtures/session-saved-chat-read.json"
ORIGINAL66_SHA256 = "7ce960307d26ad347857cda9713a40d5f5f08caa07accf04b4d8f49ee62fe888"


class SavedChatReadPeerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suite = json.loads(FIXTURE.read_text())["capabilities"][CAPABILITY]
        cls.schema = json.loads(
            (ROOT / "schemas/session-saved-chat-read.schema.json").read_text()
        )

    def peer(self, v, identity="rust"):
        with patch(
            "message_window_server.ThreadingHTTPServer",
            side_effect=AssertionError("No fixture socket permitted"),
        ):
            return SavedChatReadPeer(copy.deepcopy(self.suite), v, identity)

    def test_every_planned_request_has_explicit_credentials_and_closed_bounds(self):
        for vector in self.suite["vectors"]:
            peer = self.peer(vector)
            headers = {
                "X-OpenMates-SDK": "rust",
                "Origin": self.suite["protocol"]["app_origin"],
                "Cookie": "auth_refresh_token=" + self.suite["account"]["cookie"],
            }
            for step in peer.requests:
                query = urlencode(step.get("query", {}), doseq=True)
                code, value = peer.plan(
                    step["method"],
                    step["path"] + ("?" + query if query else ""),
                    headers,
                    step.get("body"),
                )
                self.assertEqual(code, step.get("status", 200))
                self.assertEqual(value, planned_reply(step))
                if "messages" in value:
                    rows = value["messages"]
                    self.assertLessEqual(
                        len(rows),
                        30
                        if vector["id"]
                        == "details-latest-accepts-alternate-server-cap30"
                        else 20,
                    )
                    actual = sum(
                        len(
                            json.dumps(
                                row, separators=(",", ":"), ensure_ascii=False
                            ).encode()
                        )
                        for row in rows
                    )
                    if vector["id"] == "invalid-page-byte-claim":
                        self.assertNotEqual(value["payload_bytes"], actual)
                    else:
                        self.assertEqual(value["payload_bytes"], actual)
                    self.assertLessEqual(actual, 256 * 1024)
            counts = vector.get("expected_counts_by_language", {}).get("rust", {})
            status = peer.status()
            self.assertEqual(
                status["metadata"],
                counts.get("metadata", vector["expected_metadata_requests"]),
            )
            self.assertEqual(
                status["window"],
                counts.get("window", vector["expected_window_requests"]),
            )
            self.assertEqual(status["exact"], vector["expected_exact_requests"])
            if (
                vector["mode"] != "cancel"
                and vector.get("exactAction") != "cancel"
                and vector.get("full_action") != "inflight_cancel"
                and vector.get("details_action") != "inflight_cancel"
            ):
                self.assertTrue(set(vector["expected_checks"]) <= set(status["checks"]))
            with self.assertRaises(AssertionError):
                peer.plan("GET", "/unplanned", headers)

    def test_schemas_reject_invalid_options_without_runtime(self):
        for vector in self.suite["vectors"]:
            errors = list(
                jsonschema.Draft202012Validator(self.schema).iter_errors(
                    vector["options"]
                )
            )
            self.assertEqual(bool(errors), vector["mode"] == "invalid", vector["id"])

    def test_genuine_encrypted_65_row_fixture_and_default_all_separation(self):
        key = base64.b64decode(self.suite["protocol"]["chat_key"])
        rows = self.suite["protocol"]["messages"]
        self.assertEqual(len(rows), 65)
        for row, plain in zip(rows, self.suite["protocol"]["plain_messages"]):
            raw = base64.b64decode(row["encrypted_content"], validate=True)
            self.assertEqual(raw[:2], b"OM")
            self.assertEqual(
                AESGCM(key).decrypt(raw[6:18], raw[18:], None).decode(),
                plain["content"],
            )
        vectors = {v["id"]: v for v in self.suite["vectors"]}
        self.assertEqual(len(vectors["default-30-from-65"]["expected_messages"]), 30)
        self.assertEqual(
            len(vectors["first-100-terminates-at-65"]["expected_messages"]), 65
        )
        cache = vectors["bounded-30-keeps-full-65-cache"]
        self.assertEqual(len(cache["expected_cached_messages"]), 65)
        self.assertEqual(len(cache["expected_messages"]), 30)
        self.assertTrue(
            all(
                v.get("expected_public_paging", {}).get("historyComplete", False)
                is False
                for v in self.suite["vectors"]
            )
        )

    def test_explicit_oversize_is_real_and_has_exact_only_followup(self):
        vector = next(v for v in self.suite["vectors"] if v["mode"] == "exact")
        row = vector["requests"][-1]["reply"]["message"]
        size = len(json.dumps(row, separators=(",", ":")).encode())
        self.assertGreater(size, 256 * 1024)
        self.assertLessEqual(size, 2 * 1024 * 1024)
        raw = base64.b64decode(row["encrypted_content"])
        key = base64.b64decode(self.suite["protocol"]["chat_key"])
        self.assertEqual(
            AESGCM(key).decrypt(raw[6:18], raw[18:], None).decode(),
            vector["exact_expected"]["message"]["content"],
        )
        self.assertEqual(vector["expected_public_paging"]["chat"]["messages"], [])

    def test_negative_exact_vectors_bound_and_reject_before_plaintext(self):
        vectors = {v["id"]: v for v in self.suite["vectors"]}
        value = planned_reply(vectors["exact-over-two-mib"]["requests"][-1])
        size = len(json.dumps(value["message"], separators=(",", ":")).encode())
        self.assertGreater(size, 2 * 1024 * 1024)
        self.assertLess(size, 16 * 1024 * 1024)
        for identity in ["exact-stale-live-scope", "exact-foreign-chat-cursor"]:
            vector = vectors[identity]
            self.assertEqual(len(vector["requests"]), 2)
            self.assertEqual(vector["expected_metadata_requests"], 1)
            self.assertEqual(vector["expected_exact_requests"], 0)
            self.assertEqual(vector["exact_expected_error"], "conflict")
        self.assertEqual(
            vectors["exact-cancel-before-publish"]["exact_expected_error"], "cancelled"
        )
        self.assertTrue(
            vectors["exact-cancel-before-publish"]["requests"][-1]["holdForCancel"]
        )

    def test_stored_empty_mapping_field_presence_is_preserved(self):
        vector = next(
            v
            for v in self.suite["vectors"]
            if v["id"] == "stored-empty-mapping-field-preserves-presence"
        )
        row = vector["requests"][1]["reply"]["messages"][-1]
        self.assertEqual(row["encrypted_pii_mappings"], "")
        self.assertEqual(
            vector["expected_public_paging"]["piiMappingsByMessageId"],
            {row["client_message_id"]: []},
        )

    def test_rich_rows_preserve_exact_source_identity_time_and_nullable_metadata(self):
        vector = next(
            v for v in self.suite["vectors"] if v["id"] == "rich-authoritative-metadata"
        )
        meta = vector["expected_public_paging"]["messageMetadata"][-1]
        self.assertNotEqual(meta["id"], meta["storageId"])
        self.assertEqual(meta["id"], meta["clientMessageId"])
        self.assertEqual(meta["queueRevision"], 0)
        self.assertEqual(meta["keyVersion"], 0)
        self.assertIs(meta["hasThinking"], False)
        self.assertEqual(meta["senderName"], "")
        self.assertEqual(meta["modelName"], "Synthetic model")
        self.assertEqual(meta["rawStatus"], "queued")
        self.assertNotIn("displayStatus", meta)
        self.assertIsNone(meta["embedIds"])
        zero = next(
            v for v in self.suite["vectors"] if v["id"] == "zero-created-at-preserved"
        )
        self.assertEqual(
            zero["expected_public_paging"]["messageMetadata"][0]["createdAt"], 0
        )
        first = self.suite["vectors"][0]["expected_public_paging"]["chatMetadata"]
        self.assertIsNone(first["followUpSuggestions"])
        self.assertIsNone(first["createdAt"])

    def test_shared_one_page_budget_stops_before_additional_requests(self):
        vector = next(
            v
            for v in self.suite["vectors"]
            if v["id"] == "browser-one-page-underfilled-budget"
        )
        self.assertEqual(vector["options"], {"limit": 20, "maxPages": 1})
        self.assertEqual(len(vector["requests"]), 2)
        self.assertTrue(vector["expected_public_paging"]["hasMoreBefore"])
        self.assertEqual(len(vector["expected_messages"]), 8)

    def test_additive_rich_fields_preserve_all_original_34_assertions(self):
        # Fixed identity of the reviewed original34 vectors, independent of any
        # developer's private files or environment. Only additive DTO fields
        # may be removed when checking that the original assertions survive.
        import hashlib

        original = copy.deepcopy(self.suite["vectors"][:34])
        self.assertEqual(len(original), 34)
        # One reviewed IO-only correction: strict open_chat loads metadata once
        # before its four-page full-history loop, not once for each page. Rebuild
        # ONLY those three historical POST steps/count before checking the exact
        # historical34 hash; every output/error/data assertion and other33 vector
        # must still match the original baseline. Never blindly re-pin that hash.
        full = next(v for v in original if v["id"] == "bounded-30-keeps-full-65-cache")
        self.assertEqual(full["expected_metadata_requests"], 4)
        self.assertEqual(len(full["requests"]), 10)
        self.assertEqual(
            [step["method"] for step in full["requests"][:5]],
            ["POST", "GET", "GET", "GET", "GET"],
        )
        corrected = full["requests"]
        full["requests"] = [
            corrected[0],
            corrected[1],
            copy.deepcopy(corrected[0]),
            corrected[2],
            copy.deepcopy(corrected[0]),
            corrected[3],
            copy.deepcopy(corrected[0]),
            corrected[4],
            *corrected[5:],
        ]
        full["expected_metadata_requests"] = 7
        for after in original:
            for field in [
                "expected_public_paging",
                "preflight_expected",
                "exact_expected",
            ]:
                if field in after:
                    after[field].pop("chatMetadata", None)
                    after[field].pop("messageMetadata", None)
        encoded = json.dumps(original, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(
            hashlib.sha256(encoded).hexdigest(),
            "df3a8dad5912d38658cb2c6dcf3a85cb5d743286c6895b14822d71be6abc3011",
        )

    def test_projected_header_exact_and_one_over_bound_are_independent_of_raw_size(
        self,
    ):
        def compact(value):
            return len(
                json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
            )

        for identity, size, error in [
            ("projected-header-exact-limit", 262144, None),
            ("projected-header-one-over-limit", 262145, "protocol"),
        ]:
            vector = next(v for v in self.suite["vectors"] if v["id"] == identity)
            self.assertLessEqual(
                compact(vector["requests"][0]["reply"]["chats"][0]), 262144
            )
            self.assertEqual(
                compact(vector["expected_public_paging"]["chatMetadata"]), size
            )
            self.assertEqual(vector["expected_error"], error)

    def test_every_expected_dto_satisfies_the_shared_schema(self):
        for vector in self.suite["vectors"]:
            if vector["expected_error"] is not None:
                continue
            if vector["mode"] == "details":
                schema = {**self.schema, "oneOf": [{"$ref": "#/$defs/chatDetailsRead"}]}
                jsonschema.Draft202012Validator(schema).validate(
                    vector["expected_details"]
                )
                continue
            if vector["mode"] == "full":
                schema = {**self.schema, "oneOf": [{"$ref": "#/$defs/fullRead"}]}
                jsonschema.Draft202012Validator(schema).validate(
                    vector["full_expected"]
                )
                continue
            value = copy.deepcopy(vector["expected_public_paging"])
            value["chat"]["messages"] = copy.deepcopy(vector["expected_messages"])
            for field in ["startCursor", "endCursor", "oversizedMessageCursor"]:
                if value[field] is not None:
                    value[field]["scope"] = "0" * 64
            schema = {**self.schema, "oneOf": [{"$ref": "#/$defs/read"}]}
            jsonschema.Draft202012Validator(schema).validate(value)
            if vector.get("exact_expected"):
                schema = {**self.schema, "oneOf": [{"$ref": "#/$defs/exactResult"}]}
                jsonschema.Draft202012Validator(schema).validate(
                    vector["exact_expected"]
                )

    def test_shared_message_id_vectors_and_terminal_controls_match_schema(self):
        fixture = json.loads(
            (ROOT / "fixtures/message-id-compatibility.json").read_text()
        )
        self.assertFalse(fixture["policy"]["backend_universal_limit_claimed"])
        validator = jsonschema.Draft202012Validator(
            {**self.schema, "oneOf": [{"$ref": "#/$defs/messageId"}]}
        )
        for case in fixture["cases"]:
            self.assertEqual(
                validator.is_valid(case["value"]), case["valid"], case["id"]
            )
        # The maintained shared Rust grammar explicitly preserves these exact
        # opaque read bytes; transport suitability and authority are separate.
        for suffix in ("\n", "\r", "\u2028", "\u2029"):
            self.assertTrue(validator.is_valid("message" + suffix))
        for invalid in ("", None, 42, False, [], {}):
            self.assertFalse(validator.is_valid(invalid))
        self.assertEqual(
            self.schema["$defs"]["cursor"]["properties"]["chatId"]["format"], "uuid"
        )
        self.assertEqual(
            self.schema["$defs"]["read"]["properties"]["chat"]["properties"]["id"][
                "format"
            ],
            "uuid",
        )

    def test_opaque_read_vectors_keep_alias_preference_ciphertext_and_cursor_contract(
        self,
    ):
        vectors = [
            v for v in self.suite["vectors"] if v["id"].startswith("opaque-ids-")
        ]
        self.assertEqual(len(vectors), 11)
        key = base64.b64decode(self.suite["protocol"]["chat_key"])
        for identity in ("rust", "npm", "pip"):
            for vector in vectors:
                peer = self.peer(vector, identity)
                headers = {
                    "X-OpenMates-SDK": identity,
                    "Origin": self.suite["protocol"]["app_origin"],
                    "Cookie": "auth_refresh_token=" + self.suite["account"]["cookie"],
                }
                for step in peer.requests:
                    query = urlencode(step.get("query", {}), doseq=True)
                    code, reply = peer.plan(
                        step["method"],
                        step["path"] + ("?" + query if query else ""),
                        headers,
                        step.get("body"),
                    )
                    self.assertEqual(code, step.get("status", 200))
                    self.assertEqual(reply, planned_reply(step))
                self.assertEqual(peer.status()["consumed"], len(vector["requests"]))
                if vector["expected_error"] is not None:
                    self.assertEqual(vector["expected_error"], "protocol")
                    continue
                rows = {}
                for step in peer.requests:
                    reply = step.get("reply", {})
                    if not isinstance(reply, dict):
                        continue
                    for raw in reply.get("messages", []) + (
                        [reply["message"]]
                        if isinstance(reply.get("message"), dict)
                        else []
                    ):
                        row = json.loads(raw) if isinstance(raw, str) else raw
                        logical = (
                            row.get("client_message_id")
                            or row.get("message_id")
                            or row["id"]
                        )
                        self.assertNotEqual(row["id"], logical)
                        rows[logical] = row
                expected = vector["expected_messages"] + (
                    [vector["exact_expected"]["message"]]
                    if vector.get("exact_expected")
                    else []
                )
                for message in expected:
                    row = rows[message["id"]]
                    raw = base64.b64decode(row["encrypted_content"], validate=True)
                    self.assertEqual(
                        AESGCM(key).decrypt(raw[6:18], raw[18:], None).decode(),
                        message["content"],
                    )
                for field in ("startCursor", "endCursor", "oversizedMessageCursor"):
                    cursor = vector["expected_public_paging"].get(field)
                    if cursor is not None:
                        self.assertIn(cursor["messageId"], rows)

    def test_stored_and_page_local_expected_outputs_are_distinct(self):
        vectors = {v["id"]: v for v in self.suite["vectors"]}
        stored = vectors["stored-known-pii"]["expected_public_paging"]
        restored = vectors["page_local-known-pii"]["expected_public_paging"]
        self.assertEqual(
            stored["piiMappingsByMessageId"], restored["piiMappingsByMessageId"]
        )
        self.assertNotEqual(
            stored["chat"]["messages"][0]["content"],
            restored["chat"]["messages"][0]["content"],
        )
        unknown = vectors["page_local-unknown-pii"]["expected_public_paging"]
        self.assertIn(
            self.suite["protocol"]["unknown_placeholder"],
            unknown["chat"]["messages"][0]["content"],
        )


class StrictFullPreloadPlanTests(unittest.TestCase):
    setUpClass = classmethod(SavedChatReadPeerTests.setUpClass.__func__)
    peer = SavedChatReadPeerTests.peer

    # The original tests remain the shared fixture/guard contract. These cases
    # drive the real pure peer with the public full reader's independent cursor
    # sequence; no socket, SDK/product process, profile or conformance execution.
    def test_strict_full_preload_has_one_metadata_then_four_windows_for_all_sdk_identities(
        self,
    ):
        from urllib.parse import urlencode

        vector = next(
            v
            for v in self.suite["vectors"]
            if v["id"] == "bounded-30-keeps-full-65-cache"
        )
        chat = self.suite["protocol"]["chat_id"]
        for identity in ("rust", "npm", "pip"):
            peer = self.peer(copy.deepcopy(vector), identity)
            headers = {
                "X-OpenMates-SDK": identity,
                "Origin": self.suite["protocol"]["app_origin"],
                "Cookie": "auth_refresh_token=" + self.suite["account"]["cookie"],
            }
            code, metadata = peer.plan(
                "POST", "/v1/chats/metadata/batch", headers, {"chat_ids": [chat]}
            )
            self.assertEqual(code, 200)
            self.assertEqual(metadata["chats"][0]["id"], chat)
            cursor = None
            full = []
            seen = set()
            pages = 0
            while True:
                query = {
                    "direction": "latest" if cursor is None else "before",
                    "limit": "100",
                    "respect_compression_boundary": "false",
                }
                if cursor is not None:
                    query.update(
                        before_timestamp=str(cursor["created_at"]),
                        before_message_id=cursor["message_id"],
                    )
                code, page = peer.plan(
                    "GET",
                    f"/v1/chats/{chat}/messages/window?" + urlencode(query),
                    headers,
                )
                self.assertEqual(code, 200)
                pages += 1
                for row in page["messages"]:
                    self.assertNotIn(row["client_message_id"], seen)
                    seen.add(row["client_message_id"])
                full = page["messages"] + full
                if not page["has_more_before"]:
                    break
                cursor = page["start_cursor"]
                self.assertLess(pages, 5)
            self.assertEqual(pages, 4)
            self.assertEqual(len(full), 65)
            self.assertEqual(
                [row["client_message_id"] for row in full],
                [row["id"] for row in vector["expected_cached_messages"]],
            )
            key = base64.b64decode(self.suite["protocol"]["chat_key"])
            for row, expected in zip(full, vector["expected_cached_messages"]):
                raw = base64.b64decode(row["encrypted_content"], validate=True)
                self.assertEqual(
                    AESGCM(key).decrypt(raw[6:18], raw[18:], None).decode(),
                    expected["content"],
                )
                self.assertEqual(row["role"], expected["role"])
            self.assertEqual(peer.status()["metadata"], 1)
            self.assertEqual(peer.status()["window"], 4)
            self.assertEqual(peer.status()["consumed"], 5)
            # Only the bounded operation refreshes metadata for each page. Follow
            # its independent20/10 plan, then the final canonical503 fallback.
            bounded = []
            for limit, direction in [(20, "latest"), (10, "before")]:
                self.assertEqual(
                    peer.plan(
                        "POST",
                        "/v1/chats/metadata/batch",
                        headers,
                        {"chat_ids": [chat]},
                    )[0],
                    200,
                )
                query = {
                    "direction": direction,
                    "limit": str(limit),
                    "respect_compression_boundary": "true",
                }
                if direction == "before":
                    query.update(
                        before_timestamp=str(cursor["created_at"]),
                        before_message_id=cursor["message_id"],
                    )
                code, page = peer.plan(
                    "GET",
                    f"/v1/chats/{chat}/messages/window?" + urlencode(query),
                    headers,
                )
                self.assertEqual(code, 200)
                self.assertLessEqual(len(page["messages"]), limit)
                bounded = page["messages"] + bounded
                cursor = page["start_cursor"]
            self.assertEqual(
                [row["client_message_id"] for row in bounded],
                [row["id"] for row in vector["expected_messages"]],
            )
            self.assertEqual(len(bounded), 30)
            self.assertEqual(len(full), 65)
            self.assertEqual(
                peer.plan(
                    "POST", "/v1/chats/metadata/batch", headers, {"chat_ids": [chat]}
                )[0],
                503,
            )
            report = peer.status()
            self.assertEqual(report["metadata"], 4)
            self.assertEqual(report["window"], 6)
            self.assertEqual(report["exact"], 0)
            self.assertEqual(report["consumed"], 10)
            self.assertIsNone(report["failure"])
            self.assertEqual(len(vector["expected_messages"]), 30)
            self.assertEqual(len(vector["expected_cached_messages"]), 65)

    def test_strict_preload_rejects_missing_initial_metadata_and_spurious_between_page_metadata(
        self,
    ):
        from urllib.parse import urlencode

        vector = next(
            v
            for v in self.suite["vectors"]
            if v["id"] == "bounded-30-keeps-full-65-cache"
        )
        chat = self.suite["protocol"]["chat_id"]
        headers = {
            "X-OpenMates-SDK": "rust",
            "Origin": self.suite["protocol"]["app_origin"],
            "Cookie": "auth_refresh_token=" + self.suite["account"]["cookie"],
        }
        target = f"/v1/chats/{chat}/messages/window?" + urlencode(
            {
                "direction": "latest",
                "limit": 100,
                "respect_compression_boundary": "false",
            }
        )
        peer = self.peer(copy.deepcopy(vector))
        with self.assertRaisesRegex(AssertionError, "exact route order"):
            peer.plan("GET", target, headers)
        self.assertEqual(peer.status()["consumed"], 0)
        peer.plan("POST", "/v1/chats/metadata/batch", headers, {"chat_ids": [chat]})
        peer.plan("GET", target, headers)
        with self.assertRaisesRegex(AssertionError, "exact route order"):
            peer.plan("POST", "/v1/chats/metadata/batch", headers, {"chat_ids": [chat]})
        self.assertEqual(peer.status()["consumed"], 2)
        self.assertEqual(peer.status()["metadata"], 1)

    def test_full_chat_extension_preserves_all_original_66_vectors(self):
        import hashlib

        encoded = json.dumps(
            self.suite["vectors"][:66], sort_keys=True, separators=(",", ":")
        ).encode()
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), ORIGINAL66_SHA256)
        self.assertEqual(len(self.suite["vectors"][:74]), 74)
        self.assertTrue(all(v["mode"] == "full" for v in self.suite["vectors"][66:74]))

    def test_full_chat_shared_five_reuse_exact_legacy_ciphertext_and_om_wrapping(self):
        shared = json.loads(
            (
                ROOT.parents[1]
                / "packages/openmates-rust/tests/fixtures/full-chat-read-metadata.json"
            ).read_text()
        )
        cases = self.suite["vectors"][66:71]
        self.assertEqual(len(shared["vectors"]), 5)
        key = bytes.fromhex(shared["chatKeyHex"])
        master = base64.b64decode(self.suite["account"]["master_key"])
        for case, source in zip(cases, shared["vectors"]):
            self.assertEqual(case["id"], "full-chat-" + source["id"])
            self.assertEqual(case["full_expected"], source["expected"])
            row = case["requests"][0]["reply"]["chats"][0]
            self.assertEqual("encrypted_slug" in row, source["present"])
            if source["present"]:
                self.assertEqual(row["encrypted_slug"], source["encryptedSlug"])
            raw = base64.b64decode(row["encrypted_chat_key"], validate=True)
            self.assertEqual(raw[:2], b"OM")
            self.assertEqual(AESGCM(master).decrypt(raw[6:18], raw[18:], None), key)
            for field, expected in [
                ("encrypted_title", shared["chat"]["title"]),
                ("encrypted_category", shared["chat"]["category"]),
            ]:
                raw = base64.b64decode(row[field], validate=True)
                self.assertEqual(
                    AESGCM(key).decrypt(raw[6:18], raw[18:], None).decode(), expected
                )
            if source["encryptedSlug"]:
                raw = base64.b64decode(source["encryptedSlug"], validate=True)
                self.assertEqual(
                    AESGCM(key).decrypt(raw[:12], raw[12:], None).decode(),
                    source["expected"]["slug"],
                )
        self.assertEqual(
            [v["foreign_final"] for v in cases],
            ["permitted", "cancel", "owner", "successor", "discard"],
        )

    def test_full_chat_closed_request_counts_cover_each_actual_sdk_without_io(self):
        for vector in self.suite["vectors"][66:74]:
            for identity in ("rust", "npm", "pip"):
                peer = self.peer(vector, identity)
                headers = {
                    "X-OpenMates-SDK": identity,
                    "Origin": self.suite["protocol"]["app_origin"],
                    "Cookie": "auth_refresh_token=" + self.suite["account"]["cookie"],
                }
                for step in peer.requests:
                    query = urlencode(step.get("query", {}), doseq=True)
                    code, value = peer.plan(
                        step["method"],
                        step["path"] + ("?" + query if query else ""),
                        headers,
                        step.get("body"),
                    )
                    self.assertEqual(code, 200)
                    self.assertEqual(value, planned_reply(step))
                counts = vector.get("expected_counts_by_language", {}).get(identity, {})
                report = peer.status()
                self.assertEqual(report["consumed"], len(peer.requests))
                self.assertEqual(
                    report["metadata"],
                    counts.get("metadata", vector["expected_metadata_requests"]),
                )
                self.assertEqual(
                    report["window"],
                    counts.get("window", vector["expected_window_requests"]),
                )
                self.assertEqual(report["exact"], 0)
                self.assertIsNone(peer.server)
                self.assertIsNone(report["failure"])

    def test_full_optional_slug_schema_refuses_null_or_extra_fields(self):
        validator = jsonschema.Draft202012Validator(
            {**self.schema, "oneOf": [{"$ref": "#/$defs/fullRead"}]}
        )
        empty = copy.deepcopy(self.suite["vectors"][67]["full_expected"])
        self.assertEqual(empty["slug"], "")
        validator.validate(empty)
        for value in [None, 42, False, []]:
            invalid = {**empty, "slug": value}
            self.assertTrue(list(validator.iter_errors(invalid)))
        self.assertTrue(list(validator.iter_errors({**empty, "fresh": True})))

    def test_full_error_and_cancel_inputs_are_real_not_relabeled_success(self):
        from cryptography.exceptions import InvalidTag

        shared = json.loads(
            (
                ROOT.parents[1]
                / "packages/openmates-rust/tests/fixtures/full-chat-read-metadata.json"
            ).read_text()
        )
        damaged = self.suite["vectors"][71]
        raw = base64.b64decode(
            damaged["requests"][0]["reply"]["chats"][0]["encrypted_slug"]
        )
        with self.assertRaises(InvalidTag):
            AESGCM(bytes.fromhex(shared["chatKeyHex"])).decrypt(
                raw[:12], raw[12:], None
            )
        self.assertEqual(damaged["expected_error"], "crypto")
        noauth = self.suite["vectors"][72]
        self.assertEqual(noauth["expected_error"], "authentication")
        self.assertEqual(noauth["requests"], [])
        cancel = self.suite["vectors"][73]
        self.assertEqual(cancel["expected_error"], "cancelled")
        self.assertEqual(len(cancel["requests"]), 1)
        self.assertIs(cancel["requests"][0]["holdForCancel"], True)

    def test_opaque_read_id_alignment_keeps_chat_scope_options_and_size_guards(self):
        validator = jsonschema.Draft202012Validator(
            self.schema, format_checker=jsonschema.FormatChecker()
        )
        cursor = {
            "chatId": self.suite["protocol"]["chat_id"],
            "scope": "a" * 64,
            "createdAt": 1,
            "messageId": "opaque \n雪",
        }
        validator.validate({"before": cursor})
        for field, value in [
            ("chatId", "opaque \n雪"),
            ("scope", "a" * 63),
            ("createdAt", -1),
            ("messageId", ""),
            ("messageId", None),
            ("messageId", 42),
        ]:
            invalid = {**cursor, field: value}
            self.assertTrue(list(validator.iter_errors({"before": invalid})))
        for invalid in [
            {"limit": 0},
            {"limit": 101},
            {"maxPages": 0},
            {"maxPages": 6},
            {"all": True},
            {"before": cursor, "after": cursor},
        ]:
            self.assertTrue(list(validator.iter_errors(invalid)))
        # ID grammar neither raises whole-row/page budgets nor grants a scope.
        self.assertEqual(
            self.schema["$defs"]["read"]["properties"]["payloadBytes"]["maximum"],
            1310720,
        )
        self.assertEqual(
            self.schema["$defs"]["exactResult"]["properties"]["payloadBytes"][
                "maximum"
            ],
            2097152,
        )
        self.assertEqual(
            self.schema["$defs"]["options"]["properties"]["limit"]["maximum"], 100
        )

    def test_details_preserve_all_reviewed74_vector_objects_and_old_schema(self):
        import hashlib

        encoded = json.dumps(
            self.suite["vectors"][:74],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        self.assertEqual(
            hashlib.sha256(encoded).hexdigest(),
            "234a848818af9d3f4692f68060213ac751945c820812b95624a50daf8e736928",
        )
        self.assertEqual(len(self.suite["vectors"]), 103)
        self.assertTrue(all(v["mode"] == "details" for v in self.suite["vectors"][74:]))

    def test_details_all_three_closed_plans_and_real_final_release_cases(self):
        for vector in self.suite["vectors"][74:]:
            for identity in ("rust", "npm", "pip"):
                peer = self.peer(vector, identity)
                headers = {
                    "X-OpenMates-SDK": identity,
                    "Origin": self.suite["protocol"]["app_origin"],
                    "Cookie": "auth_refresh_token=" + self.suite["account"]["cookie"],
                }
                for step in peer.requests:
                    query = urlencode(step.get("query", {}), doseq=True)
                    code, value = peer.plan(
                        step["method"],
                        step["path"] + ("?" + query if query else ""),
                        headers,
                        step.get("body"),
                    )
                    self.assertEqual(code, 200)
                    self.assertEqual(value, planned_reply(step))
                counts = vector.get("expected_counts_by_language", {}).get(identity, {})
                status = peer.status()
                self.assertEqual(status["consumed"], len(peer.requests))
                for field, expected in [
                    ("metadata", "expected_metadata_requests"),
                    ("window", "expected_window_requests"),
                    ("exact", "expected_exact_requests"),
                    ("details_embeds", "expected_embed_requests"),
                ]:
                    self.assertEqual(status[field], counts.get(field, vector[expected]))
                self.assertIsNone(peer.server)
                self.assertIsNone(status["failure"])
        cases = [v for v in self.suite["vectors"][74:] if "foreign_final" in v]
        self.assertEqual(
            [v["foreign_final"] for v in cases],
            ["permitted", "cancel", "owner", "successor"],
        )
        self.assertTrue(cases[-1]["requests"][-4]["holdForSuccessor"])

    def test_details_latest_is_one_window_and_full_drains_without_compression(self):
        vectors = {v["id"]: v for v in self.suite["vectors"][74:]}
        latest = vectors["details-latest-request30-one-server20-window"]
        self.assertEqual(latest["expected_window_requests"], 1)
        self.assertEqual(len(latest["expected_details"]["messages"]), 20)
        self.assertEqual(
            latest["requests"][1]["query"],
            {
                "direction": ["latest"],
                "limit": ["30"],
                "respect_compression_boundary": ["true"],
            },
        )
        full = vectors["details-full65-four-server20-windows"]
        self.assertEqual(full["expected_window_requests"], 4)
        self.assertEqual(len(full["expected_details"]["messages"]), 65)
        self.assertNotIn("has_more_before", full["expected_details"])
        self.assertTrue(
            all(
                r["query"]["respect_compression_boundary"] == ["false"]
                for r in full["requests"]
                if "/messages/window" in r["path"]
            )
        )
        alternate = vectors["details-latest-accepts-alternate-server-cap30"]
        self.assertEqual(alternate["expected_window_requests"], 1)
        self.assertEqual(len(alternate["expected_details"]["messages"]), 30)

    def test_details_independent_aes_fields_source_numbers_and_raw_pii_presence(self):
        vector = self.suite["vectors"][75]
        row = vector["requests"][0]["reply"]["chats"][0]
        expected = vector["expected_details"]
        master = base64.b64decode(self.suite["account"]["master_key"])
        key = base64.b64decode(self.suite["protocol"]["chat_key"])

        def decrypt(value, key):
            raw = base64.b64decode(value, validate=True)
            self.assertEqual(raw[:2], b"OM")
            return AESGCM(key).decrypt(raw[6:18], raw[18:], None)

        self.assertEqual(decrypt(row["encrypted_chat_key"], master), key)
        for plain, wire in [
            ("title", "encrypted_title"),
            ("summary", "encrypted_chat_summary"),
            ("slug", "encrypted_slug"),
            ("category", "encrypted_category"),
        ]:
            self.assertEqual(decrypt(row[wire], key).decode(), expected["chat"][plain])
        self.assertEqual(
            decrypt(row["encrypted_draft_md"], master).decode(),
            expected["chat"]["draftPreview"],
        )
        self.assertIs(type(row["created_at"]), str)
        self.assertIs(type(row["read_details"]["created_at"]), int)
        wire = {
            r["client_message_id"]: r
            for request in vector["requests"]
            if "/messages/window" in request["path"]
            for r in request["reply"]["messages"]
        }
        for message in expected["messages"]:
            r = wire[message["clientMessageId"]]
            self.assertEqual(
                decrypt(r["encrypted_content"], key).decode(), message["content"]
            )
            for plain, field in [
                ("senderName", "encrypted_sender_name"),
                ("category", "encrypted_category"),
                ("modelName", "encrypted_model_name"),
            ]:
                if message[plain] is None:
                    self.assertNotIn(field, r)
                else:
                    self.assertEqual(decrypt(r[field], key).decode(), message[plain])
            self.assertEqual("encrypted_pii_mappings" in r, "piiMappings" in message)
            if "piiMappings" in message:
                self.assertEqual(
                    json.loads(decrypt(r["encrypted_pii_mappings"], key)),
                    message["piiMappings"],
                )

    def test_details_team_uses_team_chat_wrapper_but_master_draft(self):
        vector = self.suite["vectors"][76]
        row = vector["requests"][0]["reply"]["chats"][0]
        master = base64.b64decode(self.suite["account"]["master_key"])
        key = base64.b64decode(self.suite["protocol"]["chat_key"])

        def decrypt(value, key):
            raw = base64.b64decode(value)
            return AESGCM(key).decrypt(raw[6:18], raw[18:], None)

        tk = decrypt(
            vector["requests"][1]["reply"]["team"]["encrypted_team_key"], master
        )
        self.assertEqual(
            decrypt(row["chat_key_wrappers"][0]["encrypted_chat_key"], tk), key
        )
        self.assertEqual(
            decrypt(row["encrypted_draft_md"], master).decode(), "Saved synthetic draft"
        )
        self.assertEqual(
            vector["requests"][0]["query"], {"team_id": [vector["team_id"]]}
        )

    def test_details_options_closed_and_field_absence_guards(self):
        options = jsonschema.Draft202012Validator(
            {**self.schema, "oneOf": [{"$ref": "#/$defs/chatDetailsOptions"}]}
        )
        output = jsonschema.Draft202012Validator(
            {**self.schema, "oneOf": [{"$ref": "#/$defs/chatDetailsRead"}]}
        )
        for vector in self.suite["vectors"][74:]:
            self.assertEqual(
                bool(list(options.iter_errors(vector["details_options"]))),
                vector["id"] == "details-invalid-limit-before-io",
            )
        good = copy.deepcopy(self.suite["vectors"][74]["expected_details"])
        output.validate(good)
        for field in ("chat", "messages", "follow_up_suggestions"):
            bad = copy.deepcopy(good)
            del bad[field]
            self.assertTrue(list(output.iter_errors(bad)))
        bad = copy.deepcopy(good)
        bad["chat"]["participantUserHashes"] = None
        self.assertTrue(list(output.iter_errors(bad)))
        for raw in (None, {"synthetic": "object"}, 3, [], [None, 3]):
            valid = copy.deepcopy(good)
            valid["messages"][0]["piiMappings"] = raw
            output.validate(valid)

    def test_details_utf16_fixture_requires_exact_lead_surrogate_without_value_roundtrip(
        self,
    ):
        vector = next(
            v
            for v in self.suite["vectors"]
            if v["id"] == "details-utf16-preview-split-is-lossless"
        )
        self.assertEqual(vector["expected_draft_utf16"], [97] * 199 + [0xD83D])
        self.assertIsNone(vector["expected_details"]["chat"]["draftPreview"])
        raw = base64.b64decode(
            vector["requests"][0]["reply"]["chats"][0]["encrypted_draft_md"]
        )
        master = base64.b64decode(self.suite["account"]["master_key"])
        text = AESGCM(master).decrypt(raw[6:18], raw[18:], None).decode()
        units = text.encode("utf-16-le")[:400]
        self.assertEqual(
            [
                int.from_bytes(units[i : i + 2], "little")
                for i in range(0, len(units), 2)
            ],
            vector["expected_draft_utf16"],
        )

    def test_details_optional_focus_is_fresh_encrypted_metadata_without_new_io(self):
        from cryptography.exceptions import InvalidTag

        key = base64.b64decode(self.suite["protocol"]["chat_key"])
        cases = [
            v
            for v in self.suite["vectors"]
            if v["id"].startswith("details-active-focus-")
        ]
        self.assertEqual(
            [v["id"] for v in cases],
            [
                "details-active-focus-nonempty",
                "details-active-focus-empty",
                "details-active-focus-corrupt",
            ],
        )
        for vector in cases:
            self.assertEqual(len(vector["requests"]), 3)
            self.assertEqual(vector["expected_metadata_requests"], 1)
            raw = base64.b64decode(
                vector["requests"][0]["reply"]["chats"][0]["encrypted_active_focus_id"]
            )
            if vector["id"].endswith("corrupt"):
                with self.assertRaises(InvalidTag):
                    AESGCM(key).decrypt(raw[6:18], raw[18:], None)
            else:
                plain = AESGCM(key).decrypt(raw[6:18], raw[18:], None).decode()
                self.assertEqual(
                    plain,
                    ""
                    if vector["id"] == "details-active-focus-empty"
                    else "focus-synthetic-selected",
                )
            self.assertEqual(
                "activeFocusId" in vector["expected_details"]["chat"],
                vector["id"].endswith("nonempty"),
            )
        self.assertNotIn(
            "encrypted_active_focus_id",
            self.suite["vectors"][74]["requests"][0]["reply"]["chats"][0],
        )
        self.assertNotIn(
            "activeFocusId", self.suite["vectors"][74]["expected_details"]["chat"]
        )

    def test_js_json_extension_preserves_all98_objects_and_raw_typed_numbers(self):
        import hashlib

        old = copy.deepcopy(self.suite["vectors"][:98])
        # Vector 77 (details-team-empty-one-window) once expected personal-chat
        # metadata its own team reply never carries. Its corrected expectation
        # is exactly the reply-derived projection; the original 98 objects are
        # otherwise byte-identical, so the pin hashes the original value.
        team = old[77]
        self.assertEqual(team["id"], "details-team-empty-one-window")
        corrected = {
            "createdAt": None,
            "updatedAt": None,
            "category": None,
            "mateName": None,
            "metadataUpdatedAt": 0,
        }
        chat = team["expected_details"]["chat"]
        self.assertEqual({key: chat[key] for key in corrected}, corrected)
        self.assertNotIn("created_at", team["requests"][0]["reply"]["chats"][0])
        chat.update(
            createdAt=1700000000,
            updatedAt=1700000200,
            category="general",
            metadataUpdatedAt=1700000201,
        )
        # Vectors 91-94 (details foreign-final) once planned a second fresh
        # read. The shared core now answers every later read of the same chat
        # with a cached tail delta (direction=after) that misses here, because
        # the cached 20 rows cannot fill limit 30, and then reads fresh. The
        # pin hashes the original plan: drop each delta step, restore the fresh
        # window to its slot and undo the added window counts.
        for vector in old[91:95]:
            self.assertEqual(vector["mode"], "details")
            self.assertIn("foreign_final", vector)
            requests, original, deltas = vector["requests"], [], 0
            for index, step in enumerate(requests):
                if step.get("query", {}).get("direction") == ["after"]:
                    self.assertEqual(step["reply"]["messages"], [])
                    original.append(requests[index + 2])
                    deltas += 1
                elif index >= 2 and requests[index - 2].get("query", {}).get(
                    "direction"
                ) == ["after"]:
                    continue
                else:
                    original.append(step)
            vector["requests"] = original
            vector["expected_window_requests"] -= deltas
            if vector["foreign_final"] == "successor":
                self.assertEqual(
                    vector.pop("cancel_expected_counts"), {"metadata": 3, "window": 3}
                )
        self.assertEqual(
            hashlib.sha256(
                json.dumps(
                    old, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest(),
            "2e6353ccb071eb791218fdc78b83d76f2c045dca87e1c84e00c7ee74e027d67e",
        )
        self.assertEqual(len(self.suite["vectors"]), 103)
        self.assertTrue(all(v["mode"] == "details" for v in self.suite["vectors"][98:]))
        self.assertEqual(
            len([v for v in self.suite["vectors"][98:] if "semantic_pii" in v]), 4
        )

    def test_js_json_oracle_is_independently_encrypted_and_never_frontend_normalized(
        self,
    ):
        key = base64.b64decode(self.suite["protocol"]["chat_key"])
        for vector in self.suite["vectors"][98:]:
            row = vector["requests"][1]["reply"]["messages"][0]
            raw = base64.b64decode(row["encrypted_pii_mappings"])
            source = vector.get("semantic_pii", {}).get(
                "source_json", vector.get("bounded_pii_source_json")
            )
            self.assertEqual(
                AESGCM(key).decrypt(raw[6:18], raw[18:], None).decode(), source
            )
            self.assertEqual(vector["expected_metadata_requests"], 1)
            self.assertEqual(vector["expected_window_requests"], 1)
            self.assertTrue(vector["requests"][0]["body"]["include_read_details"])
            if "semantic_pii" in vector:
                self.assertEqual(len(vector["requests"]), 3)
                self.assertIsNone(
                    vector["expected_details"]["messages"][0]["piiMappings"]
                )
                self.assertNotEqual(
                    vector["semantic_pii"]["source_json"],
                    vector["semantic_pii"]["sdk_json"],
                )
            else:
                self.assertEqual(source, "[" * 129 + "0" + "]" * 129)
                self.assertEqual(vector["expected_error"], "protocol")
                self.assertEqual(len(vector["requests"]), 2)

    def test_js_json_static_source_oracles_distinguish_cli_and_sdk_without_an_engine(
        self,
    ):
        import math

        cases = {
            v["id"]: v["semantic_pii"]
            for v in self.suite["vectors"][98:]
            if "semantic_pii" in v
        }
        main = cases["details-js-json-numbers-and-last-duplicate"]
        self.assertEqual(
            main["source_json"],
            '[9007199254740993,1e400,-0,{"k":"discarded","k":"kept"}]',
        )
        self.assertEqual(main["cli_json"], '[9007199254740992,null,0,{"k":"kept"}]')
        self.assertEqual(
            main["sdk_json"], '[9007199254740992.0,1e400,-0.0,{"k":"kept"}]'
        )
        # These parse only the independently authored wire expectations. They do
        # not compute a JS oracle or run any product/Node/Rust operation.
        sdk = json.loads(main["sdk_json"])
        cli = json.loads(main["cli_json"])
        self.assertEqual(sdk[0], 9007199254740992)
        self.assertTrue(math.isinf(sdk[1]))
        self.assertLess(math.copysign(1.0, sdk[2]), 0)
        self.assertIsNone(cli[1])
        self.assertEqual(cli[2], 0)
        self.assertEqual(sdk[3], {"k": "kept"})
        finite = cases["details-js-json-finite-layout-overflow-underflow"]
        raw_sdk = json.loads(finite["sdk_json"])
        raw_cli = json.loads(finite["cli_json"])
        self.assertIs(type(raw_sdk[4]), float)
        self.assertEqual(int(raw_sdk[4]), 1000000000000000128)
        self.assertEqual(raw_cli[4], 1000000000000000100)
        keys = cases["details-js-json-escaped-equivalent-index-keys"]
        self.assertEqual(list(json.loads(keys["sdk_json"])), ["0", "1", "2", "a"])
        utf16 = cases["details-js-json-lone-utf16-keys-and-values"]
        value = json.loads(utf16["sdk_json"])

        def units(value):
            encoded = value.encode("utf-16-le", "surrogatepass")
            return [
                int.from_bytes(encoded[i : i + 2], "little")
                for i in range(0, len(encoded), 2)
            ]

        self.assertEqual(
            [units(key) for key in value],
            [[0xD83D], [0xD83D, 0xDE00], [108, 105, 116, 101, 114, 97, 108]],
        )
        self.assertEqual(units(next(iter(value.values()))), [0xDC00])
        self.assertEqual(list(value.values())[1], "kept")


if __name__ == "__main__":
    unittest.main()
