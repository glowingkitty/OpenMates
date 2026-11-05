"""Pure native recovery-peer phase admission: no listeners or product requests."""

# contract-test-file: tooling
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "frontend/packages/openmates-tui-native/tests/support"))
from saved_read_recovery_peer import CliPeer  # noqa: E402 - import follows sys.path setup for sibling runner modules
from essential_session_server import EssentialPeer, RECOVERY  # noqa: E402 - import follows sys.path setup for sibling runner modules

REQUEST = "11111111-1111-4111-8111-111111111111"
FOREIGN = "22222222-2222-4222-8222-222222222222"


class SavedReadRecoveryPhaseTests(unittest.TestCase):
    def peer(self, cls=CliPeer):
        suite = json.loads(
            (
                ROOT
                / "tests/sdk-conformance/fixtures/session-foreground-completion-recovery.json"
            ).read_text()
        )["capabilities"][RECOVERY]
        with patch("recovery_server.ThreadingHTTPServer"):
            return cls(suite, {"mode": "main"}, "rust")

    def socket(
        self, phase="phase2", *, opted_in=True, request_id=REQUEST, payload_id=REQUEST
    ):
        socket = SimpleNamespace(
            handler=SimpleNamespace(
                connection=SimpleNamespace(settimeout=lambda _: None),
                complete_task_inventory=opted_in,
                inventory_request_id=request_id,
            ),
            raw=lambda *_: None,
            frames=[],
        )
        socket.send = lambda kind, payload: socket.frames.append((kind, payload))
        events = iter(
            [
                {
                    "type": "metadata_jobs_request",
                    "payload": {"inventory_request_id": payload_id},
                },
                {
                    "type": "phased_sync_request",
                    "payload": {"phase": phase, "inventory_request_id": payload_id},
                },
            ]
        )
        socket.receive = lambda: next(events, None)
        return socket

    def test_correlated_phase2_delivers_all_three_inventories_and_terminal_fences_without_content(
        self,
    ):
        peer = self.peer()
        # One canonical stored row: row() encrypts with a fresh random IV.
        row = peer.row()
        peer.row = lambda: row
        socket = self.socket()
        peer.websocket(socket)
        self.assertIsNone(peer.failure)
        self.assertEqual(peer.counts["phase2_inventory_syncs"], 1)
        frames = dict(socket.frames)
        for kind in (
            "metadata_jobs_available",
            "recovery_jobs_available",
            "task_update_jobs_available",
            "phase_2_last_20_chats_ready",
            "phased_sync_complete",
            "recovery_outputs_discovery_complete",
        ):
            self.assertEqual(frames[kind]["inventory_request_id"], REQUEST)
        self.assertEqual(
            frames["task_update_jobs_available"],
            {"jobs": [], "complete": True, "inventory_request_id": REQUEST},
        )
        self.assertEqual(frames["phased_sync_complete"]["phase"], "phase2")
        self.assertEqual(
            frames["recovery_outputs_discovery_complete"]["status"], "completed"
        )
        self.assertEqual(
            frames["phase_2_last_20_chats_ready"]["chats"],
            [{"chat_details": peer.row()}],
        )
        self.assertFalse(
            {
                "phase_1_last_chat_ready",
                "phase_1b_messages_ready",
                "background_message_sync",
            }
            & frames.keys()
        )
        self.assertEqual(peer.counts["claims"], 0)
        self.assertEqual(peer.counts["persists"], 0)

    def test_phase2_rejects_missing_opt_in_missing_id_foreign_id_and_unknown_phase(
        self,
    ):
        for options in (
            {"opted_in": False},
            {"request_id": None},
            {"payload_id": FOREIGN},
            {"phase": "phase3"},
        ):
            with self.subTest(options=options):
                peer = self.peer()
                socket = self.socket(**options)
                peer.websocket(socket)
                self.assertEqual(peer.failure, "essential-protocol")
                kinds = {kind for kind, _ in socket.frames}
                self.assertNotIn("phased_sync_complete", kinds)
                self.assertNotIn("recovery_outputs_discovery_complete", kinds)
                self.assertEqual(peer.counts["phase2_inventory_syncs"], 0)

    def test_shared_peer_remains_all_only_and_native_all_path_keeps_original_completion(
        self,
    ):
        shared = self.peer(EssentialPeer)
        socket = self.socket()
        shared.websocket(socket)
        self.assertEqual(shared.failure, "essential-protocol")
        native = self.peer()
        socket = self.socket("all", opted_in=False, request_id=None, payload_id=None)
        native.websocket(socket)
        self.assertIsNone(native.failure)
        self.assertEqual(native.counts["phase2_inventory_syncs"], 0)
        self.assertEqual(dict(socket.frames)["phased_sync_complete"], {})


if __name__ == "__main__":
    unittest.main()
