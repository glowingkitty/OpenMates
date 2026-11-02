#!/usr/bin/env python3
"""Independent startup protocol peer for actual Rust/NAPI/PyO3 library calls.

Synthetic explicit credentials only. No product, AI or external account IO.
"""

import argparse
import json
from pathlib import Path

from essential_session_server import EssentialPeer

CAPABILITY = "session.initial-startup-sync.v1"


class StartupPeer(EssentialPeer):
    def __init__(self, suite, vector, identity):
        super().__init__(suite, vector, identity)
        self.counts.update(
            startup_requests=0,
            metadata_requests=0,
            startup_terminals=0,
            unexpected_frames=0,
        )

    def websocket(self, socket):
        socket.handler.connection.settimeout(5)
        self.counts["connections"] += 1
        terminal_sent = False
        startup_epoch = None
        try:
            while (frame := socket.receive()) is not None:
                kind, payload = frame["type"], frame["payload"]
                if kind == "native_client_lifecycle":
                    assert (
                        payload["client_type"] == self.identity
                        and payload["interactive"] is False
                    )
                    assert payload["is_foreground"] is False
                    socket.send("native_client_lifecycle_ack", {"is_foreground": False})
                    socket.send(
                        "recovery_outputs_discovery_complete", {"status": "disabled"}
                    )
                    self.mark("real-sdk-identity")
                elif kind == "phased_sync_request":
                    self.counts["startup_requests"] += 1
                    assert self.counts["startup_requests"] == 1, (
                        "one initial dispatch per original socket"
                    )
                    assert payload["phase"] == "all"
                    epoch = payload["context_epoch"]
                    assert type(epoch) is int and epoch > 0
                    startup_epoch = epoch
                    common = {"context_epoch": epoch, "team_id": None}
                    phase2 = {**common, "chats": [{"chat_details": self.row()}]}
                    if "total_chat_count" in self.vector:
                        phase2["total_chat_count"] = self.vector["total_chat_count"]
                    socket.send("phase_2_last_20_chats_ready", phase2)
                    socket.send("phase_3_chunk_ready", {**common, "chats": []})
                    socket.send("phased_sync_complete", {**common, "phase": "all"})
                    terminal_sent = True
                    self.counts["startup_terminals"] += 1
                    self.mark("actual-startup-terminal")
                elif kind == "sync_metadata_chats":
                    self.counts["metadata_requests"] += 1
                    assert terminal_sent and self.counts["metadata_requests"] == 1
                    assert self.vector.get("total_chat_count", 0) > 100
                    assert payload["existing_chat_ids"] == [], (
                        "no caller inventory substitutes for original Client DATA"
                    )
                    epoch = payload["context_epoch"]
                    assert epoch == startup_epoch, (
                        "metadata must retain the original startup request context"
                    )
                    page = {
                        "context_epoch": epoch,
                        "team_id": None,
                        "total_count": 1234,
                        "chats": [
                            {
                                "chat_details": {
                                    **self.row(),
                                    "id": "70000000-0000-4000-8000-000000000001",
                                }
                            }
                        ],
                    }
                    self.mark("metadata-after-original-terminal")
                    if self.mode == "startup_cancel_inflight":
                        continue
                    if self.mode == "startup_foreign_context":
                        socket.send(
                            "sync_metadata_chats_response",
                            {**page, "context_epoch": epoch - 1},
                        )
                        self.mark("foreign-context-offered")
                        continue
                    if self.mode == "startup_server_error":
                        socket.send(
                            "sync_metadata_chats_response",
                            {
                                "context_epoch": epoch,
                                "team_id": None,
                                "error": "synthetic-error",
                            },
                        )
                    else:
                        socket.send("sync_metadata_chats_response", page)
                    self.mark("actual-metadata-response")
                else:
                    self.counts["unexpected_frames"] += 1
                    raise AssertionError(
                        "startup cannot claim, persist, ACK or fetch extra messages"
                    )
        finally:
            self.counts["monitor_disconnects"] += 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--capability", required=True, choices=[CAPABILITY])
    parser.add_argument("--vector", required=True)
    parser.add_argument("--identity", required=True, choices=["rust", "npm", "pip"])
    args = parser.parse_args()
    suite = json.loads(args.fixture.read_bytes())["capabilities"][args.capability]
    vector = next(item for item in suite["vectors"] if item["id"] == args.vector)
    peer = StartupPeer(suite, vector, args.identity)
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    try:
        peer.server.serve_forever()
    finally:
        peer.server.server_close()


if __name__ == "__main__":
    main()
