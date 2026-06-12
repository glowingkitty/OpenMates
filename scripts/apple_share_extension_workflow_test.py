#!/usr/bin/env python3
# Run the iOS Safari-to-OpenMates share-extension workflow test.
# The simulator cannot prove real APNs delivery, so this helper coordinates the
# native XCUITest with a host-side `simctl push` using the same generic payload
# shape as the server notification path. Credentials stay in environment
# variables consumed by xcodebuild/XCTest and are never printed by this script.
# Keep this runner narrow: it exists only for the Apple share extension E2E.

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
ONLY_TESTING = (
    "OpenMatesUITests/ChatManagementSharingParityUITests/"
    "testSafariShareSheetSendsURLThroughOpenMatesExtension"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulator", default=DEFAULT_SIMULATOR)
    parser.add_argument(
        "--push-delay",
        type=int,
        default=105,
        help="Seconds to wait after xcodebuild starts before injecting simctl push.",
    )
    parser.add_argument("--skip-uninstall", action="store_true")
    parser.add_argument("--skip-push", action="store_true")
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
        "chat_id": "simulated-share-extension-chat",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def run_uninstall(bundle_id: str) -> None:
    subprocess.run(
        ["xcrun", "simctl", "uninstall", "booted", bundle_id],
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


def run_xcodebuild(simulator: str, expect_notification: bool) -> int:
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
    if expect_notification:
        env["OPENMATES_SHARE_WORKFLOW_EXPECT_NOTIFICATION"] = "1"
    return subprocess.run(command, env=env, check=False).returncode


def main() -> int:
    args = parse_args()
    if not args.skip_uninstall:
        run_uninstall(APP_BUNDLE_ID)
        run_uninstall("com.apple.mobilesafari")

    if args.skip_push:
        return run_xcodebuild(args.simulator, expect_notification=False)

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
        return run_xcodebuild(args.simulator, expect_notification=True)
    finally:
        payload_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
