"""Pure wire-format and passive-monitor guards for the shared SDK peer.

Exercise actual peer methods with bounded in-memory transport doubles only.
Offer canonical-shaped pending Task, workflow and typed replay discoveries.
Reject capability escalation and every non-read monitor client frame.
Require pending offers to be delivered before a successful monitor receipt.
Lease regressions retain their original UTC, generation and sealing checks.
Never bind a listener, launch an SDK or send a product/network request.
"""
# contract-test-file: tooling

import ast
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import essential_session_server as essential


NOW = datetime(2026, 12, 31, 23, 59, 59, 987654, tzinfo=timezone.utc)


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz != timezone.utc:
            raise AssertionError("Lease fixtures must use explicit UTC")
        return NOW


class RecordingSocket:
    def __init__(self):
        self.frames = []

    def send(self, kind, payload):
        self.frames.append((kind, payload))


class EssentialLeaseTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(essential.__file__).with_name("fixtures") / (
            "session-foreground-completion-recovery.json"
        )
        self.suite = json.loads(fixture.read_text())["capabilities"][essential.RECOVERY]

    def peer(self, mode="main", identity="rust"):
        # Preserve the real constructor, key derivation, sealed payload and
        # claim validators; replace only its unused HTTP listener. These tests
        # do not bind sockets, start threads or perform SDK/product requests.
        with patch("recovery_server.ThreadingHTTPServer"):
            return essential.EssentialPeer(self.suite, {"mode": mode}, identity)

    def claim(self, peer, **overrides):
        socket = RecordingSocket()
        payload = {
            "protocol_version": 1,
            "job_id": self.suite["protocol"]["job_id"],
            "request_id": "synthetic-lease-request",
            **overrides,
        }
        with patch.object(essential, "datetime", FrozenDatetime):
            peer.claim(socket, payload)
        return socket.frames

    def test_utc_milliseconds_preserve_normal_and_expiry_lease_durations(self):
        for identity in ("rust", "npm", "pip"):
            for mode, seconds in (("main", 60), ("main_expiry", 1)):
                with self.subTest(identity=identity, mode=mode):
                    peer = self.peer(mode, identity)
                    frames = self.claim(peer)
                    self.assertEqual(len(frames), 1)
                    kind, payload = frames[0]
                    self.assertEqual(kind, "recovery_job_claimed")
                    stamp = payload["lease_expires_at"]
                    self.assertRegex(
                        stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
                    )
                    self.assertEqual(len(stamp), 24)
                    expected = NOW.replace(microsecond=987000) + timedelta(
                        seconds=seconds
                    )
                    self.assertEqual(
                        datetime.fromisoformat(stamp.replace("Z", "+00:00")), expected
                    )
                    self.assertEqual(payload["state"], "LEASED")
                    self.assertEqual(
                        payload["lease_token"], self.suite["protocol"]["lease_token"]
                    )
                    self.assertEqual(payload["lease_generation"], 7)
                    self.assertEqual(peer.counts["claims"], 1)
                    self.assertEqual(peer.counts["persists"], 0)
                    self.assertNotIn(
                        self.suite["protocol"]["sealed_content"],
                        payload["sealed_payload"],
                    )

    def test_terminal_and_cancelled_claims_do_not_gain_lease_authority(self):
        peer = self.peer()
        peer.terminal = True
        frames = self.claim(peer)
        self.assertEqual(frames[0][1]["state"], "TERMINAL")
        for field in (
            "lease_token",
            "lease_generation",
            "lease_expires_at",
            "sealed_payload",
        ):
            self.assertNotIn(field, frames[0][1])
        cancelled = self.peer("main_cancel")
        self.assertEqual(self.claim(cancelled), [])
        self.assertEqual(cancelled.counts["persists"], 0)

    def test_invalid_claim_protocol_and_job_remain_refused(self):
        for invalid in ({"protocol_version": 2}, {"job_id": "foreign-synthetic-job"}):
            with self.subTest(invalid=invalid):
                peer = self.peer()
                with self.assertRaises(AssertionError):
                    self.claim(peer, **invalid)
                self.assertEqual(peer.counts["persists"], 0)
                self.assertNotIn("foreground-exact-claim", peer.checks)


class PassiveMonitorPeerTests(unittest.TestCase):
    def peer(self, identity="rust", mode="monitor"):
        fixture = (
            Path(essential.__file__).with_name("fixtures")
            / "session-chat-change-monitor.json"
        )
        suite = json.loads(fixture.read_text())["capabilities"][essential.MONITOR]
        with patch("recovery_server.ThreadingHTTPServer"):
            return essential.EssentialPeer(suite, {"mode": mode}, identity)

    def socket(self, *events):
        socket = RecordingSocket()
        socket.handler = SimpleNamespace(
            connection=SimpleNamespace(settimeout=lambda _: None)
        )
        socket.raw = lambda *_: None
        sequence = iter(events)
        socket.receive = lambda: next(sequence, None)
        return socket

    def event(self, kind, payload=None):
        return {"type": kind, "payload": payload or {}}

    def test_all_three_adapters_receive_pending_work_before_sync_completion_without_side_effects(
        self,
    ):
        for identity in ("rust", "npm", "pip"):
            with self.subTest(identity=identity):
                peer = self.peer(identity)
                socket = self.socket(
                    self.event(
                        "native_client_lifecycle",
                        {
                            "client_type": identity,
                            "interactive": False,
                            "is_foreground": False,
                        },
                    ),
                    self.event("phased_sync_request", {"phase": "all"}),
                )
                peer.websocket(socket)
                kinds = [kind for kind, _ in socket.frames]
                offers = dict(peer.pending_monitor_offers())
                for kind, payload in offers.items():
                    self.assertIn((kind, payload), socket.frames)
                    self.assertLess(
                        kinds.index(kind), kinds.index("phased_sync_complete")
                    )
                status = peer.status()
                self.assertIsNone(status["failure"])
                self.assertEqual(status["passive_pending_offer_batches"], 1)
                self.assertEqual(status["passive_side_effect_attempts"], 0)
                self.assertEqual(status["claims"], 0)
                self.assertEqual(status["persists"], 0)
                self.assertEqual(status["admissions"], 0)
                self.assertIn("strict-canonical-sync", status["checks"])
                self.assertIn("passive-pending-offers-delivered", status["checks"])

    def test_every_monitor_mode_keeps_all_sockets_without_task_or_completion_capability(
        self,
    ):
        class Parent:
            def do_GET(self):
                self.delegated = True

        fixture = (
            Path(essential.__file__).with_name("fixtures")
            / "session-chat-change-monitor.json"
        )
        suite = json.loads(fixture.read_text())["capabilities"][essential.MONITOR]
        for vector in suite["vectors"]:
            peer = self.peer(mode=vector["mode"])
            with patch("recovery_server.RecoveryPeer.handler", return_value=Parent):
                handler_type = peer.handler()
            for connection in range(2):
                for extra in ("task_update_jobs", "chat_metadata_recovery"):
                    with self.subTest(
                        vector=vector["id"], connection=connection, capability=extra
                    ):
                        handler = object.__new__(handler_type)
                        handler.path = (
                            "/v1/ws?client_capabilities=typed_recovery_outputs_v2,"
                            + extra
                        )
                        handler.delegated = False
                        with self.assertRaises(AssertionError):
                            handler.do_GET()
                        self.assertFalse(handler.delegated)
                handler = object.__new__(handler_type)
                handler.path = "/v1/ws?client_capabilities=typed_recovery_outputs_v2"
                handler.do_GET()
                self.assertTrue(handler.delegated)

    def test_only_existing_advance_cas_intent_admits_one_exact_foreground_read(self):
        base = [
            "canonical_embed_receipts_v1",
            "typed_recovery_outputs_v2",
            "agentic-storage-v2",
            "chat_sync_feed_v1",
        ]
        capable = base + ["task_update_jobs"]
        for mode in ("monitor_cas", "monitor_data_changed"):
            with self.subTest(mode=mode):
                peer = self.peer(mode=mode)
                with self.assertRaises(AssertionError):
                    peer.admit_monitor_socket(capable)
                peer.control("advance")
                # Passive sockets cannot consume the deliberate foreground intent.
                self.assertFalse(peer.admit_monitor_socket(base))
                self.assertEqual(peer.ordinary_read_budget, 1)
                for invalid in (
                    capable + ["foreign"],
                    capable + ["chat_metadata_recovery"],
                    capable[:-2] + ["task_update_jobs"],
                    capable + [capable[0]],
                ):
                    with self.assertRaises(AssertionError):
                        peer.admit_monitor_socket(invalid)
                    self.assertEqual(peer.ordinary_read_budget, 1)
                self.assertTrue(peer.admit_monitor_socket(capable))
                self.assertEqual(peer.counts["explicit_foreground_reads"], 1)
                self.assertEqual(peer.ordinary_read_budget, 0)
                with self.assertRaises(AssertionError):
                    peer.admit_monitor_socket(capable)
                with self.assertRaises(AssertionError):
                    peer.control("advance")
                self.assertFalse(peer.admit_monitor_socket(base))
        peer = self.peer()
        peer.control("advance")
        with self.assertRaises(AssertionError):
            peer.admit_monitor_socket(capable)

    def test_deliberate_foreground_read_never_joins_monitor_registry_or_receives_pending_offers(
        self,
    ):
        peer = self.peer(mode="monitor_cas")
        peer.control("advance")
        capable = [
            "canonical_embed_receipts_v1",
            "typed_recovery_outputs_v2",
            "agentic-storage-v2",
            "chat_sync_feed_v1",
            "task_update_jobs",
        ]
        admitted = peer.admit_monitor_socket(capable)
        socket = self.socket(
            self.event(
                "native_client_lifecycle",
                {"client_type": "rust", "interactive": False, "is_foreground": False},
            ),
            self.event("phased_sync_request", {"phase": "all"}),
        )
        socket.handler.essential_foreground_read = admitted
        peer.websocket(socket)
        self.assertIsNone(peer.status()["failure"])
        self.assertEqual(peer.counts["monitor_disconnects"], 0)
        self.assertEqual(peer.monitors, [])
        self.assertFalse(
            any(
                name
                in {
                    "new_chat_message",
                    "task_update_jobs_available",
                    "workflow_chat_deliveries_available",
                }
                for name, _ in socket.frames
            )
        )
        self.assertIn(("recovery_outputs_available", {"outputs": []}), socket.frames)

    def test_pending_offer_consumer_cannot_claim_persist_replay_or_request_recovery(
        self,
    ):
        forbidden = [
            "task_update_job_claim",
            "task_update_job_persist",
            "task_update_job_event_confirmed",
            "workflow_chat_delivery_claim",
            "workflow_chat_delivery_persist",
            "recovery_job_claim",
            "recovery_job_persist",
            "metadata_jobs_request",
            "recovery_output_get",
            "recovery_output_status",
            "recovery_output_ack",
            "recovery_output_ack_checkpoint",
            "store_chat_compression_checkpoint",
        ]
        for identity in ("rust", "npm", "pip"):
            for kind in forbidden:
                with self.subTest(identity=identity, kind=kind):
                    peer = self.peer(identity)
                    socket = self.socket(
                        self.event("phased_sync_request", {"phase": "all"}),
                        self.event(kind, {"job_id": peer.protocol["job_id"]}),
                    )
                    peer.websocket(socket)
                    status = peer.status()
                    self.assertEqual(
                        status["failure"], "passive-monitor-unexpected-frame"
                    )
                    self.assertEqual(status["passive_pending_offer_batches"], 1)
                    self.assertEqual(status["passive_side_effect_attempts"], 1)
                    self.assertEqual(status["claims"], 0)
                    self.assertEqual(status["persists"], 0)
                    self.assertEqual(status["admissions"], 0)
                    self.assertFalse(
                        any(
                            "claimed" in name or "persisted" in name
                            for name, _ in socket.frames
                        )
                    )

    def test_empty_monitor_run_cannot_claim_pending_offer_coverage(self):
        self.assertEqual(
            self.peer().status()["failure"], "passive-monitor-pending-offer-contract"
        )

    def test_pending_summary_shapes_match_canonical_backend_producers_without_importing_services(
        self,
    ):
        root = Path(essential.__file__).parents[2]
        folder = root / "backend/core/api/app/routes/handlers/websocket_handlers"

        def pure_function(path, name):
            tree = ast.parse(path.read_text())
            function = next(
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == name
            )
            module = ast.Module(
                body=[
                    ast.ImportFrom(
                        module="__future__",
                        names=[ast.alias(name="annotations")],
                        level=0,
                    ),
                    function,
                ],
                type_ignores=[],
            )
            namespace = {}
            exec(
                compile(ast.fix_missing_locations(module), str(path), "exec"), namespace
            )
            return namespace[name]

        peer = self.peer()
        offers = dict(peer.pending_monitor_offers())
        task = offers["task_update_jobs_available"]["jobs"][0]
        summary = pure_function(folder / "task_update_job_handlers.py", "_job_summary")
        self.assertEqual(
            task,
            summary(
                {
                    **task,
                    "expected_task_version": task["revision"],
                    "owner_hash": "private-not-offered",
                    "state": "AVAILABLE",
                }
            ),
        )
        workflow = offers["workflow_chat_deliveries_available"]["deliveries"][0]
        projection = pure_function(
            folder / "workflow_chat_delivery_handlers.py", "_delivery_payload"
        )
        self.assertEqual(
            workflow,
            projection(
                SimpleNamespace(
                    **{
                        key: value
                        for key, value in workflow.items()
                        if key != "client_persisted"
                    },
                    client_persistence=None,
                )
            ),
        )
        output = offers["recovery_outputs_available"]["outputs"][0]
        source = (
            root
            / "backend/core/directus/extensions/chat-recovery-transaction/src/operations.js"
        ).read_text()
        block = source[
            source.index("async function listPendingOutputs(") : source.index(
                "async function getPendingOutput("
            )
        ]
        selected = re.search(r"\.select\(\[(.*?)\]\)", block, re.S).group(1)
        fields = set(re.findall(r"'([^']+)'", selected))
        fields.remove("created_at")
        fields.remove("id")
        self.assertEqual(set(output), fields | {"record_id"})
        self.assertEqual(output["root_chat_id"], peer.chat_id)
        self.assertEqual(output["root_hashed_team_id"], None)
        self.assertEqual(output["output_kind"], "embed")


class Phase1MetadataCoverageTests(unittest.TestCase):
    def fixture(self):
        root = Path(__file__).resolve().parents[2]
        source = json.loads(
            (
                root
                / "packages/openmates-rust/tests/fixtures/phase1b-ciphertext-window.json"
            ).read_text()
        )
        row = {
            **source["metadata"],
            "opaqueUserMetadata": {
                "linkedProjectIds": ["雪", "😀"],
                "camelCase": {"sourceId": "preserve-verbatim"},
            },
        }
        return row, source["payload"]

    def test_metadata_coverage_is_independent_of_parent_content_budget(self):
        row, payload = self.fixture()
        original = json.loads(json.dumps(payload))
        records, windows = essential.phase1_metadata_coverage(row, payload)
        self.assertEqual(len(records), 26)
        self.assertEqual(len({record["id"] for record in records}), 26)
        self.assertEqual(
            sum(not record.get("is_sub_chat", False) for record in records), 25
        )
        self.assertEqual(records[-1]["parent_id"], row["id"])
        self.assertTrue(records[-1]["is_sub_chat"])
        self.assertEqual(len(windows["chats"]), 20)
        self.assertEqual(
            [window["chat_id"] for window in windows["chats"]],
            [record["id"] for record in records[:20]],
        )
        self.assertEqual(payload, original)
        for window in windows["chats"]:
            self.assertNotEqual(window["chat_id"], records[-1]["id"])
            self.assertEqual(window["server_message_count"], 5)
            self.assertTrue(window["message_window"]["has_more_before"])
            self.assertEqual(len(window["messages"]), 2)
            for raw in window["messages"]:
                message = json.loads(raw)
                self.assertEqual(message["chat_id"], window["chat_id"])
                self.assertIsInstance(message["encrypted_content"], str)
                self.assertNotIn("content", message)
        for index, record in enumerate(records):
            self.assertEqual(record["opaqueUserMetadata"], row["opaqueUserMetadata"])
            self.assertEqual(record["pinned"], index < 25 and index % 2 == 0)

    def test_existing_metadata_response_page_shapes_preserve_opaque_children_and_memory_boundary(
        self,
    ):
        row = {
            "id": "22222222-2222-4222-8222-222222222222",
            "encrypted_title": "opaque",
            "encrypted_chat_key": "wrapped",
            "draft_v": 7,
            "opaqueUserMetadata": {"camelCase": ["雪", "😀"]},
        }
        expanded, older = essential.metadata_response_pages(row)
        self.assertEqual(
            set(expanded), {"chats", "team_id", "context_epoch", "total_count"}
        )
        self.assertEqual(set(older), set(expanded) | {"offset", "has_more"})
        self.assertEqual(older["offset"], 1000)
        self.assertFalse(older["has_more"])
        parent, child = [wrapper["chat_details"] for wrapper in expanded["chats"]]
        self.assertEqual(child["parent_id"], parent["id"])
        self.assertTrue(child["is_sub_chat"])
        for wrapper in expanded["chats"] + older["chats"]:
            self.assertEqual(set(wrapper), {"chat_details"})
            self.assertEqual(
                wrapper["chat_details"]["opaqueUserMetadata"], row["opaqueUserMetadata"]
            )
            self.assertEqual(wrapper["chat_details"]["draft_v"], 7)
            self.assertNotIn("messages", wrapper["chat_details"])

    def test_existing_monitor_vector_prefix_is_extended_without_new_family(self):
        fixture = (
            Path(essential.__file__).with_name("fixtures")
            / "session-chat-change-monitor.json"
        )
        vectors = json.loads(fixture.read_text())["capabilities"][essential.MONITOR][
            "vectors"
        ]
        self.assertEqual(len(vectors), 13)
        self.assertEqual(
            vectors[11],
            {
                "id": "monitor-phase1-all-metadata-content20",
                "mode": "monitor_phase1b_metadata_coverage",
            },
        )
        self.assertEqual(
            vectors[12],
            {
                "id": "monitor-existing-metadata-responses-memory-pagination",
                "mode": "monitor_phase1b_metadata_responses",
            },
        )
        self.assertEqual(len({vector["id"] for vector in vectors}), 13)


if __name__ == "__main__":
    unittest.main()


class RecoveryDriftTests(unittest.TestCase):
    """Real peer methods with in-memory transport only; no listener/SDK launch."""

    def peer(self, mode):
        fixture = (
            Path(essential.__file__).with_name("fixtures")
            / "session-foreground-completion-recovery.json"
        )
        suite = json.loads(fixture.read_text())["capabilities"][essential.RECOVERY]
        vector = next(row for row in suite["vectors"] if row["mode"] == mode)
        with patch("recovery_server.ThreadingHTTPServer"):
            return essential.EssentialPeer(suite, vector, "rust")

    def payload(self, peer):
        return {
            "protocol_version": 1,
            "job_id": peer.protocol["job_id"],
            "request_id": "request",
            "lease_token": peer.protocol["lease_token"],
            "lease_generation": 7,
            "expected_messages_v": peer.version,
            "encrypted_assistant_message": {
                "client_message_id": peer.protocol["assistant_id"],
                "chat_id": peer.chat_id,
                "created_at": peer.vector.get("created_at", 1),
                "encrypted_content": essential.encrypt(
                    peer.protocol["sealed_content"].encode(), peer.key
                ),
            },
        }

    def test_durable_job_creation_time_survives_cold_peer_persistence(self):
        peer = self.peer("main_created_at")
        socket = RecordingSocket()
        self.assertEqual(peer.job()["created_at"], 1800000001)
        peer.persist(socket, self.payload(peer))
        self.assertEqual(peer.messages[0]["created_at"], 1800000001)
        self.assertEqual(peer.counts["persists"], 1)

    def test_cas_three_retry_success_and_exhaustion_keep_exact_ciphertext_lease(self):
        for mode in ("main_cas_retry", "main_cas_exhausted"):
            peer = self.peer(mode)
            socket = RecordingSocket()
            payload = self.payload(peer)
            candidate = json.loads(json.dumps(payload["encrypted_assistant_message"]))
            for _ in range(4):
                payload["expected_messages_v"] = peer.version
                peer.persist(socket, payload)
                self.assertEqual(payload["encrypted_assistant_message"], candidate)
            self.assertEqual(peer.counts["persist_attempts"], 4)
            self.assertEqual(
                peer.counts["persists"], 1 if mode == "main_cas_retry" else 0
            )
            self.assertEqual(
                [kind for kind, _ in socket.frames].count("error"),
                3 if mode == "main_cas_retry" else 4,
            )

    def test_pending_only_selection_is_negative_data_never_a_claimable_offer(self):
        peer = self.peer("selected_pending")
        socket = RecordingSocket()
        peer.selected_discovery_offers(socket)
        payload = next(
            p for kind, p in socket.frames if kind == "recovery_jobs_available"
        )
        self.assertTrue(all(job["chat_id"] != peer.chat_id for job in payload["jobs"]))
        self.assertEqual(payload["pending_jobs"][0]["chat_id"], peer.chat_id)
        self.assertEqual(payload["pending_jobs"][0]["state"], "LEASED")
        self.assertEqual(peer.counts["claims"], 0)

    def test_legacy_checkpoint_vector_reclaims_only_after_original_lease_expiry(self):
        peer = self.peer("main_legacy_created_at")
        socket = RecordingSocket()
        request = {
            "protocol_version": 1,
            "job_id": peer.protocol["job_id"],
            "request_id": "first",
        }
        peer.claim(socket, request)
        self.assertEqual(socket.frames[-1][1]["lease_generation"], 7)
        self.assertEqual(socket.frames[-1][1]["created_at"], 1800000001)
        with self.assertRaisesRegex(AssertionError, "old original lease must expire"):
            peer.claim(socket, {**request, "request_id": "too-early"})
        self.assertEqual(peer.counts["claims"], 1)
        with patch.object(essential, "datetime") as clock:
            clock.now.return_value = peer.legacy_lease_deadline
            peer.claim(socket, {**request, "request_id": "expired"})
        self.assertEqual(socket.frames[-1][1]["lease_generation"], 8)
        payload = self.payload(peer)
        payload["lease_generation"] = 8
        peer.persist(socket, payload)
        self.assertEqual(peer.counts["claims"], 2)
        self.assertEqual(peer.counts["persists"], 1)
        # Remove only new optional metadata; ciphertext and all original bytes stay exact.
        raw = '{"job":{"job_id":"original","created_at":1800000001},"encrypted_candidate":{"created_at":1800000001,"encrypted_content":"opaque"}}'
        needle = ',"created_at":1800000001},"encrypted_candidate"'
        self.assertEqual(raw.count(needle), 1)
        legacy = raw.replace(needle, '},"encrypted_candidate"')
        self.assertNotIn("created_at", json.loads(legacy)["job"])
        self.assertEqual(
            json.loads(legacy)["encrypted_candidate"],
            json.loads(raw)["encrypted_candidate"],
        )
