"""Pure scripted transport checks for the maintained synthetic CLI peer.

No SDK/product/network execution; verifies the authored peer does not fabricate
phased-sync responses to get the selected no-sync regression past discovery.
"""

# contract-test-file: tooling
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(
    os.environ.get(
        "OPENMATES_LATENCY_SOURCE_ROOT", str(Path(__file__).resolve().parents[4])
    )
)
PEER = Path(
    os.environ.get(
        "OPENMATES_LATENCY_PEER",
        str(
            ROOT
            / "frontend/packages/openmates-tui-native/tests/support/saved_read_recovery_peer.py"
        ),
    )
)
sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
spec = importlib.util.spec_from_file_location("latency_saved_read_peer", PEER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ScriptedSocket:
    def __init__(self, foreground, inventory):
        self.sent = []
        self.events = [
            {
                "type": "native_client_lifecycle",
                "payload": {
                    "client_type": "cli",
                    "interactive": False,
                    "is_foreground": foreground,
                },
            }
        ]
        self.handler = SimpleNamespace(
            complete_task_inventory=inventory,
            inventory_request_id=None,
            connection=SimpleNamespace(settimeout=lambda value: None),
        )

    def receive(self):
        return self.events.pop(0) if self.events else None

    def send(self, kind, payload):
        self.sent.append((kind, payload))

    def raw(self, opcode, data):
        raise AssertionError("No real socket frames allowed")


class StartupDiscovery(unittest.TestCase):
    def peer(self, terminal=False):
        # Bypass constructor deliberately: it binds a socket. These checks run
        # only the actual peer's websocket policy with scripted transport.
        peer = object.__new__(module.CliPeer)
        peer.protocol = json.loads(
            (
                ROOT
                / "tests/sdk-conformance/fixtures/session-foreground-completion-recovery.json"
            ).read_text()
        )["capabilities"][module.RECOVERY]["protocol"]
        peer.chat_id = peer.protocol["initial_chat_id"]
        peer.mode = "main"
        peer.identity = "cli"
        peer.terminal = terminal
        peer.monitors = []
        peer.failure = None
        peer.checks = set()
        peer.counts = dict(
            connections=0,
            claims=0,
            persists=0,
            admissions=0,
            inventory_syncs=0,
            inventory_discovery=0,
            metadata_discovery=0,
            monitor_disconnects=0,
            claimed_socket_disconnects=0,
        )
        return peer

    def run_peer(self, foreground=True, inventory=False, terminal=False):
        peer = self.peer(terminal)
        transport = ScriptedSocket(foreground, inventory)
        peer.websocket(transport)
        self.assertIsNone(peer.failure)
        self.assertEqual(peer.counts["claims"], 0)
        self.assertEqual(peer.counts["persists"], 0)
        self.assertEqual(peer.counts["inventory_syncs"], 0)
        return peer, transport

    def test_selected_startup_finishes_without_phased_request(self):
        peer, transport = self.run_peer()
        kinds = [kind for kind, _ in transport.sent]
        self.assertEqual(
            kinds,
            [
                "recovery_jobs_available",
                "metadata_jobs_available",
                "recovery_outputs_available",
                "recovery_outputs_discovery_complete",
                "native_client_lifecycle_ack",
            ],
        )
        self.assertEqual(len(transport.sent[0][1]["jobs"]), 1)
        self.assertEqual(peer.counts["startup_recovery_discovery"], 1)

    def test_terminal_empty_offer_is_explicit(self):
        _, transport = self.run_peer(terminal=True)
        self.assertEqual(transport.sent[0][1]["jobs"], [])
        self.assertEqual(transport.sent[3][1], {"status": "completed"})

    def test_passive_does_not_offer_claimable_work(self):
        _, transport = self.run_peer(foreground=False)
        self.assertEqual(
            [kind for kind, _ in transport.sent], ["native_client_lifecycle_ack"]
        )

    def test_inventory_fixture_keeps_its_original_correlated_discovery(self):
        _, transport = self.run_peer(inventory=True)
        self.assertEqual(
            [kind for kind, _ in transport.sent], ["native_client_lifecycle_ack"]
        )


if __name__ == "__main__":
    # Enforce the pure-harness scope, including accidental constructors/listeners.
    socket.socket = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("network forbidden")
    )
    unittest.main()
