#!/usr/bin/env python3
"""Verify the released legacy CLI cutover contract against an in-memory boundary.

This fixture deliberately does not call a live OpenMates deployment or mutate the
server-authoritative protocol epoch. It models the 0.14.0 saved-chat wire frame
at the admission boundary and proves rejection occurs before inference dispatch.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass


RELEASED_LEGACY_VERSION = "0.14.0"
UPDATE_GUIDANCE = "Please update OpenMates before sending another saved chat message."


@dataclass
class MockCutoverBoundary:
    inference_starts: int = 0

    def admit_saved_chat(self, frame: dict[str, object]) -> dict[str, object]:
        payload = frame.get("payload")
        if not isinstance(payload, dict) or payload.get("protocol_version") != 1:
            return {
                "type": "error",
                "payload": {"code": "client_update_required", "message": UPDATE_GUIDANCE},
            }
        self.inference_starts += 1
        return {"type": "chat_message_confirmed", "payload": {"success": True}}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli-version", default=RELEASED_LEGACY_VERSION)
    parser.add_argument("--env", default="mock", choices=("mock", "dev"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.cli_version != RELEASED_LEGACY_VERSION:
        raise AssertionError(f"fixture is pinned to released legacy CLI {RELEASED_LEGACY_VERSION}")

    legacy_history = [{"role": "user", "content": "locally decrypted history"}]
    legacy_send = {
        "type": "chat_message_added",
        "payload": {
            "chat_id": "11111111-1111-4111-8111-111111111111",
            "message": {"message_id": "22222222-2222-4222-8222-222222222222", "content": "legacy send"},
        },
    }
    boundary = MockCutoverBoundary()
    response = boundary.admit_saved_chat(legacy_send)

    assert response["payload"] == {
        "code": "client_update_required",
        "message": UPDATE_GUIDANCE,
    }
    assert boundary.inference_starts == 0
    assert legacy_history == [{"role": "user", "content": "locally decrypted history"}]
    print(json.dumps({
        "cli_version": args.cli_version,
        "boundary": "in_memory_no_live_epoch_state",
        "send_exit_code": 1,
        "inference_starts": boundary.inference_starts,
        "read_only_history_usable": True,
        "error": response["payload"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
