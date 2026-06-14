#!/usr/bin/env python3
"""Run the Apple background-notification simulator test with a simulated push.

The simulator cannot prove real APNs delivery from OpenMates servers without a
paid Apple Developer team and a physical device token. This helper runs the
native XCUITest that sends a real chat and presses Home, then injects a generic
server-shaped APNs payload with `xcrun simctl push` while the test waits on
SpringBoard. It never reads or prints credential values; pass the standard
OPENMATES_TEST_ACCOUNT_* environment variables to xcodebuild.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


PROJECT_PATH = "apple/OpenMates.xcodeproj"
SCHEME = "OpenMates_iOS"
DEFAULT_SIMULATOR = "iPhone 17"
APP_BUNDLE_ID = "org.openmates.app"
ONLY_TESTING = "OpenMatesUITests/BackgroundChatNotificationUITests"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulator", default=DEFAULT_SIMULATOR)
    parser.add_argument(
        "--push-delay",
        type=int,
        default=75,
        help="Seconds to wait after xcodebuild starts before injecting simctl push.",
    )
    parser.add_argument("--skip-uninstall", action="store_true")
    return parser.parse_args()


def write_payload(path: Path) -> None:
    payload = {
        "Simulator Target Bundle": APP_BUNDLE_ID,
        "aps": {
            "alert": {
                "title": "OpenMates",
                "body": "New message received",
            },
            "sound": "default",
            "category": "OPENMATES_CHAT_MESSAGE",
        },
        "chat_id": "simulated-background-chat",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def run_uninstall() -> None:
    subprocess.run(
        ["xcrun", "simctl", "uninstall", "booted", APP_BUNDLE_ID],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def inject_push_after_delay(payload_path: Path, delay: int) -> None:
    time.sleep(delay)
    result = subprocess.run(
        ["xcrun", "simctl", "push", "booted", APP_BUNDLE_ID, str(payload_path)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.stdout:
        print(result.stdout.strip())
    if result.returncode != 0:
        print(f"simctl push failed with exit code {result.returncode}", file=sys.stderr)


def run_xcodebuild(simulator: str) -> int:
    command = [
        "xcodebuild",
        "test",
        "-project",
        PROJECT_PATH,
        "-scheme",
        SCHEME,
        "-destination",
        f"platform=iOS Simulator,name={simulator}",
        "-only-testing",
        ONLY_TESTING,
    ]
    env = os.environ.copy()
    return subprocess.run(command, env=env, check=False).returncode


def main() -> int:
    args = parse_args()
    if not args.skip_uninstall:
        run_uninstall()

    with tempfile.NamedTemporaryFile("w", suffix=".apns", delete=False) as tmp:
        payload_path = Path(tmp.name)
    try:
        write_payload(payload_path)
        thread = threading.Thread(
            target=inject_push_after_delay,
            args=(payload_path, args.push_delay),
            daemon=True,
        )
        thread.start()
        return run_xcodebuild(args.simulator)
    finally:
        payload_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
