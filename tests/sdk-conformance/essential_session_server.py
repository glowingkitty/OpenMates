#!/usr/bin/env python3
"""PRIVATE UNRUN synthetic peer for actual Bridge/NAPI/PyO3 essential calls.

No inference, CLI, account creation, external network or production import.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from recovery_server import RecoveryPeer, encrypt, decrypt, seal, hkdf, lp, b64url

MONITOR = "session.chat-change-monitor.v1"
RECOVERY = "session.foreground-completion-recovery.v1"
PENDING_OFFER_EXPIRES_AT = 4102444800  # Synthetic2100-01-01 UTC; never real job state.


def phase1_metadata_coverage(row, window_payload):
    """Synthetic complete Phase1 metadata with independent20-parent content.

    The actual SDK/socket path calls this fixture helper. These JSON values are
    protocol DATA only and never manufacture Client/monitor/IO authority.
    """
    parents = [row["id"]] + [
        f"30000000-0000-4000-8000-{index:012}" for index in range(1, 25)
    ]
    records = []
    for index, chat_id in enumerate(parents):
        record = json.loads(json.dumps(row))
        record.update(id=chat_id, pinned=index % 2 == 0)
        records.append(record)
    child = json.loads(json.dumps(row))
    child.update(
        id="60000000-0000-4000-8000-000000000000",
        parent_id=parents[0],
        is_sub_chat=True,
        pinned=False,
    )
    records.append(child)
    payload = json.loads(json.dumps(window_payload))
    template = payload["chats"][0]
    windows = []
    for chat_id in parents[:20]:
        window = json.loads(json.dumps(template))
        window["chat_id"] = chat_id
        rows = []
        for raw in window["messages"]:
            message = json.loads(raw) if isinstance(raw, str) else raw
            message["chat_id"] = chat_id
            rows.append(json.dumps(message) if isinstance(raw, str) else message)
        window["messages"] = rows
        windows.append(window)
    payload["chats"] = windows
    return records, payload


def metadata_response_pages(row):
    """Existing backend page shapes: search rows persist, older page stays memory-only."""
    parent = {**row, "id": "70000000-0000-4000-8000-000000000001", "pinned": True}
    child = {
        **row,
        "id": "70000000-0000-4000-8000-000000000002",
        "parent_id": parent["id"],
        "is_sub_chat": True,
        "pinned": False,
    }
    older = {**row, "id": "80000000-0000-4000-8000-000000000001", "pinned": False}
    common = {"team_id": None, "context_epoch": 0, "total_count": 1234}
    expanded = {**common, "chats": [{"chat_details": parent}, {"chat_details": child}]}
    page = {
        **common,
        "chats": [{"chat_details": older}],
        "offset": 1000,
        "has_more": False,
    }
    return expanded, page


class EssentialPeer(RecoveryPeer):
    def __init__(self, suite, vector, identity):
        self.monitors = []
        self.version = 5
        self.terminal = False
        self.denied = False
        self.lock = threading.RLock()
        super().__init__(suite, {**vector, "mode": "essential"}, identity)
        self.mode = vector["mode"]
        self.counts["monitor_disconnects"] = 0
        self.counts["claimed_socket_disconnects"] = 0
        self.counts["passive_pending_offer_batches"] = 0
        self.counts["passive_side_effect_attempts"] = 0
        self.counts["explicit_foreground_reads"] = 0
        self.ordinary_read_budget = 0
        self.counts["persist_attempts"] = 0
        self.cas_candidate = None
        self.wrapped = encrypt(self.key, self.master)
        private = hkdf(
            self.key,
            hashlib.sha256(b"openmates:chat-recovery:v1").digest(),
            lp(self.chat_id) + (1).to_bytes(4, "big"),
        )
        self.public = b64url(
            X25519PrivateKey.from_private_bytes(private)
            .public_key()
            .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        )

    def row(self):
        return {
            "id": self.chat_id,
            "encrypted_chat_key": self.wrapped,
            "encrypted_title": encrypt(
                ("Synthetic " + str(self.version)).encode(), self.key
            ),
            "messages_v": self.version,
            "opaqueUserMetadata": {
                "linkedProjectIds": ["雪", "😀"],
                "camelCase": {"sourceId": "preserve-verbatim"},
            },
        }

    def job(self):
        return {
            **(
                {"created_at": self.vector["created_at"]}
                if "created_at" in self.vector
                else {}
            ),
            "job_id": self.protocol["job_id"],
            "chat_id": self.chat_id,
            "turn_id": self.protocol["turn_id"],
            "assistant_message_id": self.protocol["assistant_id"],
            "inference_task_id": "99999999-9999-4999-8999-999999999999",
            "chat_key_version": 1,
            "state": "TERMINAL" if self.terminal else "AVAILABLE",
        }

    def pending_monitor_offers(self):
        # Canonical discovery shapes, offered adversarially even without the
        # task capability: an unsolicited hint must never grant write authority.
        # task_update_job_handlers._job_summary; workflow_chat_delivery_handlers
        # ._delivery_payload; Directus listPendingOutputs projection.
        task = {
            "job_id": self.protocol["job_id"],
            "task_id": self.protocol["record_id"],
            "chat_id": self.chat_id,
            "revision": 1,
            "task_key_version": 1,
            "expires_at": PENDING_OFFER_EXPIRES_AT,
        }
        workflow = {
            "delivery_id": self.protocol["record_id"],
            "chat_id": self.chat_id,
            "message_id": self.protocol["assistant_id"],
            "status": "delivery_pending",
            "encrypted_payload": "synthetic-opaque-vault-ciphertext",
            "created_at": 1,
            "expires_at": PENDING_OFFER_EXPIRES_AT,
            "claim_generation": 0,
            "claim_expires_at": None,
            "workflow_id": None,
            "run_id": None,
            "client_persisted": False,
        }
        output = {
            **self.output(),
            "root_hashed_team_id": None,
            "message_role": None,
            "payload_storage": "inline",
        }
        return [
            ("task_update_jobs_available", {"jobs": [task]}),
            ("workflow_chat_deliveries_available", {"deliveries": [workflow]}),
            ("recovery_outputs_available", {"outputs": [output]}),
        ]

    def admit_monitor_socket(self, capabilities):
        # Two existing CAS vectors deliberately call the ordinary public list
        # after advance to invalidate staged data. That is not a monitor stage.
        if "task_update_jobs" not in capabilities:
            assert "chat_metadata_recovery" not in capabilities
            return False
        assert self.mode in {"monitor_cas", "monitor_data_changed"}
        assert (
            self.ordinary_read_budget == 1
            and self.counts["explicit_foreground_reads"] == 0
        )
        assert len(capabilities) == 5 and set(capabilities) == {
            "canonical_embed_receipts_v1",
            "typed_recovery_outputs_v2",
            "agentic-storage-v2",
            "chat_sync_feed_v1",
            "task_update_jobs",
        }
        self.ordinary_read_budget = 0
        self.counts["explicit_foreground_reads"] += 1
        self.mark("explicit-foreground-cas-read")
        return True

    def status(self):
        if self.mode == "monitor" and (
            not self.counts["passive_pending_offer_batches"]
            or self.counts["passive_side_effect_attempts"]
            or self.counts["claims"]
            or self.counts["persists"]
        ):
            self.failure = self.failure or "passive-monitor-pending-offer-contract"
        if self.mode in {"monitor_cas", "monitor_data_changed"} and (
            self.ordinary_read_budget or self.counts["explicit_foreground_reads"] != 1
        ):
            self.failure = self.failure or "explicit-foreground-read-contract"
        return super().status()

    def control(self, action):
        if action == "deny":
            self.denied = True
        if action == "advance":
            if self.mode in {"monitor_cas", "monitor_data_changed"}:
                assert (
                    self.ordinary_read_budget == 0
                    and self.counts["explicit_foreground_reads"] == 0
                )
                self.ordinary_read_budget = 1
            self.version += 1
        for socket in list(self.monitors):
            try:
                if action == "revoke":
                    socket.send("force_logout", {"reason": "synthetic-owner-revoked"})
                else:
                    for _ in range(200 if action == "burst" else 1):
                        socket.send("new_chat_message", {"chat_id": self.chat_id})
            except (OSError, EOFError):
                pass
        return {"success": True}

    def handler(self):
        parent = super().handler()
        peer = self

        class Handler(parent):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def do_POST(self):
                if self.path == "/v1/chats/metadata/batch" and peer.denied:
                    peer.headers(self)
                    length = int(self.headers["Content-Length"])
                    assert 0 < length < 65536
                    self.rfile.read(length)
                    self.response(403, {"detail": "Forbidden"})
                    return
                super().do_POST()

            def do_GET(self):
                route = urlsplit(self.path)
                if route.path == "/__test/control":
                    self.response(200, peer.control(parse_qs(route.query)["action"][0]))
                    return
                if route.path == f"/v1/chats/{peer.chat_id}/messages/window":
                    peer.headers(self)
                    self.response(
                        200, {"messages": peer.messages, "has_more_before": False}
                    )
                    peer.mark("canonical-message-reread")
                    return
                if route.path == "/v1/ws":
                    capabilities = (
                        parse_qs(route.query)
                        .get("client_capabilities", [""])[0]
                        .split(",")
                    )
                    self.essential_foreground_read = False
                    if peer.mode.startswith("monitor"):
                        self.essential_foreground_read = peer.admit_monitor_socket(
                            capabilities
                        )
                    else:
                        assert "task_update_jobs" not in capabilities
                super().do_GET()

        return Handler

    def validate_sync_phase(self, socket, payload):
        # Reusable library/monitor fixtures retain their existing all-only contract.
        assert payload["phase"] == "all"

    def websocket(self, raw):
        # The parent handler supplies its parsed transport; attach one write lock
        # because independent test control requests may send revocation/hints.
        socket = raw
        socket.handler.connection.settimeout(5)
        lock = threading.Lock()
        original_raw = socket.raw

        def locked(opcode, data):
            with lock:
                original_raw(opcode, data)

        socket.raw = locked
        self.counts["connections"] += 1
        claimed = False
        foreground_read = getattr(socket.handler, "essential_foreground_read", False)
        try:
            while (event := socket.receive()) is not None:
                kind, payload = event["type"], event["payload"]
                if self.mode.startswith("monitor") and kind not in {
                    "native_client_lifecycle",
                    "set_active_chat",
                    "phased_sync_request",
                }:
                    self.counts["passive_side_effect_attempts"] += 1
                    self.failure = "passive-monitor-unexpected-frame"
                    raise AssertionError(
                        "Passive monitor cannot claim, persist or replay pending work"
                    )
                if kind == "native_client_lifecycle":
                    assert (
                        payload["client_type"] == self.identity
                        and payload["interactive"] is False
                    )
                    socket.send(
                        "native_client_lifecycle_ack",
                        {"is_foreground": payload["is_foreground"]},
                    )
                    if (
                        self.mode.startswith("monitor")
                        and not foreground_read
                        and socket not in self.monitors
                    ):
                        self.monitors.append(socket)
                        if self.mode != "monitor_read_cancel":
                            socket.send("new_chat_message", {"chat_id": self.chat_id})
                    self.mark("real-sdk-identity")
                    if self.mode.startswith("selected_") and payload["is_foreground"]:
                        self.selected_discovery_offers(socket)

                elif kind == "set_active_chat":
                    assert payload["chat_id"] == self.chat_id
                elif kind == "phased_sync_request":
                    assert not self.mode.startswith("selected_"), (
                        "selected discovery cannot fetch global phased content"
                    )
                    self.validate_sync_phase(socket, payload)
                    coverage_rows = None
                    if self.mode.startswith("monitor_phase1b"):
                        vector = json.loads(
                            (
                                Path(__file__).resolve().parents[2]
                                / "packages/openmates-rust/tests/fixtures/phase1b-ciphertext-window.json"
                            ).read_text()
                        )
                        window_payload = vector["payload"]
                        coverage_rows = None
                        if self.mode in (
                            "monitor_phase1b_metadata_coverage",
                            "monitor_phase1b_metadata_responses",
                        ):
                            coverage_rows, window_payload = phase1_metadata_coverage(
                                self.row(), window_payload
                            )
                        socket.send(
                            "phase_1_last_chat_ready",
                            {
                                "chat_id": self.chat_id,
                                "chat_details": coverage_rows[0]
                                if coverage_rows
                                else self.row(),
                                "messages": None,
                                "recent_chat_metadata": coverage_rows[1:]
                                if coverage_rows
                                else [],
                                "team_id": None,
                                "context_epoch": 0,
                            },
                        )
                        assert window_payload["chats"][0]["chat_id"] == self.chat_id
                        if self.mode == "monitor_phase1b_context":
                            window_payload["context_epoch"] = 1
                            socket.send(vector["event_type"], window_payload)
                            self.mark("phase1b-context-refusal-offered")
                            return
                        socket.send(vector["event_type"], window_payload)
                        if self.mode == "monitor_phase1b_duplicate":
                            socket.send(vector["event_type"], window_payload)
                        self.mark("bounded-phase1b-ciphertext-window")
                    socket.send(
                        "phase_2_last_20_chats_ready",
                        {
                            "chats": [
                                {
                                    "chat_details": coverage_rows[0]
                                    if coverage_rows
                                    else self.row()
                                }
                            ]
                        },
                    )
                    if self.mode == "monitor_phase1b_metadata_responses":
                        expanded, older = metadata_response_pages(self.row())
                        socket.send("sync_metadata_chats_response", expanded)
                        socket.send(
                            "sync_metadata_chats_response", expanded
                        )  # identical replay
                        socket.send("load_more_chats_response", older)
                        self.mark("existing-metadata-response-pages-offered")
                    if not self.mode.startswith("monitor"):
                        socket.send(
                            "recovery_jobs_available",
                            {"jobs": [] if self.terminal else [self.job()]},
                        )
                    if self.mode == "monitor" and not foreground_read:
                        for offer_kind, offer_payload in self.pending_monitor_offers():
                            socket.send(offer_kind, offer_payload)
                        self.counts["passive_pending_offer_batches"] += 1
                        self.mark("passive-pending-offers-delivered")
                    else:
                        socket.send("recovery_outputs_available", {"outputs": []})
                    socket.send(
                        "phased_sync_complete",
                        {"phase": "phase2"} if payload["phase"] == "phase2" else {},
                    )
                    socket.send(
                        "recovery_outputs_discovery_complete", {"status": "completed"}
                    )
                    self.mark("strict-canonical-sync")
                elif kind == "metadata_jobs_request":
                    socket.send("metadata_jobs_available", {"jobs": []})
                    self.mark("separate-metadata-discovery")
                elif kind == "recovery_job_claim":
                    if self.mode.startswith("selected_"):
                        assert payload["job_id"] == self.protocol["job_id"], (
                            "unrelated job must stay unclaimed"
                        )

                    claimed = True
                    self.claim(socket, payload)
                elif kind == "recovery_job_persist":
                    self.persist(socket, payload)
                    if self.mode == "main_lost_ack":
                        return
                else:
                    self.failure = "unexpected-client-frame"
                    raise AssertionError(
                        "No inference, Task autoexecution, generic route or unsupported fixture frame"
                    )
        except (EOFError, OSError):
            pass
        except Exception:
            self.failure = self.failure or "essential-protocol"
        finally:
            if claimed:
                self.counts["claimed_socket_disconnects"] += 1
            if socket in self.monitors:
                self.monitors.remove(socket)
                self.counts["monitor_disconnects"] += 1
            self.mark("socket-closed")

    def selected_discovery_offers(self, socket):
        """Existing authenticated startup protocol, no phased response/receipt."""
        self.counts["selected_discoveries"] = (
            self.counts.get("selected_discoveries", 0) + 1
        )
        unrelated = {
            **self.job(),
            "chat_id": self.vector["unrelated_chat_id"],
            "job_id": self.vector["unrelated_job_id"],
            "state": "AVAILABLE",
        }
        selected = (
            []
            if self.mode in {"selected_empty", "selected_pending"} or self.terminal
            else [self.job()]
        )
        socket.send(
            "recovery_jobs_available",
            {
                "jobs": selected + [unrelated],
                **(
                    {"pending_jobs": [{**self.job(), "state": "LEASED"}]}
                    if self.mode == "selected_pending"
                    else {}
                ),
            },
        )
        socket.send("metadata_jobs_available", {"jobs": []})
        socket.send("recovery_outputs_available", {"outputs": []})
        if self.mode == "selected_cancel":
            self.counts["selected_discovery_waiting"] = (
                self.counts.get("selected_discovery_waiting", 0) + 1
            )
        else:
            socket.send(
                "recovery_outputs_discovery_complete",
                {
                    "status": "failed"
                    if self.mode == "selected_partial_failure"
                    else "completed"
                },
            )
        self.mark("selected-startup-without-phased-sync")

    def claim(self, socket, payload):
        if self.mode == "main_legacy_created_at" and self.counts["claims"]:
            assert datetime.now(timezone.utc) >= self.legacy_lease_deadline, (
                "old original lease must expire before re-claim"
            )
        self.counts["claims"] += 1
        assert (
            payload["protocol_version"] == 1
            and payload["job_id"] == self.protocol["job_id"]
        )
        if self.mode == "main_cancel":
            return
        reply = {
            **self.job(),
            "request_id": payload["request_id"],
            "state": "TERMINAL" if self.terminal else "LEASED",
        }
        if not self.terminal:
            reply.update(
                lease_token=self.protocol["lease_token"],
                lease_generation=7
                + (
                    self.counts["claims"] - 1
                    if self.mode == "main_legacy_created_at"
                    else 0
                ),
                lease_expires_at=(
                    datetime.now(timezone.utc)
                    + timedelta(
                        seconds=1
                        if self.mode == "main_expiry"
                        or (
                            self.mode == "main_legacy_created_at"
                            and self.counts["claims"] == 1
                        )
                        else 60
                    )
                )
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
            )
            identity = [
                self.account["owner_id"],
                self.chat_id,
                self.protocol["turn_id"],
                self.protocol["job_id"],
                self.protocol["assistant_id"],
            ]
            content = {
                "assistant_message_id": self.protocol["assistant_id"],
                "chat_id": self.chat_id,
                "turn_id": self.protocol["turn_id"],
                "job_id": self.protocol["job_id"],
                "key_version": 1,
                "content": self.protocol["sealed_content"],
                "category": None,
                "model_name": None,
            }
            reply["sealed_payload"] = json.dumps(seal(self.public, identity, content))
        if self.mode == "main_legacy_created_at" and self.counts["claims"] == 1:
            self.legacy_lease_deadline = datetime.fromisoformat(
                reply["lease_expires_at"].replace("Z", "+00:00")
            )
        socket.send("recovery_job_claimed", reply)
        self.mark("foreground-exact-claim")

    def persist(self, socket, payload):
        assert (
            payload["protocol_version"] == 1
            and payload["job_id"] == self.protocol["job_id"]
        )
        assert payload["lease_token"] == self.protocol["lease_token"] and payload[
            "lease_generation"
        ] == 7 + (
            self.counts["claims"] - 1 if self.mode == "main_legacy_created_at" else 0
        )
        assert payload["expected_messages_v"] == self.version
        message = payload["encrypted_assistant_message"]
        assert (
            message["client_message_id"] == self.protocol["assistant_id"]
            and message["chat_id"] == self.chat_id
        )
        assert (
            decrypt(message["encrypted_content"], self.key).decode()
            == self.protocol["sealed_content"]
        )
        assert self.protocol["sealed_content"] not in json.dumps(payload)
        self.counts["persist_attempts"] += 1
        if self.mode.startswith("main_cas_"):
            if self.cas_candidate is None:
                self.cas_candidate = json.loads(json.dumps(message))
            assert message == self.cas_candidate, (
                "CAS retry must reuse exact ciphertext"
            )
            limit = 3 if self.mode == "main_cas_retry" else 4
            if self.counts["persist_attempts"] <= limit:
                self.version += 1
                socket.send(
                    "error",
                    {
                        "request_id": payload["request_id"],
                        "job_id": payload["job_id"],
                        "code": "version_conflict",
                    },
                )
                self.mark("same-lease-version-cas-conflict")
                return
        if "created_at" in self.vector:
            assert message["created_at"] == self.vector["created_at"]
        self.counts["persists"] += 1
        self.messages = [message]
        self.version += 1
        self.terminal = True
        self.mark("canonical-encrypted-completion")
        if self.mode != "main_lost_ack":
            socket.send(
                "recovery_job_persisted",
                {
                    **self.job(),
                    "request_id": payload["request_id"],
                    "state": "TERMINAL",
                    "committed_messages_v": self.version,
                },
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--capability", required=True, choices=[MONITOR, RECOVERY])
    parser.add_argument("--vector", required=True)
    parser.add_argument("--identity", required=True, choices=["rust", "npm", "pip"])
    args = parser.parse_args()
    suite = json.loads(Path(args.fixture).read_text())["capabilities"][args.capability]
    vector = next(item for item in suite["vectors"] if item["id"] == args.vector)
    peer = EssentialPeer(suite, vector, args.identity)
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    try:
        peer.server.serve_forever()
    finally:
        peer.server.server_close()


if __name__ == "__main__":
    main()
