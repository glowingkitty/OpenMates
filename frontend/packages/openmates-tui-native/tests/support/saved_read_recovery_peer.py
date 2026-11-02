#!/usr/bin/env python3
"""Native CLI-only synthetic peer. Never imported by production code."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
# Reuse the independent test protocol/crypto implementation, not SDK code.
from essential_session_server import EssentialPeer, RECOVERY  # noqa: E402
from recovery_server import RecoveryPeer, encrypt  # noqa: E402


class CliPeer(EssentialPeer):
    def __init__(self, *args):
        super().__init__(*args)
        self.counts.update(
            auth_checks=0,
            inventory_syncs=0,
            inventory_discovery=0,
            metadata_discovery=0,
            task_inventory_discovery=0,
            phase2_inventory_syncs=0,
        )

    def structured_vector(self):
        path = Path(__file__).resolve().parents[1] / "fixtures/chats-show-json.json"
        return json.loads(path.read_text())["vectors"][1]["expected"]

    def structured_row(self):
        expected = self.structured_vector()["chat"]
        row = {
            "id": self.chat_id,
            "encrypted_chat_key": self.wrapped,
            "messages_v": 65,
            "created_at": str(expected["createdAt"]),
            "last_edited_overall_timestamp": str(expected["updatedAt"]),
            "updated_at": str(expected["metadataUpdatedAt"]),
            "participant_user_hashes": expected["participantUserHashes"],
            "is_sub_chat": False,
            "is_hidden": False,
            "pinned": True,
            "encrypted_draft_md": encrypt(b"Saved synthetic draft", self.master),
        }
        for target, field in [
            ("title", "encrypted_title"),
            ("summary", "encrypted_chat_summary"),
            ("slug", "encrypted_slug"),
            ("category", "encrypted_category"),
        ]:
            row[field] = encrypt(expected[target].encode(), self.key)
        focus = getattr(self, "structured_focus", None)
        if focus is not None:
            row["encrypted_active_focus_id"] = encrypt(focus.encode(), self.key)
        team = getattr(self, "structured_team", None)
        if team:
            row.update(
                team_id=team,
                chat_visibility="team",
                chat_key_wrappers=[
                    {
                        "hashed_chat_id": hashlib.sha256(
                            self.chat_id.encode()
                        ).hexdigest(),
                        "hashed_team_id": hashlib.sha256(team.encode()).hexdigest(),
                        "key_type": "team",
                        "encrypted_chat_key": encrypt(
                            self.key, self.structured_team_key
                        ),
                    }
                ],
            )
        return row

    def structured_messages(self):
        rows = []
        fields = {
            "content": "encrypted_content",
            "senderName": "encrypted_sender_name",
            "category": "encrypted_category",
            "modelName": "encrypted_model_name",
        }
        for message in self.structured_vector()["messages"]:
            row = {
                "id": message["id"],
                "client_message_id": message["clientMessageId"],
                "chat_id": self.chat_id,
                "role": message["role"],
                "created_at": message["createdAt"],
                "status": "sent",
            }
            if message["hashedSenderUserId"] is not None:
                row["hashed_user_id"] = message["hashedSenderUserId"]
            for source, target in fields.items():
                if message[source] is not None:
                    row[target] = encrypt(message[source].encode(), self.key)
            if "piiMappings" in message:
                row["encrypted_pii_mappings"] = encrypt(
                    json.dumps(message["piiMappings"]).encode(), self.key
                )
            rows.append(row)
        return rows

    def structured_window(self, query):
        direction = query.get("direction", ["latest"])[0]
        limit = int(query["limit"][0])
        assert direction in {"latest", "before"} and 1 <= limit <= 100
        rows = self.messages
        if direction == "before":
            stamp = int(query["before_timestamp"][0])
            identity = query["before_message_id"][0]
            rows = [
                r
                for r in rows
                if (r["created_at"], r["client_message_id"]) < (stamp, identity)
            ]
        selected = rows[-min(limit, 20) :]

        def cursor(row):
            return {
                "created_at": row["created_at"],
                "message_id": row["client_message_id"],
            }

        compression = query.get("respect_compression_boundary", ["true"])[0]
        assert compression in {"true", "false"}
        self.counts["structured_window_reads"].append(
            {
                "direction": direction,
                "limit": limit,
                "respect_compression_boundary": compression == "true",
                "returned": len(selected),
            }
        )
        return {
            "messages": selected,
            "has_more_before": len(rows) > len(selected),
            "has_more_after": False,
            "anchor_found": True,
            "start_cursor": cursor(selected[0]) if selected else None,
            "end_cursor": cursor(selected[-1]) if selected else None,
            "server_message_count": 65,
            "messages_v": 65,
            "oversized_message": False,
            "oversized_message_cursor": None,
            "payload_bytes": sum(
                len(
                    json.dumps(row, separators=(",", ":"), ensure_ascii=False).encode(
                        "utf-8"
                    )
                )
                for row in selected
            ),
        }

    def row(self):
        if getattr(self, "structured", False):
            return self.structured_row()
        row = super().row()
        # Optional synthetic data only; same authenticated metadata protocol.
        # Independent peer encryption proves final JSON used saved ciphertext.
        slug = getattr(self, "full_chat_slug", None)
        if slug is not None:
            row["encrypted_slug"] = encrypt(slug.encode(), self.key)
        return row

    def control(self, action):
        if action in {
            "structured-history",
            "structured-history-team",
            "structured-history-focus",
            "structured-history-focus-team",
            "structured-history-focus-space",
            "structured-history-focus-space-team",
        }:
            self.structured = True
            self.structured_focus = (
                "   "
                if "focus-space" in action
                else "synthetic-focus-雪"
                if "focus" in action
                else None
            )
            self.structured_team = (
                "33333333-3333-4333-8333-333333333333"
                if action.endswith("-team")
                else None
            )
            self.structured_team_key = bytes([83]) * 32
            self.terminal = True
            self.version = 65
            self.messages = self.structured_messages()
            self.counts["structured_window_reads"] = []
            self.counts["structured_embed_reads"] = 0
            self.counts["structured_detail_reads"] = 0
            return {"success": True}
        if action == "no-recovery":
            self.terminal = True
            return {"success": True}
        return super().control(action)

    def validate_sync_phase(self, socket, payload):
        if payload["phase"] != "phase2":
            return super().validate_sync_phase(socket, payload)
        # Only the exact inventory-capable native socket admitted in do_GET may
        # use metadata-only discovery. Ordinary/foreground reads still use all.
        request_id = getattr(socket.handler, "inventory_request_id", None)
        assert getattr(socket.handler, "complete_task_inventory", False)
        assert (
            request_id is not None and payload.get("inventory_request_id") == request_id
        )
        self.counts["phase2_inventory_syncs"] += 1

    def websocket(self, socket):
        original_send = socket.send

        def counted_send(kind, payload):
            request_id = getattr(socket.handler, "inventory_request_id", None)
            if request_id is not None and kind in {
                "recovery_jobs_available",
                "metadata_jobs_available",
                "task_update_jobs_available",
                "recovery_outputs_available",
                "recovery_outputs_discovery_complete",
                "phase_1_last_chat_ready",
                "phase_1b_messages_ready",
                "phase_2_last_20_chats_ready",
                "background_message_sync",
                "phased_sync_complete",
                "app_settings_memories_sync_ready",
            }:
                payload = {**payload, "inventory_request_id": request_id}
            for frame, counter in (
                ("phase_2_last_20_chats_ready", "inventory_syncs"),
                ("recovery_outputs_discovery_complete", "inventory_discovery"),
                ("metadata_jobs_available", "metadata_discovery"),
            ):
                if kind == frame:
                    self.counts[counter] += 1
            result = original_send(kind, payload)
            if kind == "phase_2_last_20_chats_ready" and getattr(
                socket.handler, "complete_task_inventory", False
            ):
                # Match the opt-in backend's strict successful empty offer. The
                # backend draft tests separately reject scan/read failure.
                original_send(
                    "task_update_jobs_available",
                    {
                        "jobs": [],
                        "complete": True,
                        "inventory_request_id": socket.handler.inventory_request_id,
                    },
                )
                self.counts["task_inventory_discovery"] += 1
            return result

        socket.send = counted_send
        original_receive = socket.receive

        def correlated_receive():
            event = original_receive()
            if (
                event
                and event["type"] == "native_client_lifecycle"
                and event["payload"].get("is_foreground") is True
                and not getattr(socket.handler, "complete_task_inventory", False)
            ):
                # Match maintained backend startup discovery, independently of
                # any phased_sync_request. Keep global-sync counters measuring
                # explicit phase responses; startup offers have their own count.
                self.counts["startup_recovery_discovery"] = (
                    self.counts.get("startup_recovery_discovery", 0) + 1
                )
                original_send(
                    "recovery_jobs_available",
                    {"jobs": [] if self.terminal else [self.job()]},
                )
                original_send("metadata_jobs_available", {"jobs": []})
                original_send("recovery_outputs_available", {"outputs": []})
                original_send(
                    "recovery_outputs_discovery_complete", {"status": "completed"}
                )
            if (
                event
                and event["type"] in {"metadata_jobs_request", "phased_sync_request"}
                and getattr(socket.handler, "inventory_request_id", None) is not None
            ):
                assert (
                    event["payload"].get("inventory_request_id")
                    == socket.handler.inventory_request_id
                )
            return event

        socket.receive = correlated_receive
        request_id = getattr(socket.handler, "inventory_request_id", None)
        if request_id is not None:
            original_send(
                "server_capabilities",
                {"capabilities": [], "inventory_request_id": request_id},
            )
        return super().websocket(socket)

    def handler(self):
        parent = super().handler()
        transport = RecoveryPeer.handler(self)
        peer = self

        class Handler(parent):
            def do_POST(self):
                if urlsplit(self.path).path == "/v1/chats/metadata/batch":
                    peer.headers(self)
                    length = int(self.headers["Content-Length"])
                    assert 0 < length < 65536
                    payload = json.loads(self.rfile.read(length))
                    assert payload in (
                        {"chat_ids": [peer.chat_id]},
                        {"chat_ids": [peer.chat_id], "include_read_details": True},
                    )
                    if peer.denied:
                        self.response(403, {"detail": "Forbidden"})
                        return
                    row = peer.row()
                    # Preserve the ordinary metadata shape: the new selected
                    # projection is opt-in and uses the same authenticated row.
                    if payload.get("include_read_details") is True:
                        details = {
                            "created_at": None,
                            "updated_at": None,
                            "last_edited_overall_timestamp": None,
                            "encrypted_follow_up_request_suggestions": None,
                        }
                        if getattr(peer, "structured", False):
                            expected = peer.structured_vector()["chat"]
                            details.update(
                                created_at=expected["createdAt"],
                                updated_at=expected["metadataUpdatedAt"],
                                last_edited_overall_timestamp=expected["updatedAt"],
                                encrypted_follow_up_request_suggestions=encrypt(
                                    json.dumps(
                                        [
                                            "[legacy] Explore the saved result",
                                            "Continue with 雪",
                                            "[empty] ",
                                        ]
                                    ).encode(),
                                    peer.key,
                                ),
                            )
                            peer.counts["structured_detail_reads"] += 1
                        row["read_details"] = details
                    peer.mark("fresh-metadata-reread")
                    self.response(200, {"chats": [row]})
                    return
                if urlsplit(self.path).path == "/v1/auth/session":
                    peer.counts["auth_checks"] += 1
                return super().do_POST()

            def do_GET(self):
                route = urlsplit(self.path)
                if getattr(peer, "structured", False):
                    team = getattr(peer, "structured_team", None)
                    if route.path == f"/v1/teams/{team}" and team:
                        peer.headers(self)
                        self.response(
                            200,
                            {
                                "team": {
                                    "team_id": team,
                                    "encrypted_team_key": encrypt(
                                        peer.structured_team_key, peer.master
                                    ),
                                }
                            },
                        )
                        return
                    if route.path == f"/v1/chats/{peer.chat_id}/messages/window":
                        peer.headers(self)
                        self.response(
                            200, peer.structured_window(parse_qs(route.query))
                        )
                        return
                    if route.path == f"/v1/embeds/chats/{peer.chat_id}/window":
                        peer.headers(self)
                        peer.counts["structured_embed_reads"] += 1
                        message_id = peer.structured_vector()["messages"][-2][
                            "clientMessageId"
                        ]
                        embed = {
                            "embed_id": "synthetic-embed-64",
                            "id": "synthetic-embed-64",
                            "hashed_chat_id": hashlib.sha256(
                                peer.chat_id.encode()
                            ).hexdigest(),
                            "hashed_message_id": hashlib.sha256(
                                message_id.encode()
                            ).hexdigest(),
                            "parent_embed_id": None,
                            "created_at": 1700000064,
                        }
                        self.response(
                            200,
                            {
                                "chat_id": peer.chat_id,
                                "embeds": [embed],
                                "embed_keys": [],
                                "embed_keys_has_more_after": False,
                                "embed_keys_end_cursor": None,
                                "oversized_embed_key_id": None,
                                "has_more_before": False,
                                "start_cursor": {
                                    "created_at": 1700000064,
                                    "id": "synthetic-embed-64",
                                },
                                "oversized_embed_id": None,
                                "oversized_embed_cursor": None,
                            },
                        )
                        return
                if route.path == f"/v1/chats/{peer.chat_id}/messages/window":
                    # Ordinary recovery fixtures predate selected rich reads.
                    # Match the real REST byte-accounting contract while keeping
                    # the inherited canonical ciphertext and recovery checks.
                    peer.headers(self)
                    query = parse_qs(route.query)
                    assert query.get("direction") == ["latest"]
                    limit = int(query["limit"][0])
                    assert 1 <= limit <= 100
                    assert query.get("respect_compression_boundary") in (
                        ["true"],
                        ["false"],
                    )
                    rows = peer.messages[-min(limit, 20) :]

                    def cursor(row):
                        return {
                            "created_at": row["created_at"],
                            "message_id": row.get("client_message_id")
                            or row.get("message_id")
                            or row["id"],
                        }

                    self.response(
                        200,
                        {
                            "chat_id": peer.chat_id,
                            "messages": rows,
                            "has_more_before": len(peer.messages) > len(rows),
                            "has_more_after": False,
                            "start_cursor": cursor(rows[0]) if rows else None,
                            "end_cursor": cursor(rows[-1]) if rows else None,
                            "anchor_found": True,
                            "oversized_message": False,
                            "oversized_message_cursor": None,
                            "payload_bytes": sum(
                                len(
                                    json.dumps(
                                        row, separators=(",", ":"), ensure_ascii=False
                                    ).encode("utf-8")
                                )
                                for row in rows
                            ),
                        },
                    )
                    peer.mark("canonical-message-reread")
                    return
                if route.path == f"/v1/embeds/chats/{peer.chat_id}/window":
                    # Main-message recovery creates no saved embed rows. Rich
                    # reads still authenticate the actual empty inventory route.
                    peer.headers(self)
                    self.response(
                        200,
                        {
                            "chat_id": peer.chat_id,
                            "embeds": [],
                            "embed_keys": [],
                            "embed_keys_has_more_after": False,
                            "embed_keys_end_cursor": None,
                            "oversized_embed_key_id": None,
                            "has_more_before": False,
                            "start_cursor": None,
                            "oversized_embed_id": None,
                            "oversized_embed_cursor": None,
                        },
                    )
                    return
                if route.path == "/v1/ws":
                    capabilities = set(
                        parse_qs(urlsplit(self.path).query)
                        .get("client_capabilities", [""])[0]
                        .split(",")
                    )
                    expected = {
                        "canonical_embed_receipts_v1",
                        "typed_recovery_outputs_v2",
                        "agentic-storage-v2",
                    }
                    # Saved reads use ordinary task-capable sockets after the
                    # explicit recovery pump disables its foreground opt-in.
                    # Keep the reusable EssentialPeer's recovery-only rule
                    # intact and check both exact native capability sets here.
                    expected.add(
                        "chat_metadata_recovery"
                        if "chat_metadata_recovery" in capabilities
                        else "task_update_jobs"
                    )
                    self.complete_task_inventory = (
                        "task_update_jobs_inventory_v1" in capabilities
                    )
                    self.inventory_request_id = None
                    if self.complete_task_inventory:
                        expected.update(
                            {
                                "task_update_jobs",
                                "task_update_jobs_inventory_v1",
                                "chat_metadata_recovery",
                            }
                        )
                        request_id = parse_qs(urlsplit(self.path).query).get(
                            "inventory_request_id", [None]
                        )[0]
                        assert isinstance(request_id, str)
                        parsed = uuid.UUID(request_id)
                        assert parsed.version == 4 and str(parsed) == request_id
                        self.inventory_request_id = request_id
                    assert capabilities == expected, "native read capabilities"
                    transport.do_GET(self)
                    return
                if self.path.startswith("/v1/teams/"):
                    peer.headers(self)
                    team = self.path.split("/", 4)[3].split("?", 1)[0]
                    peer.counts["denied_team"] = team
                    self.response(403, {"detail": "synthetic membership denied"})
                    return
                super().do_GET()

        return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vector", required=True)
    parser.add_argument("--full-chat-slug")
    args = parser.parse_args()
    fixture = (
        ROOT
        / "tests/sdk-conformance/fixtures/session-foreground-completion-recovery.json"
    )
    suite = json.loads(fixture.read_text())["capabilities"][RECOVERY]
    vector = next(item for item in suite["vectors"] if item["id"] == args.vector)
    # The reusable fixture's constructor admits three library labels only.
    # Initialization derives test data and opens a loopback listener; no SDK
    # request is admitted until this process publishes its endpoint below.
    # Expect the genuine CLI identity on EVERY later HTTP/WS frame. This does
    # not alter/spoof the Client identity under test or run CLI/profile discovery.
    peer = CliPeer(suite, vector, "rust")
    peer.identity = "cli"
    peer.full_chat_slug = args.full_chat_slug
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    try:
        peer.server.serve_forever()
    finally:
        peer.server.server_close()


if __name__ == "__main__":
    main()
