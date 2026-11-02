"""Independent saved-turn loopback protocol for session.work-crud lifecycle cases.

Auth, websocket framing and AES-GCM use the maintained test peer, never SDK code.
Authored runtime fixture: actual Rust/NAPI/PyO3 execution belongs to isolated CI.
"""

from __future__ import annotations

import copy
import json
import threading
from urllib.parse import urlsplit, parse_qs
import uuid

from recovery_server import RecoveryPeer, decrypt, encrypt, seal


class SavedStreamPeer(RecoveryPeer):
    def __init__(self, suite, vector, identity):
        super().__init__(suite["saved_stream"], vector, identity)
        self.release_b = threading.Event()
        self.release_inventory_body = threading.Event()
        self.hold_next_inventory = False
        self.release_owned_a = None
        self.version_enabled = False
        self.release_version_body = threading.Event()
        self.version_assistant = "55555555-5555-4555-8555-555555555555"
        self.version_job = "66666666-6666-4666-8666-666666666665"
        self.version_content = "Synthetic sealed Version reply"
        self.version_lease = "synthetic-version-lease"
        self.catalogue_enabled = False
        self.catalogue_project = "66666666-6666-4666-8666-666666666666"
        self.catalogue_key = bytes([9]) * 32
        self.release_catalogue_body = threading.Event()
        self.snapshot_waiting = False
        self.snapshots = 0
        self.turns, self.message_ids, self.admitted_chats = set(), set(), []
        self.admitted_messages = []
        self.saved_messages = {}
        self.counts.update(
            auth_checks=0,
            auth_denials=0,
            closed_sockets=0,
            task_cancel_requests=0,
            product_http_requests=0,
            inventory_requests=0,
            inventory_headers=0,
            catalogue_requests=0,
            catalogue_headers=0,
            catalogue_results=0,
            version_requests=0,
            version_headers=0,
        )
        self._lock = threading.Lock()

    def close(self):
        self.release_b.set()
        self.release_inventory_body.set()
        self.release_catalogue_body.set()
        self.release_version_body.set()
        super().close()

    def status(self):
        with self._lock:
            return {
                **super().status(),
                "turns": sorted(self.turns),
                "message_ids": sorted(self.message_ids),
                "admitted_chats": list(self.admitted_chats),
                "admitted_messages": list(self.admitted_messages),
                "snapshot_waiting": self.snapshot_waiting,
            }

    def row(self):
        row = super().row()
        row["messages_v"] = len(self.saved_messages.get(self.chat_id, []))
        return row

    def handler(self):
        base = super().handler()
        peer = self

        class Handler(base):
            def do_POST(self):
                with peer._lock:
                    peer.counts["product_http_requests"] += 1
                if self.path == "/v1/auth/session":
                    peer.counts["auth_checks"] += 1
                    if peer.vector["mode"] == "saved_auth_denial":
                        peer.headers(self)
                        self.rfile.read(int(self.headers["Content-Length"]))
                        peer.counts["auth_denials"] += 1
                        self.response(403, {"detail": "synthetic-private-denial"})
                        return
                if (
                    self.path == "/v1/chats/metadata/batch"
                    and peer.version_enabled
                    and peer.counts["claims"]
                    and not peer.counts["persists"]
                ):
                    try:
                        peer.headers(self)
                        value = json.loads(
                            self.rfile.read(int(self.headers["Content-Length"]))
                        )
                        assert value == {"chat_ids": [peer.chat_id]}
                        raw = json.dumps({"chats": [peer.row()]}).encode()
                        with peer._lock:
                            peer.counts["version_requests"] += 1
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(raw)))
                        self.send_header(
                            "Set-Cookie",
                            "auth_refresh_token=synthetic-version-rotation; Path=/",
                        )
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.wfile.flush()
                        peer.account["cookie"] = "synthetic-version-rotation"
                        with peer._lock:
                            peer.counts["version_headers"] += 1
                        assert peer.release_version_body.wait(10), (
                            "Version body release timeout"
                        )
                        self.wfile.write(raw)
                        self.wfile.flush()
                    except (EOFError, BrokenPipeError, ConnectionResetError):
                        pass
                    except Exception:
                        peer.failure = peer.failure or "fixed-version-protocol"
                    return
                super().do_POST()

            def do_GET(self):
                route = urlsplit(self.path)
                if not route.path.startswith("/__test/"):
                    with peer._lock:
                        peer.counts["product_http_requests"] += 1
                if route.path == "/__test/version-enable":
                    peer.version_enabled = True
                    peer.release_version_body.clear()
                    self.response(200, {})
                    return
                if route.path == "/__test/version-release-body":
                    peer.release_version_body.set()
                    self.response(200, {})
                    return
                if route.path == "/__test/catalogue-enable":
                    peer.catalogue_enabled = True
                    peer.release_catalogue_body.clear()
                    self.response(200, {})
                    return
                if route.path == "/__test/catalogue-release-body":
                    peer.release_catalogue_body.set()
                    self.response(200, {})
                    return
                if (
                    route.path == f"/v1/projects/{peer.catalogue_project}"
                    and peer.catalogue_enabled
                ):
                    try:
                        peer.headers(self)
                        assert parse_qs(route.query) == {}, (
                            "existing personal Project catalogue query"
                        )
                        project = {
                            "project_id": peer.catalogue_project,
                            "encrypted_project_key": encrypt(
                                peer.catalogue_key, peer.master
                            ),
                        }
                        metadata = {
                            "display_path": ".openmates/focuses/fixture/SKILL.md",
                            "focus_title": "Fixture focus",
                            "focus_description": "Fixture description",
                            "focus_when_to_use": "Fixture use",
                        }
                        item = {
                            "project_item_id": "fixture-focus",
                            "item_type": "embed",
                            "target_id_hash": "fixture-target",
                            "updated_at": 1,
                            "encrypted_metadata": encrypt(
                                json.dumps(metadata).encode(), peer.catalogue_key
                            ),
                        }
                        raw = json.dumps(
                            {"project": project, "items": [item], "folders": []}
                        ).encode()
                        with peer._lock:
                            peer.counts["catalogue_requests"] += 1
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(raw)))
                        self.send_header(
                            "Set-Cookie",
                            "auth_refresh_token=synthetic-catalogue-rotation; Path=/",
                        )
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.wfile.flush()
                        peer.account["cookie"] = "synthetic-catalogue-rotation"
                        with peer._lock:
                            peer.counts["catalogue_headers"] += 1
                        assert peer.release_catalogue_body.wait(10), (
                            "catalogue body release timeout"
                        )
                        self.wfile.write(raw)
                        self.wfile.flush()
                    except (EOFError, BrokenPipeError, ConnectionResetError):
                        pass
                    except Exception:
                        peer.failure = (
                            peer.failure or "fixed-project-catalogue-protocol"
                        )
                    return
                if route.path == "/__test/inventory-hold-next":
                    peer.hold_next_inventory = True
                    peer.release_inventory_body.clear()
                    self.response(200, {})
                    return
                if route.path == "/__test/inventory-release-body":
                    peer.release_inventory_body.set()
                    self.response(200, {})
                    return
                if route.path == "/__test/release-owned-a":
                    assert peer.release_owned_a is not None
                    peer.release_owned_a()
                    self.response(200, {})
                    return
                if route.path == "/v1/apps/metadata":
                    try:
                        peer.headers(self)
                        assert parse_qs(route.query) == {
                            "include_unavailable": ["true"]
                        }
                        with peer._lock:
                            peer.counts["inventory_requests"] += 1
                            index = peer.counts["inventory_requests"]
                        held = peer.hold_next_inventory
                        peer.hold_next_inventory = False
                        raw = json.dumps(
                            {
                                "apps": {
                                    "fixture-app": {
                                        "name": "Fixture inventory",
                                        "status": "available",
                                    }
                                }
                            }
                        ).encode()
                        cookie = f"synthetic-inventory-rotation-{index}"
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(raw)))
                        self.send_header(
                            "Set-Cookie", f"auth_refresh_token={cookie}; Path=/"
                        )
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.wfile.flush()
                        # The next actual request must use this observed cookie.
                        peer.account["cookie"] = cookie
                        with peer._lock:
                            peer.counts["inventory_headers"] += 1
                        if held:
                            assert peer.release_inventory_body.wait(10), (
                                "inventory body release timeout"
                            )
                        self.wfile.write(raw)
                        self.wfile.flush()
                    except (EOFError, BrokenPipeError, ConnectionResetError):
                        pass
                    except Exception:
                        peer.failure = peer.failure or "fixed-apps-inventory-protocol"
                    return
                if route.path == "/__test/release-b":
                    peer.release_b.set()
                    self.response(200, {})
                    return
                if route.path == "/v1/projects/focus/current":
                    peer.headers(self)
                    assert parse_qs(route.query) == {"chat_id": [peer.chat_id]}
                    peer.checks.add("fresh-canonical-focus-no-selection")
                    self.response(200, {"focus": None})
                    return
                if route.path.startswith("/v1/chats/") and route.path.endswith(
                    "/messages/window"
                ):
                    try:
                        peer.headers(self)
                        chat = route.path.split("/")[3]
                        assert chat == peer.chat_id
                        assert parse_qs(route.query) == {
                            "direction": ["latest"],
                            "limit": ["100"],
                            "respect_compression_boundary": ["false"],
                        }
                        self.response(
                            200,
                            {
                                "messages": peer.saved_messages.get(chat, []),
                                "has_more_before": False,
                            },
                        )
                    except Exception:
                        peer.failure = peer.failure or "saved-window-protocol"
                        self.response(500, {})
                    return
                super().do_GET()

        return Handler

    def websocket(self, socket):
        self.counts["connections"] += 1
        try:
            while (event := socket.receive()) is not None:
                kind, payload = event["type"], event["payload"]
                if kind == "native_client_lifecycle":
                    assert payload["client_type"] == self.identity
                    assert payload["interactive"] is False
                elif kind == "set_active_chat":
                    uuid.UUID(payload["chat_id"])
                    self.chat_id = payload["chat_id"]
                elif kind == "personal_send_context_snapshot":
                    self.snapshots += 1
                    if (
                        self.vector["mode"] == "saved_pre_effect_abort"
                        and self.snapshots == 1
                    ):
                        # Real SDK future is waiting on its authenticated socket;
                        # leave the exact response pending until scoped cancel.
                        self.snapshot_waiting = True
                        continue
                    socket.send(
                        "personal_send_context_snapshot_result",
                        {
                            "success": True,
                            "unchanged": False,
                            "request_id": payload["request_id"],
                            "turn_id": payload["turn_id"],
                            "receipt_id": "synthetic-saved-privacy",
                            "privacy_generation": 1,
                            "personal_memories": {"memories": []},
                            "project_candidates": [
                                {
                                    "project_id": self.catalogue_project,
                                    "encrypted_project_key": encrypt(
                                        self.catalogue_key, self.master
                                    ),
                                    "encrypted_name": encrypt(
                                        b"Fixture project", self.catalogue_key
                                    ),
                                    "auto_selection": True,
                                    "focus_activation_policy": "delayed",
                                }
                            ]
                            if self.catalogue_enabled
                            else [],
                        },
                    )
                elif kind == "chat_turn_admit":
                    self.admit_saved(socket, payload)
                elif kind == "project_focus_catalog_result":
                    assert self.catalogue_enabled
                    assert payload["chat_id"] == self.admitted_chats[0]
                    assert payload["project_id"] == self.catalogue_project
                    assert payload["request_id"] == "synthetic-catalogue-request"
                    assert len(payload["focuses"]) == 1
                    focus = payload["focuses"][0]
                    assert focus["item_id"] == "fixture-focus"
                    assert focus["title"] == "Fixture focus"
                    assert focus["description"] == "Fixture description"
                    assert focus["when_to_use"] == "Fixture use"
                    assert (
                        isinstance(focus["revision"], str)
                        and len(focus["revision"]) == 64
                    )
                    with self._lock:
                        self.counts["catalogue_results"] += 1
                elif kind == "recovery_job_claim" and self.version_enabled:
                    self.claim_version(socket, payload)
                elif kind == "recovery_job_persist" and self.version_enabled:
                    self.persist_version(socket, payload)
                elif kind == "cancel_ai_task":
                    assert (
                        self.vector["mode"] == "saved_active_task_cancel"
                        or self.version_enabled
                    )
                    assert payload == {
                        "chat_id": self.admitted_chats[0],
                        "task_id": "synthetic-active-task-A",
                    }
                    self.counts["task_cancel_requests"] += 1
                    self.checks.add("exact-A-task-revocation-request-not-settlement")
                elif kind == "phased_sync_request":
                    assert payload["phase"] == "all"
                    socket.send(
                        "phase_2_last_20_chats_ready",
                        {"chats": [{"chat_details": self.row()}]},
                    )
                    socket.send("phased_sync_complete", {})
                    socket.send(
                        "recovery_outputs_discovery_complete", {"status": "completed"}
                    )
                else:
                    raise AssertionError("unexpected saved stream frame")
        except (EOFError, BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.failure = self.failure or "saved-websocket-protocol"
        finally:
            self.counts["closed_sockets"] += 1

    def admit_saved(self, socket, payload):
        # Inspect actual independently decrypted request bytes. No fixture flag,
        # local iterator state or error string grants a terminal/rearm receipt.
        chat, turn, message = (
            payload[key] for key in ("chat_id", "turn_id", "message_id")
        )
        for identity in (chat, turn, message):
            assert str(uuid.UUID(identity)) == identity
        assert turn not in self.turns and message not in self.message_ids
        self.key = decrypt(payload["encrypted_chat_key"], self.master)
        assert len(self.key) == 32 and self.key != self.master
        self.wrapped = payload["encrypted_chat_key"]
        assert (
            decrypt(
                payload["encrypted_user_message"]["encrypted_content"], self.key
            ).decode()
            == self.protocol["input"]
        )
        assert (
            payload["inference_request"]["message"]["content"] == self.protocol["input"]
        )
        assert (
            not {
                "model",
                "model_id",
                "model_name",
                "provider",
                "provider_id",
                "provider_name",
            }
            & payload["inference_request"].keys()
        )
        assert payload["privacy_receipt_id"] == "synthetic-saved-privacy"
        assert (
            type(payload["privacy_generation"]) is int
            and payload["privacy_generation"] == 1
        )
        assert payload["protocol_version"] == payload["chat_key_version"] == 1
        previous = self.saved_messages.setdefault(chat, [])
        assert type(payload["expected_messages_v"]) is int and payload[
            "expected_messages_v"
        ] == len(previous)
        row = copy.deepcopy(payload["encrypted_user_message"])
        assert (
            row["client_message_id"] == message
            and row["chat_id"] == chat
            and row["role"] == "user"
        )
        assert type(row["created_at"]) is int and row["created_at"] >= 0
        assert row["updated_at"] == row["created_at"]
        previous.append(row)
        with self._lock:
            self.turns.add(turn)
            self.message_ids.add(message)
            self.admitted_chats.append(chat)
            self.admitted_messages.append(message)
            self.counts["admissions"] += 1
            index = self.counts["admissions"]
        assert index <= self.vector["expected_admissions"]
        self.checks.update(
            (
                "actual-encrypted-saved-admission",
                "no-replay-of-turn-or-message-identities",
                "no-model-provider-override",
            )
        )
        socket.send(
            "chat_turn_preflight_ack",
            {
                "turn_id": turn,
                "preflight_id": "synthetic-preflight",
                "committed_messages_v": len(previous),
            },
        )
        socket.send(
            "chat_message_confirmed",
            {"chat_id": chat, "message_id": message, "new_messages_v": len(previous)},
        )

        def queued():
            socket.send(
                "message_queued",
                {
                    "chat_id": chat,
                    "message_id": message,
                    "user_message_id": message,
                    "turn_id": turn,
                    "recovery_turn_id": turn,
                    "queue_mode": "follow_up",
                    "queue_revision": index,
                },
            )

        if index == 1:
            # Test-only release of the existing exact queued terminal frame;
            # it never supplies authority or a fabricated cancellation result.
            self.release_owned_a = queued
        if self.version_enabled and index == 1:
            self.admission = copy.deepcopy(payload)
            socket.send(
                "ai_task_initiated",
                {
                    "chat_id": chat,
                    "user_message_id": message,
                    "task_id": "synthetic-active-task-A",
                },
            )
            socket.send(
                "ai_message_update",
                {
                    "chat_id": chat,
                    "user_message_id": message,
                    "task_id": "synthetic-active-task-A",
                    "message_id": self.version_assistant,
                    "full_content_so_far": "Transient only",
                    "is_final_chunk": True,
                    "recovery_protocol_version": 1,
                    "recovery_turn_id": turn,
                    "recovery_job_id": self.version_job,
                    "created_at": 1,
                },
            )
            socket.send("recovery_outputs_discovery_complete", {"status": "completed"})
        if self.catalogue_enabled and index == 1:
            socket.send(
                "project_focus_catalog_requested",
                {
                    "chat_id": chat,
                    "project_id": self.catalogue_project,
                    "team_id": None,
                    "request_id": "synthetic-catalogue-request",
                },
            )
        if self.vector["mode"] == "saved_active_task_cancel" and index == 1:
            socket.send(
                "ai_task_initiated",
                {
                    "chat_id": chat,
                    "user_message_id": message,
                    "task_id": "synthetic-active-task-A",
                },
            )
            socket.send(
                "ai_message_update",
                {
                    "chat_id": chat,
                    "user_message_id": message,
                    "turn_id": turn,
                    "task_id": "synthetic-active-task-A",
                    "message_id": "55555555-5555-4555-8555-555555555555",
                    "full_content_so_far": "Synthetic live fragment",
                    "is_final_chunk": False,
                },
            )
        elif self.vector["mode"] in {
            "saved_stale_terminal",
            "saved_queued_successor_terminal",
        }:
            if index == 1:
                queued()
            else:

                def release():
                    if self.release_b.wait(10):
                        try:
                            queued()
                        except (EOFError, BrokenPipeError, ConnectionResetError):
                            pass
                    else:
                        self.failure = self.failure or "saved-B-release-timeout"

                threading.Thread(target=release, daemon=True).start()
        elif index == 2 or self.vector["mode"] == "saved_pre_effect_abort":
            queued()
        # First-turn hold is released only by the actual SDK socket close. The
        # peer never fabricates a cancellation terminal or a reusable context.

    def claim_version(self, socket, payload):
        assert (
            payload["protocol_version"] == 1 and payload["job_id"] == self.version_job
        )
        assert uuid.UUID(payload["request_id"]).version == 4
        with self._lock:
            self.counts["claims"] += 1
        turn = self.admission["turn_id"]
        identity = [
            self.account["owner_id"],
            self.chat_id,
            turn,
            self.version_job,
            self.version_assistant,
        ]
        content = {
            "assistant_message_id": self.version_assistant,
            "chat_id": self.chat_id,
            "turn_id": turn,
            "job_id": self.version_job,
            "key_version": 1,
            "content": self.version_content,
            "category": None,
            "model_name": None,
        }
        socket.send(
            "recovery_job_claimed",
            {
                "job_id": self.version_job,
                "request_id": payload["request_id"],
                "chat_id": self.chat_id,
                "turn_id": turn,
                "assistant_message_id": self.version_assistant,
                "chat_key_version": 1,
                "state": "LEASED",
                "lease_token": self.version_lease,
                "lease_generation": 1,
                "sealed_payload": json.dumps(
                    seal(
                        self.admission["recovery_public_key"], identity, content, False
                    )
                ),
            },
        )

    def persist_version(self, socket, payload):
        assert payload["job_id"] == self.version_job
        assert (
            payload["lease_token"] == self.version_lease
            and payload["lease_generation"] == 1
        )
        assert (
            payload["expected_messages_v"]
            == len(self.saved_messages[self.chat_id])
            == 1
        )
        message = payload["encrypted_assistant_message"]
        assert (
            message["chat_id"] == self.chat_id
            and message["client_message_id"] == self.version_assistant
        )
        assert (
            decrypt(message["encrypted_content"], self.key).decode()
            == self.version_content
        )
        assert self.version_content not in json.dumps(payload)
        self.saved_messages[self.chat_id].append(copy.deepcopy(message))
        with self._lock:
            self.counts["persists"] += 1
        socket.send(
            "recovery_job_persisted",
            {
                "job_id": self.version_job,
                "state": "TERMINAL",
                "committed_messages_v": 2,
            },
        )
