#!/usr/bin/env python3
"""Run simulator-backed Apple background notification interaction coverage.

The simulator can inject an APNs-shaped payload, but cannot prove provider
acceptance, token registration, or notification-extension/keychain behavior.
This helper exchanges per-scenario requests with the XCUITest so pushes are
injected only after the app has reached the intended foreground/background
state. It never prints account credentials, notification replies, or chat IDs.
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

# contract-test-file: infrastructure


PROJECT_PATH = "apple/OpenMates.xcodeproj"
SCHEME = "OpenMates_iOS"
DEFAULT_SIMULATOR = "iPhone 17"
APP_BUNDLE_ID = "org.openmates.app"
ONLY_TESTING = "OpenMatesUITests/BackgroundChatNotificationUITests"
POLL_INTERVAL_SECONDS = 0.1
REQUEST_TIMEOUT_SECONDS = 150
DEVELOPER_DIR = "/Applications/Xcode.app/Contents/Developer"
MISSING_APP_MARKERS = ("no such app", "not installed")
RECORDING_PROFILES = {
    "apple-iphone-portrait": "iphone",
    "apple-ipad-landscape": "ipad",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulator", default=DEFAULT_SIMULATOR)
    parser.add_argument(
        "--record-profile",
        choices=sorted(RECORDING_PROFILES),
        help="Validate the iPhone/iPad recording profile expected by the remote runner.",
    )
    parser.add_argument(
        "--push-delay",
        type=int,
        default=0,
        help="Deprecated compatibility delay before the request handshake starts.",
    )
    parser.add_argument(
        "--inline-reply",
        choices=("auto", "supported", "unsupported"),
        default="auto",
        help="Declare simulator inline-reply automation capability for the XCTest.",
    )
    parser.add_argument("--skip-uninstall", action="store_true")
    return parser.parse_args()


def simulator_family(simulator: str) -> str:
    return "ipad" if "ipad" in simulator.lower() else "iphone"


def validate_profile(simulator: str, profile: str | None) -> None:
    if profile is None:
        return
    expected_family = RECORDING_PROFILES[profile]
    actual_family = simulator_family(simulator)
    if expected_family != actual_family:
        raise ValueError(
            f"{profile} requires an {expected_family} simulator, got {actual_family}"
        )


def write_payload(path: Path, request: dict[str, str]) -> None:
    # Keep simulator payloads equivalent to the server's privacy-safe fallback.
    payload = {
        "Simulator Target Bundle": APP_BUNDLE_ID,
        "aps": {
            "alert": {"title": "OpenMates", "body": "New message received"},
            "sound": "default",
            "badge": 1,
            "category": "OPENMATES_CHAT_MESSAGE",
            "thread-id": request["chat_id"],
        },
        "chat_id": request["chat_id"],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def xcode_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["DEVELOPER_DIR"] = DEVELOPER_DIR
    return environment


def run_uninstall() -> None:
    result = subprocess.run(
        ["xcrun", "simctl", "uninstall", "booted", APP_BUNDLE_ID],
        check=False,
        capture_output=True,
        text=True,
        env=xcode_environment(),
    )
    if result.returncode == 0:
        return
    output = f"{result.stdout}\n{result.stderr}".lower()
    if any(marker in output for marker in MISSING_APP_MARKERS):
        return
    raise RuntimeError("simctl uninstall failed")


def read_request(path: Path) -> dict[str, str] | None:
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    required_fields = ("request_id", "scenario", "chat_id")
    if not all(isinstance(request.get(field), str) and request[field] for field in required_fields):
        return None
    return {field: request[field] for field in required_fields}


def write_response(path: Path, request_id: str, status: str) -> None:
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps({"request_id": request_id, "status": status}), encoding="utf-8"
    )
    temporary_path.replace(path)


def inject_push(payload_path: Path) -> bool:
    result = subprocess.run(
        ["xcrun", "simctl", "push", "booted", APP_BUNDLE_ID, str(payload_path)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=xcode_environment(),
    )
    return result.returncode == 0


def serve_push_requests(
    request_path: Path,
    response_path: Path,
    stop_event: threading.Event,
) -> None:
    handled_request_id: str | None = None
    while not stop_event.wait(POLL_INTERVAL_SECONDS):
        request = read_request(request_path)
        if request is None or request["request_id"] == handled_request_id:
            continue
        handled_request_id = request["request_id"]
        with tempfile.NamedTemporaryFile("w", suffix=".apns", delete=False) as payload_file:
            payload_path = Path(payload_file.name)
        try:
            write_payload(payload_path, request)
            status = "injected" if inject_push(payload_path) else "injection_failed"
            write_response(response_path, request["request_id"], status)
        finally:
            payload_path.unlink(missing_ok=True)


def run_xcodebuild(
    simulator: str,
    request_path: Path,
    response_path: Path,
    inline_reply: str,
    record_profile: str | None,
) -> int:
    command = [
        "xcodebuild", "test", "-project", PROJECT_PATH, "-scheme", SCHEME,
        "-destination", f"platform=iOS Simulator,name={simulator}",
        "-only-testing", ONLY_TESTING,
    ]
    env = xcode_environment()
    env["OPENMATES_SIMULATED_PUSH_REQUEST_PATH"] = str(request_path)
    env["OPENMATES_SIMULATED_PUSH_RESPONSE_PATH"] = str(response_path)
    env["OPENMATES_SIMULATOR_INLINE_REPLY"] = inline_reply
    env["OPENMATES_SIMULATOR_REQUEST_TIMEOUT"] = str(REQUEST_TIMEOUT_SECONDS)
    if record_profile:
        env["OPENMATES_SIMULATOR_RECORD_PROFILE"] = record_profile
    return subprocess.run(command, env=env, check=False).returncode


def print_capability_classification(inline_reply: str) -> None:
    inline_status = "conditional" if inline_reply != "unsupported" else "unsupported"
    print("simulator_coverage generic_payload=covered foreground_dedup=covered warm_tap=covered cold_tap=covered")
    print(f"simulator_coverage inline_reply={inline_status}")
    print("simulator_coverage unread_state=external badge_clear=external")
    print("simulator_limitations apns_provider=external token_registration=external notification_extension=external")


def main() -> int:
    args = parse_args()
    try:
        validate_profile(args.simulator, args.record_profile)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    if not args.skip_uninstall:
        try:
            run_uninstall()
        except RuntimeError as error:
            print(str(error), file=sys.stderr)
            return 1
    if args.push_delay:
        time.sleep(args.push_delay)

    with tempfile.TemporaryDirectory(prefix="openmates-simulator-push-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        request_path = temporary_path / "request.json"
        response_path = temporary_path / "response.json"
        stop_event = threading.Event()
        thread = threading.Thread(
            target=serve_push_requests,
            args=(request_path, response_path, stop_event),
            daemon=True,
        )
        thread.start()
        try:
            return run_xcodebuild(
                args.simulator, request_path, response_path, args.inline_reply, args.record_profile
            )
        finally:
            stop_event.set()
            thread.join(timeout=1)
            print_capability_classification(args.inline_reply)


if __name__ == "__main__":
    raise SystemExit(main())
