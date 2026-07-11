#!/usr/bin/env python3
"""Run redacted remote Apple development commands over Tailscale/SSH.

This wrapper keeps private connection details out of repo commands and logs. It
discovers a single online macOS Tailscale peer or reads local-only operator
configuration, then runs SSH with non-interactive safety defaults. Output labels
refer to the target generically as `macos-peer` so hostnames, IPs, usernames,
aliases, device names, and local Mac paths do not leak into committed artifacts.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_CONFIG_PATH = Path.home() / ".config" / "openmates" / "apple-remote.json"
REMOTE_LABEL = "macos-peer"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
MIN_TESTFLIGHT_WHATS_NEW_LINES = 5
SIMULATOR_LOCK_PATH = "/tmp/openmates-apple-simulator.lock"
DESTRUCTIVE_TOKENS = {
    "rm",
    "shutdown",
    "reboot",
    "halt",
    "diskutil",
    "eraseDisk",
    "git reset --hard",
    "git clean",
}
XCODE_CACHE_TARGETS = {
    "derived-data": "~/Library/Developer/Xcode/DerivedData",
    "module-cache": "~/Library/Developer/Xcode/DerivedData/ModuleCache.noindex",
    "swiftpm-cache": "~/Library/Caches/org.swift.swiftpm",
    "simulator-caches": "~/Library/Developer/CoreSimulator/Caches",
    "device-support": "~/Library/Developer/Xcode/iOS DeviceSupport",
}

SIMULATOR_LOCK_SCRIPT = r'''
import fcntl
import subprocess
import sys

lock_path = sys.argv[1]
command = sys.argv[2:]
print("simulator_lock=waiting", flush=True)
with open(lock_path, "w", encoding="utf-8") as lock_file:
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    print("simulator_lock=acquired", flush=True)
    result = subprocess.run(command)
sys.exit(result.returncode)
'''


DEVICE_STATUS_SCRIPT = r'''
import json
import os
import subprocess
import sys
import tempfile

fd, path = tempfile.mkstemp(suffix=".json")
os.close(fd)
try:
    result = subprocess.run(
        ["xcrun", "devicectl", "list", "devices", "--json-output", path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    print(f"devicectl_exit={result.returncode}")
    if result.returncode != 0:
        print("device_status=devicectl_failed")
        sys.exit(result.returncode)
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
finally:
    try:
        os.remove(path)
    except OSError:
        pass

devices = data.get("result", {}).get("devices", []) if isinstance(data, dict) else []
wired = [d for d in devices if d.get("connectionProperties", {}).get("transportType") == "wired"]
print(f"devices={len(devices)}")
print(f"wired_devices={len(wired)}")
for index, device in enumerate(devices, 1):
    properties = device.get("deviceProperties", {})
    connection = device.get("connectionProperties", {})
    print(f"device_{index}_transport={connection.get('transportType', 'unknown')}")
    print(f"device_{index}_pairing={connection.get('pairingState', 'unknown')}")
    print(f"device_{index}_developer_mode={properties.get('developerModeStatus', 'unknown')}")
    print(f"device_{index}_product_type={properties.get('productType', 'unknown')}")
    print(f"device_{index}_os={properties.get('osVersionNumber', properties.get('osVersion', 'unknown'))}")
sys.exit(0 if devices else 3)
'''


INSTALL_IOS_DEVICE_SCRIPT = r'''
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

configuration = sys.argv[1]
allow_provisioning_updates = sys.argv[2] == "1"
with_associated_domains = sys.argv[3] == "1"
device_index = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else None


def print_tail(label, text, device_id, app_path=None, limit=160):
    print(f"{label}=failed")
    sanitized = text.replace(device_id, "<device-id>")
    sanitized = re.sub(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16}\b", "<device-id>", sanitized)
    if app_path:
        sanitized = sanitized.replace(app_path, "<app-bundle>")
    for line in sanitized.splitlines()[-limit:]:
        print(line)


def print_build_failure_hint(text):
    lowered = text.lower()
    if "personal development teams" in lowered and "associated domains" in lowered:
        print("build_failure_hint=paid_team_not_selected_in_xcode")
        print("build_failure_action=select_paid_development_team_or_add_app_store_connect_api_key_on_macos_peer")
    if "errsecinternalcomponent" in lowered or "user interaction is not allowed" in lowered:
        print("build_failure_hint=keychain_codesign_access_required")
        print("build_failure_action=unlock_login_keychain_and_allow_codesign_on_macos_peer")
    if "developer disk image could not be mounted" in lowered:
        print("build_failure_hint=developer_disk_image_mount_failed")
        print("build_failure_action=unlock_device_keep_awake_then_retry_or_update_xcode_device_support")


fd, path = tempfile.mkstemp(suffix=".json")
os.close(fd)
try:
    subprocess.run(
        ["xcrun", "devicectl", "list", "devices", "--json-output", path],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
finally:
    try:
        os.remove(path)
    except OSError:
        pass

devices = data.get("result", {}).get("devices", []) if isinstance(data, dict) else []
eligible = [
    d
    for d in devices
    if d.get("connectionProperties", {}).get("pairingState") == "paired"
    and d.get("deviceProperties", {}).get("developerModeStatus") == "enabled"
]
if device_index is not None:
    if device_index < 1 or device_index > len(devices):
        print("install_status=device_index_out_of_range")
        sys.exit(3)
    selected = devices[device_index - 1]
    if selected not in eligible:
        print("install_status=device_not_ready")
        sys.exit(3)
elif len(eligible) == 1:
    selected = eligible[0]
else:
    print(f"install_status=ambiguous_device")
    print(f"eligible_devices={len(eligible)}")
    sys.exit(3)

device_id = selected.get("identifier")
if not device_id:
    print("install_status=no_device_identifier")
    sys.exit(4)

derived = tempfile.mkdtemp(prefix="openmates-device-build-")
entitlements_override = None
if with_associated_domains:
    entitlements_override = pathlib.Path("apple/OpenMates/Resources/OpenMatesPasskey.entitlements")
    print("associated_domains=enabled_for_passkey_build")
else:
    print("associated_domains=project_default")

print("translations_status=started")
translations = subprocess.run(
    ["npm", "run", "build:translations"],
    cwd="frontend/packages/ui",
    capture_output=True,
    text=True,
    timeout=180,
)
if translations.returncode != 0:
    print_tail("translations_status", translations.stdout + translations.stderr, derived, limit=120)
    sys.exit(translations.returncode)
print("translations_status=passed")

build_cmd = [
    "xcodebuild",
    "-project",
    "apple/OpenMates.xcodeproj",
    "-scheme",
    "OpenMates_iOS",
    "-configuration",
    configuration,
    "-destination",
    "generic/platform=iOS",
    "-derivedDataPath",
    derived,
]
if allow_provisioning_updates:
    build_cmd.append("-allowProvisioningUpdates")
if entitlements_override is not None:
    build_cmd.append(f"CODE_SIGN_ENTITLEMENTS={entitlements_override}")
build_cmd.append("build")

print("build_status=started")
build = subprocess.run(build_cmd, capture_output=True, text=True, timeout=1800)
if build.returncode != 0:
    build_output = build.stdout + build.stderr
    print_tail("build_status", build_output, device_id)
    print_build_failure_hint(build_output)
    sys.exit(build.returncode)

products = pathlib.Path(derived) / "Build" / "Products" / f"{configuration}-iphoneos"
apps = [path for path in products.glob("*.app") if path.name == "OpenMates.app"]
if not apps:
    apps = [path for path in products.glob("*.app") if not path.name.endswith("Extension.app")]
if not apps:
    print("install_status=no_app_bundle")
    sys.exit(5)

app = str(apps[0])
print("build_status=passed")
print("install_status=started")
install = subprocess.run(
    ["xcrun", "devicectl", "device", "install", "app", "--device", device_id, app],
    capture_output=True,
    text=True,
    timeout=300,
)
if install.returncode != 0:
    print_tail("install_status", install.stdout + install.stderr, device_id, app, limit=100)
    sys.exit(install.returncode)

print("install_status=passed")
for line in (install.stdout + install.stderr).replace(device_id, "<device-id>").replace(app, "<app-bundle>").splitlines()[-20:]:
    print(line)
'''


WATCH_STARTUP_SCRIPT = r'''
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

simulator = sys.argv[1]
duration = int(sys.argv[2])
bundle_id = "org.openmates.app.watch"
scheme = "OpenMatesWatch"
project = "apple/OpenMates.xcodeproj"


def print_tail(label, text, limit=120):
    print(f"{label}=failed")
    for line in text.splitlines()[-limit:]:
        sanitized = line.replace(derived, "<derived-data>") if "derived" in globals() else line
        sanitized = sanitized.replace(artifact_dir, "<watch-startup-artifacts>") if "artifact_dir" in globals() else sanitized
        print(sanitized)


def run(label, cmd, *, timeout):
    print(f"{label}=started")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        print_tail(label, result.stdout + result.stderr)
        sys.exit(result.returncode)
    print(f"{label}=passed")
    return result


if duration < 5 or duration > 300:
    print("startup_status=invalid_duration")
    print("duration must be between 5 and 300 seconds")
    sys.exit(2)

derived = tempfile.mkdtemp(prefix="openmates-watch-startup-derived-")
artifact_dir = tempfile.mkdtemp(prefix="openmates-watch-startup-artifacts-")
print("artifact_dir=<watch-startup-artifacts>")

crash_dir = pathlib.Path.home() / "Library" / "Logs" / "DiagnosticReports"
started_at = time.time()

try:
    run(
        "settings_status",
        [
            "xcodebuild",
            "-showBuildSettings",
            "-project",
            project,
            "-scheme",
            scheme,
            "-destination",
            f"platform=watchOS Simulator,name={simulator}",
            "-derivedDataPath",
            derived,
        ],
        timeout=180,
    )
    run(
        "build_status",
        [
            "xcodebuild",
            "-project",
            project,
            "-scheme",
            scheme,
            "-destination",
            f"platform=watchOS Simulator,name={simulator}",
            "-derivedDataPath",
            derived,
            "build",
        ],
        timeout=1800,
    )

    products = pathlib.Path(derived) / "Build" / "Products" / "Debug-watchsimulator"
    apps = sorted(products.glob("OpenMatesWatch.app"))
    if not apps:
        apps = sorted(products.glob("*.app"))
    if not apps:
        print("install_status=no_app_bundle")
        sys.exit(5)
    app_path = str(apps[0])

    subprocess.run(["xcrun", "simctl", "boot", simulator], capture_output=True, text=True, timeout=120)
    run("boot_status", ["xcrun", "simctl", "bootstatus", simulator, "-b"], timeout=180)
    subprocess.run(["xcrun", "simctl", "uninstall", simulator, bundle_id], capture_output=True, text=True, timeout=120)
    print("uninstall_status=attempted")
    run("install_status", ["xcrun", "simctl", "install", simulator, app_path], timeout=180)
    launch = run("launch_status", ["xcrun", "simctl", "launch", simulator, bundle_id], timeout=120)

    pid = None
    for token in launch.stdout.split():
        if token.isdigit():
            pid = token
    if pid:
        print(f"launch_pid={pid}")

    screenshot_points = {5: "screenshot_5s", 30: "screenshot_30s"}
    deadline = time.monotonic() + duration
    captured = set()
    status = "passed"
    while time.monotonic() < deadline:
        elapsed = int(duration - max(0, deadline - time.monotonic()))
        for point, label in screenshot_points.items():
            if elapsed >= point and point not in captured:
                screenshot_path = pathlib.Path(artifact_dir) / f"{label}.png"
                shot = subprocess.run(
                    ["xcrun", "simctl", "io", simulator, "screenshot", str(screenshot_path)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                print(f"{label}={'passed' if shot.returncode == 0 else 'failed'}")
                captured.add(point)

        launchctl = subprocess.run(
            ["xcrun", "simctl", "spawn", simulator, "launchctl", "print", f"system/{bundle_id}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        pgrep = subprocess.run(
            ["xcrun", "simctl", "spawn", simulator, "pgrep", "-f", bundle_id],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if launchctl.returncode != 0 and pgrep.returncode != 0:
            status = "process_exited"
            break

        recent_crashes = []
        if crash_dir.exists():
            for path in crash_dir.glob("*OpenMatesWatch*"):
                try:
                    if path.stat().st_mtime >= started_at:
                        recent_crashes.append(path)
                except OSError:
                    pass
        if recent_crashes:
            print("crash_report_status=found")
            print("crash_report_count=" + str(len(recent_crashes)))
            status = "crash_report_found"
            break

        time.sleep(2)

    for point, label in screenshot_points.items():
        if point <= duration and point not in captured:
            screenshot_path = pathlib.Path(artifact_dir) / f"{label}.png"
            shot = subprocess.run(
                ["xcrun", "simctl", "io", simulator, "screenshot", str(screenshot_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            print(f"{label}={'passed' if shot.returncode == 0 else 'failed'}")

    logs = subprocess.run(
        [
            "xcrun",
            "simctl",
            "spawn",
            simulator,
            "log",
            "show",
            "--last",
            f"{max(duration, 30)}s",
            "--predicate",
            f"process == '{scheme}' OR eventMessage CONTAINS '{bundle_id}'",
            "--style",
            "compact",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    log_path = pathlib.Path(artifact_dir) / "watch-startup.log"
    log_path.write_text(logs.stdout + logs.stderr, encoding="utf-8")
    print("log_capture_status=passed" if logs.returncode == 0 else "log_capture_status=partial")
    print(f"startup_status={status}")
    sys.exit(0 if status == "passed" else 6)
finally:
    shutil.rmtree(derived, ignore_errors=True)
'''


TESTFLIGHT_IOS_SCRIPT = r'''
import base64
import json
import os
import pathlib
import plistlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

internal_only = sys.argv[1] == "1"
target_platform = sys.argv[2] if len(sys.argv) > 2 else "ios"
MIN_TESTFLIGHT_WHATS_NEW_LINES = 5
testflight_whats_new = ""
testflight_whats_new_locale = "en-US"
requested_build_number = os.environ.get("OPENMATES_UNIFIED_BUILD_NUMBER")
if requested_build_number:
    requested_build_number = requested_build_number.strip()
    if not re.fullmatch(r"\d{1,4}(?:\.\d{1,2}){0,2}", requested_build_number):
        print("build_number_status=invalid")
        sys.exit(2)
    print(f"build_number_status=unified:{requested_build_number}")
else:
    requested_build_number = None
if len(sys.argv) > 3 and sys.argv[3]:
    testflight_whats_new = base64.b64decode(sys.argv[3]).decode("utf-8").strip()
if len(sys.argv) > 4 and sys.argv[4]:
    testflight_whats_new_locale = sys.argv[4]
if len([line for line in testflight_whats_new.splitlines() if line.strip()]) < MIN_TESTFLIGHT_WHATS_NEW_LINES:
    print("whats_new_status=too_short")
    print(f"hint=App Store Connect TestFlight What to Test text must contain at least {MIN_TESTFLIGHT_WHATS_NEW_LINES} non-empty lines.")
    sys.exit(2)
if len(testflight_whats_new) > 4000:
    print("whats_new_status=too_long")
    print("hint=App Store Connect TestFlight What to Test text must be 4000 characters or less.")
    sys.exit(2)
build_keychain_path = None
distribution_identity_name = ""
distribution_identity_sha1 = ""
installer_identity_sha1 = ""
profile_names = {}
previous_testflight_build_ids = set()
APP_GROUP_IDENTIFIER = "group.org.openmates.app.shared"
if target_platform == "ios":
    scheme_name = "OpenMates_iOS"
    archive_filename = "OpenMates.xcarchive"
    archive_destination = "generic/platform=iOS"
    profile_type = "IOS_APP_STORE"
    certificate_type_filter = "IOS_DISTRIBUTION"
    profile_extension = "mobileprovision"
    bundle_id_platform = "IOS"
    archive_without_signing = False
    BUNDLE_IDS = (
        "org.openmates.app",
        "org.openmates.app.share",
        "org.openmates.app.notification-service",
        "org.openmates.app.widget",
        "org.openmates.app.watch",
    )
    REQUIRED_APP_GROUP_BUNDLE_IDS = set(BUNDLE_IDS) - {
        "org.openmates.app.watch",
    }
    REQUIRED_KEYCHAIN_GROUP_BUNDLE_IDS = set()
elif target_platform == "macos":
    scheme_name = "OpenMates_macOS"
    archive_filename = "OpenMatesMac.xcarchive"
    archive_destination = "generic/platform=macOS"
    profile_type = "MAC_APP_STORE"
    certificate_type_filter = "DISTRIBUTION"
    profile_extension = "provisionprofile"
    bundle_id_platform = "MAC_OS"
    archive_without_signing = True
    BUNDLE_IDS = (
        "org.openmates.app",
        "org.openmates.app.sharemacos",
    )
    REQUIRED_APP_GROUP_BUNDLE_IDS = set(BUNDLE_IDS)
    REQUIRED_KEYCHAIN_GROUP_BUNDLE_IDS = set()
elif target_platform == "watchos":
    scheme_name = "OpenMatesWatch"
    archive_filename = "OpenMatesWatch.xcarchive"
    archive_destination = "generic/platform=watchOS"
    profile_type = "IOS_APP_STORE"
    certificate_type_filter = "IOS_DISTRIBUTION"
    profile_extension = "mobileprovision"
    bundle_id_platform = "IOS"
    archive_without_signing = False
    BUNDLE_IDS = (
        "org.openmates.app.watch",
    )
    REQUIRED_APP_GROUP_BUNDLE_IDS = set()
    REQUIRED_KEYCHAIN_GROUP_BUNDLE_IDS = set()
else:
    print(f"unsupported_target_platform={target_platform}")
    sys.exit(2)


def auth_args():
    key_path = os.environ.get("APP_STORE_CONNECT_API_KEY_PATH")
    key_id = os.environ.get("APP_STORE_CONNECT_API_KEY_ID")
    issuer_id = os.environ.get("APP_STORE_CONNECT_API_ISSUER_ID")
    if key_path and key_id and issuer_id:
        return [
            "-authenticationKeyPath",
            os.path.expanduser(key_path),
            "-authenticationKeyID",
            key_id,
            "-authenticationKeyIssuerID",
            issuer_id,
        ]
    return []


def print_tail(label, text, tmp_dir=None, limit=160):
    print(f"{label}=failed")
    sanitized = text
    if tmp_dir:
        sanitized = sanitized.replace(tmp_dir, "<macos-peer-tmp>")
    api_key_path = os.environ.get("APP_STORE_CONNECT_API_KEY_PATH")
    if api_key_path:
        sanitized = sanitized.replace(api_key_path, "<app-store-connect-api-key>")
    sanitized = re.sub(r"/Users/[^\s]+", "<macos-peer-path>", sanitized)
    for line in sanitized.splitlines()[-limit:]:
        print(line)


def build_translations():
    print("translations_status=started")
    result = subprocess.run(
        ["npm", "run", "build:translations"],
        cwd="frontend/packages/ui",
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        print_tail("translations_status", result.stdout + result.stderr, limit=120)
        sys.exit(result.returncode)
    print("translations_status=passed")


def build_tokens():
    print("tokens_status=started")
    result = subprocess.run(
        ["npm", "run", "build:tokens"],
        cwd="frontend/packages/ui",
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        print_tail("tokens_status", result.stdout + result.stderr, limit=120)
        sys.exit(result.returncode)
    print("tokens_status=passed")


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def der_ecdsa_to_raw_jws_signature(der_signature):
    if len(der_signature) < 8 or der_signature[0] != 0x30:
        raise ValueError("Unexpected ECDSA signature format")
    index = 2
    if der_signature[1] & 0x80:
        length_bytes = der_signature[1] & 0x7F
        index = 2 + length_bytes
    if der_signature[index] != 0x02:
        raise ValueError("Missing ECDSA R integer")
    r_length = der_signature[index + 1]
    r_start = index + 2
    r = der_signature[r_start:r_start + r_length].lstrip(b"\x00")
    s_index = r_start + r_length
    if der_signature[s_index] != 0x02:
        raise ValueError("Missing ECDSA S integer")
    s_length = der_signature[s_index + 1]
    s_start = s_index + 2
    s = der_signature[s_start:s_start + s_length].lstrip(b"\x00")
    return r.rjust(32, b"\x00") + s.rjust(32, b"\x00")


def app_store_connect_jwt():
    key_path = os.path.expanduser(os.environ.get("APP_STORE_CONNECT_API_KEY_PATH", ""))
    key_id = os.environ.get("APP_STORE_CONNECT_API_KEY_ID")
    issuer_id = os.environ.get("APP_STORE_CONNECT_API_ISSUER_ID")
    if not key_path or not key_id or not issuer_id:
        print("profile_create=missing_app_store_connect_api_auth")
        sys.exit(2)
    now = int(time.time())
    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    payload = {"iss": issuer_id, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"}
    signing_input = ".".join([
        b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ])
    signer = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", key_path, "-binary"],
        input=signing_input.encode("ascii"),
        capture_output=True,
        timeout=30,
    )
    if signer.returncode != 0:
        print_tail("jwt_signing", signer.stderr.decode("utf-8", "replace"), limit=80)
        sys.exit(signer.returncode)
    signature = der_ecdsa_to_raw_jws_signature(signer.stdout)
    return f"{signing_input}.{b64url(signature)}"


def asc_request(path, method="GET", body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.appstoreconnect.apple.com/v1/{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {app_store_connect_jwt()}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                content = response.read().decode("utf-8")
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", "replace")
            print(f"asc_http_status={exc.code}")
            print_tail("asc_request", body_text, limit=120)
            sys.exit(1)
        except (TimeoutError, socket.timeout, urllib.error.URLError):
            if attempt == 2:
                print("asc_request=timeout")
                sys.exit(1)
            time.sleep(3)
    print("asc_request=failed")
    sys.exit(1)


def latest_app_store_build_for_notes(excluded_build_ids=None, wait_for_new=True):
    excluded_build_ids = set(excluded_build_ids or [])
    apps_query = urllib.parse.urlencode({"filter[bundleId]": "org.openmates.app", "limit": "10"})
    apps = asc_request(f"apps?{apps_query}").get("data", [])
    if not apps:
        print("whats_new_status=missing_app")
        sys.exit(1)

    expected_platform = "MAC_OS" if target_platform == "macos" else "IOS"
    attempts = 20 if wait_for_new else 1
    for attempt in range(attempts):
        for app in apps:
            app_id = app.get("id")
            builds_query = urllib.parse.urlencode({
                "filter[app]": app_id,
                "include": "preReleaseVersion",
                "limit": "20",
                "sort": "-uploadedDate",
            })
            response = asc_request(f"builds?{builds_query}")
            pre_release_versions = {
                item.get("id"): item.get("attributes", {})
                for item in response.get("included", [])
                if item.get("type") == "preReleaseVersions"
            }
            for build in response.get("data", []):
                pre_release_id = build.get("relationships", {}).get("preReleaseVersion", {}).get("data", {}).get("id")
                platform = pre_release_versions.get(pre_release_id, {}).get("platform")
                if platform == expected_platform and build.get("id") not in excluded_build_ids:
                    return build
        if attempt < attempts - 1:
            time.sleep(30)

    if not wait_for_new:
        return None

    print(f"whats_new_status=missing_build:{expected_platform}")
    sys.exit(1)


def upsert_testflight_whats_new():
    if not testflight_whats_new:
        return
    if target_platform == "watchos":
        print("whats_new_status=skipped_watchos")
        return

    build = latest_app_store_build_for_notes(excluded_build_ids=previous_testflight_build_ids)
    build_id = build.get("id")
    if not build_id:
        print("whats_new_status=missing_build_id")
        sys.exit(1)

    localizations = asc_request(f"builds/{build_id}/betaBuildLocalizations?limit=200").get("data", [])
    existing = next(
        (
            item for item in localizations
            if item.get("attributes", {}).get("locale") == testflight_whats_new_locale
        ),
        None,
    )
    if existing and existing.get("id"):
        asc_request(
            f"betaBuildLocalizations/{existing['id']}",
            method="PATCH",
            body={
                "data": {
                    "type": "betaBuildLocalizations",
                    "id": existing["id"],
                    "attributes": {"whatsNew": testflight_whats_new},
                }
            },
        )
        print(f"whats_new_status=updated:{testflight_whats_new_locale}")
        return

    asc_request(
        "betaBuildLocalizations",
        method="POST",
        body={
            "data": {
                "type": "betaBuildLocalizations",
                "attributes": {
                    "locale": testflight_whats_new_locale,
                    "whatsNew": testflight_whats_new,
                },
                "relationships": {
                    "build": {"data": {"type": "builds", "id": build_id}}
                },
            }
        },
    )
    print(f"whats_new_status=created:{testflight_whats_new_locale}")


def parse_keychain_list(output):
    keychains = []
    for line in output.splitlines():
        cleaned = line.strip().strip('"')
        if cleaned:
            keychains.append(cleaned)
    return keychains


def use_build_keychain_if_present():
    global build_keychain_path
    password_path = pathlib.Path.home() / ".config" / "openmates" / "apple-build-keychain-password"
    keychain = pathlib.Path.home() / "Library" / "Keychains" / "openmates-build.keychain-db"
    if not password_path.exists() or not keychain.exists():
        return []
    password = password_path.read_text(encoding="utf-8").strip()
    unlock = subprocess.run(["security", "unlock-keychain", "-p", password, str(keychain)], capture_output=True, text=True, timeout=30)
    if unlock.returncode != 0:
        print_tail("build_keychain_unlock", unlock.stdout + unlock.stderr, limit=80)
        sys.exit(unlock.returncode)
    partition_list = subprocess.run(
        ["security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:", "-s", "-k", password, str(keychain)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if partition_list.returncode != 0:
        print_tail("build_keychain_partition_list", partition_list.stdout + partition_list.stderr, limit=80)
        sys.exit(partition_list.returncode)
    build_keychain_path = str(keychain)
    return [build_keychain_path]


def preflight_signing():
    global distribution_identity_name, distribution_identity_sha1, installer_identity_sha1
    keychain_args = use_build_keychain_if_present()
    identities = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning", *keychain_args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if identities.returncode != 0:
        print_tail("preflight_status", identities.stdout + identities.stderr, limit=80)
        sys.exit(identities.returncode)

    identity_lines = identities.stdout.splitlines()
    development_identity = next((line.split('"')[0].split(")", 1)[-1].strip() for line in identity_lines if "Apple Development:" in line or "iPhone Developer:" in line), "")
    if target_platform == "macos":
        distribution_identity_line = next((line for line in identity_lines if "Apple Distribution:" in line), "")
    else:
        distribution_identity_line = next((line for line in identity_lines if "Apple Distribution:" in line or "iPhone Distribution:" in line), "")
    if distribution_identity_line:
        distribution_identity_sha1 = distribution_identity_line.split()[1].upper()
        distribution_identity_name = distribution_identity_line.split('"')[1]
    distribution_identity = bool(distribution_identity_name)

    if not distribution_identity:
        print("distribution_identity=missing")
        print("hint=Create or download an Apple Distribution certificate in Xcode before TestFlight upload.")

    if target_platform == "macos":
        installer_certificate = subprocess.run(
            ["security", "find-certificate", "-a", "-Z", "-c", "3rd Party Mac Developer Installer", *keychain_args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if installer_certificate.returncode != 0 or "3rd Party Mac Developer Installer" not in installer_certificate.stdout:
            print("installer_distribution_identity=missing")
            print("hint=Run ensure-mac-installer-distribution-certificate --create before macOS TestFlight upload.")
            sys.exit(1)
        for line in installer_certificate.stdout.splitlines():
            if line.strip().startswith("SHA-1 hash:"):
                installer_identity_sha1 = line.split(":", 1)[1].strip().upper()
                break
        if not installer_identity_sha1:
            print("installer_distribution_identity=missing_sha1")
            sys.exit(1)

    probe_identity = distribution_identity_name or development_identity
    if probe_identity:
        probe_dir = tempfile.mkdtemp(prefix="openmates-codesign-preflight-")
        probe_path = pathlib.Path(probe_dir) / "probe"
        try:
            subprocess.run(["cp", "/bin/ls", str(probe_path)], check=True, capture_output=True, text=True, timeout=30)
            probe = subprocess.run(
                ["codesign", "--force", "--sign", probe_identity, "--timestamp=none", str(probe_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
        finally:
            shutil.rmtree(probe_dir, ignore_errors=True)
        if probe.returncode != 0:
            print_tail("preflight_status", probe.stdout + probe.stderr, probe_dir, limit=80)
            print("hint=Allow codesign private-key access in Keychain Access or archive once from Xcode and choose Always Allow.")
            sys.exit(probe.returncode)

    if not distribution_identity:
        sys.exit(1)

    print("preflight_status=passed")


def sha1_for_der_base64(content):
    der = base64.b64decode(content)
    return subprocess.run(["shasum", "-a", "1"], input=der, capture_output=True, timeout=30).stdout.decode("utf-8").split()[0].upper()


def matching_distribution_certificate_id():
    query = urllib.parse.urlencode({"filter[certificateType]": certificate_type_filter, "limit": "200"})
    response = asc_request(f"certificates?{query}")
    for certificate in response.get("data", []):
        content = certificate.get("attributes", {}).get("certificateContent")
        if content and sha1_for_der_base64(content) == distribution_identity_sha1:
            return certificate.get("id")
    print("profile_create=matching_distribution_certificate_missing")
    sys.exit(1)


def bundle_id_record_id(identifier):
    query = urllib.parse.urlencode({"filter[identifier]": identifier, "limit": "1"})
    response = asc_request(f"bundleIds?{query}")
    data = response.get("data", [])
    if not data:
        name = "OpenMates" if identifier == "org.openmates.app" else f"OpenMates {identifier.rsplit('.', 1)[-1]}"
        created = asc_request("bundleIds", method="POST", body={
            "data": {
                "type": "bundleIds",
                "attributes": {
                    "identifier": identifier,
                    "name": name,
                    "platform": bundle_id_platform,
                },
            }
        })
        bundle_id = created.get("data", {}).get("id")
        if not bundle_id:
            print(f"profile_create=bundle_id_missing:{identifier}")
            sys.exit(1)
        print(f"bundle_id_create=passed:{identifier}")
        return bundle_id
    return data[0].get("id")


def capability_attributes(capability_type):
    attributes = {"capabilityType": capability_type}
    return attributes


def existing_capability_id(bundle_id, capability_type):
    response = asc_request(f"bundleIds/{bundle_id}/bundleIdCapabilities")
    for capability in response.get("data", []):
        if capability.get("attributes", {}).get("capabilityType") == capability_type:
            return capability.get("id")
    return None


def enable_bundle_capability(bundle_id, capability_type):
    capability_id = existing_capability_id(bundle_id, capability_type)
    if capability_id:
        asc_request(f"bundleIdCapabilities/{capability_id}", method="PATCH", body={
            "data": {
                "type": "bundleIdCapabilities",
                "id": capability_id,
                "attributes": capability_attributes(capability_type),
            }
        })
        return
    asc_request("bundleIdCapabilities", method="POST", body={
        "data": {
            "type": "bundleIdCapabilities",
            "attributes": capability_attributes(capability_type),
            "relationships": {"bundleId": {"data": {"type": "bundleIds", "id": bundle_id}}},
        }
    })


def sync_bundle_capabilities():
    for identifier in BUNDLE_IDS:
        bundle_id = bundle_id_record_id(identifier)
        if identifier in REQUIRED_APP_GROUP_BUNDLE_IDS:
            enable_bundle_capability(bundle_id, "APP_GROUPS")
            print(f"capability_sync=passed:{identifier}:APP_GROUPS")
        if identifier in REQUIRED_KEYCHAIN_GROUP_BUNDLE_IDS:
            # App Store Connect does not expose KEYCHAIN_SHARING as a Bundle ID
            # capability. Keep validating the generated provisioning profile
            # entitlement below, but do not attempt an ASC capability mutation.
            print(f"capability_sync=skipped:{identifier}:KEYCHAIN_SHARING:not_app_store_connect_capability")
        if identifier == "org.openmates.app":
            enable_bundle_capability(bundle_id, "ASSOCIATED_DOMAINS")
            print(f"capability_sync=passed:{identifier}:ASSOCIATED_DOMAINS")


def existing_profile(profile_name):
    query = urllib.parse.urlencode({"filter[name]": profile_name, "limit": "1"})
    response = asc_request(f"profiles?{query}")
    data = response.get("data", [])
    if not data:
        return None
    profile_id = data[0].get("id")
    if not profile_id:
        return None
    return asc_request(f"profiles/{profile_id}")


def delete_existing_profile(profile_name):
    query = urllib.parse.urlencode({"filter[name]": profile_name, "limit": "200"})
    response = asc_request(f"profiles?{query}")
    for profile in response.get("data", []):
        profile_id = profile.get("id")
        if not profile_id:
            continue
        asc_request(f"profiles/{profile_id}", method="DELETE")


def assert_profile_supports_required_entitlements(identifier, profile_path):
    decoded = subprocess.run(["security", "cms", "-D", "-i", str(profile_path)], capture_output=True, timeout=30)
    if decoded.returncode != 0:
        print(f"profile_entitlements=decode_failed:{identifier}")
        print_tail("profile_decode", decoded.stderr.decode("utf-8", "replace"), limit=80)
        sys.exit(decoded.returncode)
    data = plistlib.loads(decoded.stdout)
    entitlements = data.get("Entitlements", {}) if isinstance(data, dict) else {}
    if identifier in REQUIRED_APP_GROUP_BUNDLE_IDS:
        app_groups = entitlements.get("com.apple.security.application-groups", [])
        if APP_GROUP_IDENTIFIER not in app_groups:
            print(f"profile_app_group=missing:{identifier}:{APP_GROUP_IDENTIFIER}")
            print("manual_action=assign_app_group_to_bundle_id_in_apple_developer_portal")
            print("manual_path=Certificates, Identifiers & Profiles > Identifiers > App IDs > bundle ID > App Groups")
            sys.exit(1)
        print(f"profile_app_group=passed:{identifier}")
    if identifier in REQUIRED_KEYCHAIN_GROUP_BUNDLE_IDS:
        keychain_groups = entitlements.get("keychain-access-groups", [])
        keychain_group = required_keychain_group(identifier, entitlements)
        if keychain_group not in keychain_groups:
            print(f"profile_keychain_group=missing:{identifier}:{keychain_group}")
            print("manual_action=assign_keychain_sharing_group_to_bundle_id_in_apple_developer_portal")
            print("manual_path=Certificates, Identifiers & Profiles > Identifiers > App IDs > bundle ID > Keychain Sharing")
            sys.exit(1)
        print(f"profile_keychain_group=passed:{identifier}")


def create_or_download_app_store_profiles():
    certificate_id = matching_distribution_certificate_id()
    profile_dirs = provisioning_profile_dirs()
    for profiles_dir in profile_dirs:
        profiles_dir.mkdir(parents=True, exist_ok=True)
    for identifier in BUNDLE_IDS:
        profile_name = f"OpenMates {target_platform} App Store {identifier}"
        delete_existing_profile(profile_name)
        response = asc_request("profiles", method="POST", body={
            "data": {
                "type": "profiles",
                "attributes": {
                    "name": profile_name,
                    "profileType": profile_type,
                },
                "relationships": {
                    "bundleId": {"data": {"type": "bundleIds", "id": bundle_id_record_id(identifier)}},
                    "certificates": {"data": [{"type": "certificates", "id": certificate_id}]},
                },
            }
        })
        attributes = response.get("data", {}).get("attributes", {})
        profile_content = attributes.get("profileContent")
        profile_uuid = attributes.get("uuid") or response.get("data", {}).get("id")
        if not profile_content or not profile_uuid:
            print(f"profile_create=missing_content:{identifier}")
            sys.exit(1)
        profile_bytes = base64.b64decode(profile_content)
        profile_path = profile_dirs[0] / f"{profile_uuid}.{profile_extension}"
        for profiles_dir in profile_dirs:
            (profiles_dir / f"{profile_uuid}.{profile_extension}").write_bytes(profile_bytes)
        assert_profile_supports_required_entitlements(identifier, profile_path)
        profile_data = decoded_profile(profile_path)
        installed_uuid = profile_data.get("UUID") if profile_data else None
        profile_names[identifier] = installed_uuid or profile_uuid
        print(f"profile_create=passed:{identifier}")


def clean_openmates_provisioning_profiles():
    profile_dirs = [
        pathlib.Path.home() / "Library" / "MobileDevice" / "Provisioning Profiles",
        pathlib.Path.home() / "Library" / "Developer" / "Xcode" / "UserData" / "Provisioning Profiles",
    ]
    backup_dir = pathlib.Path(tempfile.mkdtemp(prefix="openmates-profiles-backup-"))
    moved = 0
    existing_dirs = [profiles_dir for profiles_dir in profile_dirs if profiles_dir.exists()]
    if not existing_dirs:
        print("provisioning_profile_cleanup=profiles_dir_missing")
        return
    for profiles_dir in existing_dirs:
        for profile in [*profiles_dir.glob("*.mobileprovision"), *profiles_dir.glob("*.provisionprofile")]:
            decoded = subprocess.run(["security", "cms", "-D", "-i", str(profile)], capture_output=True, timeout=30)
            if decoded.returncode != 0:
                continue
            try:
                data = plistlib.loads(decoded.stdout)
            except Exception:
                continue
            entitlements = data.get("Entitlements", {}) if isinstance(data, dict) else {}
            app_identifier = str(entitlements.get("application-identifier", ""))
            profile_name = str(data.get("Name", "")) if isinstance(data, dict) else ""
            if ".org.openmates.app" not in app_identifier and "org.openmates.app" not in profile_name:
                continue
            target = backup_dir / profile.name
            try:
                profile.replace(target)
            except FileNotFoundError:
                continue
            moved += 1
    print(f"provisioning_profile_cleanup=moved:{moved}")


def has_app_store_connect_api_auth():
    return all(
        os.environ.get(name)
        for name in (
            "APP_STORE_CONNECT_API_KEY_PATH",
            "APP_STORE_CONNECT_API_KEY_ID",
            "APP_STORE_CONNECT_API_ISSUER_ID",
        )
    )


def provisioning_profile_dirs():
    return [
        pathlib.Path.home() / "Library" / "MobileDevice" / "Provisioning Profiles",
        pathlib.Path.home() / "Library" / "Developer" / "Xcode" / "UserData" / "Provisioning Profiles",
    ]


def decoded_profile(profile_path):
    decoded = subprocess.run(["security", "cms", "-D", "-i", str(profile_path)], capture_output=True, timeout=30)
    if decoded.returncode != 0:
        return None
    try:
        data = plistlib.loads(decoded.stdout)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def profile_bundle_identifier(profile_data):
    entitlements = profile_data.get("Entitlements", {}) if isinstance(profile_data, dict) else {}
    app_identifier = str(entitlements.get("application-identifier", ""))
    for identifier in BUNDLE_IDS:
        if app_identifier.endswith(f".{identifier}"):
            return identifier
    profile_name = str(profile_data.get("Name", ""))
    return next((identifier for identifier in BUNDLE_IDS if identifier in profile_name), None)


def profile_has_required_entitlements(identifier, profile_data):
    entitlements = profile_data.get("Entitlements", {}) if isinstance(profile_data, dict) else {}
    if identifier in REQUIRED_APP_GROUP_BUNDLE_IDS:
        app_groups = entitlements.get("com.apple.security.application-groups", [])
        if APP_GROUP_IDENTIFIER not in app_groups:
            print(f"profile_app_group=missing:{identifier}:{APP_GROUP_IDENTIFIER}")
            return False
    if identifier in REQUIRED_KEYCHAIN_GROUP_BUNDLE_IDS:
        keychain_groups = entitlements.get("keychain-access-groups", [])
        keychain_group = required_keychain_group(identifier, entitlements)
        if keychain_group not in keychain_groups:
            print(f"profile_keychain_group=missing:{identifier}:{keychain_group}")
            return False
    return True


def required_keychain_group(identifier, entitlements):
    app_identifier = str(entitlements.get("application-identifier", ""))
    if app_identifier.endswith(f".{identifier}"):
        return app_identifier
    return identifier


def load_installed_app_store_profiles():
    profile_names.clear()
    found = {}
    for profile_dir in provisioning_profile_dirs():
        if not profile_dir.exists():
            continue
        for profile_path in profile_dir.glob(f"*.{profile_extension}"):
            profile_data = decoded_profile(profile_path)
            if not profile_data:
                continue
            identifier = profile_bundle_identifier(profile_data)
            if not identifier or not profile_has_required_entitlements(identifier, profile_data):
                continue
            profile_uuid = profile_data.get("UUID")
            if not profile_uuid:
                continue
            found[identifier] = profile_uuid

    missing = [identifier for identifier in BUNDLE_IDS if identifier not in found]
    if missing:
        print(f"installed_profiles=missing:{','.join(missing)}")
        return False
    profile_names.update(found)
    for identifier in BUNDLE_IDS:
        print(f"installed_profile=passed:{identifier}")
    return True


def restore_latest_openmates_profile_backup():
    backup_roots = [pathlib.Path(tempfile.gettempdir()), pathlib.Path("/var/folders")]
    backups_by_path = {}
    for root in backup_roots:
        if not root.exists():
            continue
        for dirpath, dirnames, _filenames in os.walk(root):
            path = pathlib.Path(dirpath)
            if path.name.startswith("openmates-profiles-backup-"):
                backups_by_path[str(path)] = path
                dirnames[:] = []
    backups = sorted(
        backups_by_path.values(),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    if not backups:
        print("provisioning_profile_restore=backup_missing")
        return
    target_dir = provisioning_profile_dirs()[0]
    target_dir.mkdir(parents=True, exist_ok=True)
    restored = 0
    restored_identifiers = set()
    for backup in backups:
        for profile_path in backup.glob(f"*.{profile_extension}"):
            profile_data = decoded_profile(profile_path)
            identifier = profile_bundle_identifier(profile_data) if profile_data else None
            if not identifier:
                continue
            target = target_dir / profile_path.name
            if not target.exists():
                profile_path.replace(target)
                restored += 1
            restored_identifiers.add(identifier)
        if all(identifier in restored_identifiers for identifier in BUNDLE_IDS):
            break
    print(f"provisioning_profile_restore=restored:{restored}")


def stamp_unsigned_macos_archive_entitlements():
    if target_platform != "macos":
        return
    app_path = archive_path / "Products" / "Applications" / "OpenMates.app"
    extension_path = app_path / "Contents" / "PlugIns" / "OpenMatesShareExtension_macOS.appex"
    targets = (
        (extension_path, pathlib.Path("apple/OpenMatesShareExtensionMacOS/OpenMatesShareExtensionMacOS.entitlements")),
        (app_path, pathlib.Path("apple/OpenMates/Resources/OpenMatesPasskey.entitlements")),
    )
    for bundle_path, entitlements_path in targets:
        sign = subprocess.run(
            [
                "codesign",
                "--force",
                "--sign",
                "-",
                "--entitlements",
                str(entitlements_path),
                "--timestamp=none",
                str(bundle_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if sign.returncode != 0:
            print_tail("archive_entitlements_stamp", sign.stdout + sign.stderr, derived, limit=120)
            sys.exit(sign.returncode)
    print("archive_entitlements_stamp=passed")


def assert_ios_archive_passkey_entitlements():
    if target_platform != "ios":
        return
    app_binary = archive_path / "Products" / "Applications" / "OpenMates.app" / "OpenMates"
    entitlements = subprocess.run(
        ["codesign", "-d", "--entitlements", ":-", str(app_binary)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if entitlements.returncode != 0:
        print_tail("archive_entitlements_check", entitlements.stdout + entitlements.stderr, derived, limit=120)
        sys.exit(entitlements.returncode)
    text = entitlements.stdout + entitlements.stderr
    required = {
        "associated_domains": "com.apple.developer.associated-domains",
        "openmates_webcredentials": "webcredentials:openmates.org",
        "app_group": APP_GROUP_IDENTIFIER,
    }
    missing = [name for name, marker in required.items() if marker not in text]
    if missing:
        print(f"archive_entitlements_check=missing:{','.join(missing)}")
        print("hint=iOS archive is not signed with OpenMates passkey/app-group entitlements; do not upload this build.")
        sys.exit(1)
    print("archive_entitlements_check=passed")


def assert_ios_archive_embeds_watch_companion():
    if target_platform != "ios":
        return
    app_path = archive_path / "Products" / "Applications" / "OpenMates.app"
    watch_apps = sorted((app_path / "Watch").glob("*.app"))
    if not watch_apps:
        print("archive_watch_companion=missing")
        print("hint=iOS TestFlight uploads must carry the OpenMates Watch companion app; do not upload a watchOS-only archive separately.")
        sys.exit(1)
    info_path = watch_apps[0] / "Info.plist"
    if not info_path.exists():
        print("archive_watch_companion=missing_info_plist")
        sys.exit(1)
    try:
        with info_path.open("rb") as handle:
            info = plistlib.load(handle)
    except Exception as exc:
        print(f"archive_watch_companion=invalid_info_plist:{type(exc).__name__}")
        sys.exit(1)
    bundle_id = info.get("CFBundleIdentifier")
    companion_id = info.get("WKCompanionAppBundleIdentifier")
    executable = info.get("CFBundleExecutable")
    modern_watch_app = info.get("WKApplication") is True
    legacy_watchkit_app = info.get("WKWatchKitApp") is True
    runs_independently = info.get("WKRunsIndependentlyOfCompanionApp")
    if bundle_id != "org.openmates.app.watch" or companion_id != "org.openmates.app":
        print("archive_watch_companion=invalid_metadata")
        print(f"watch_bundle_id={bundle_id or 'missing'}")
        print(f"watch_companion_bundle_id={companion_id or 'missing'}")
        sys.exit(1)
    if not executable:
        print("archive_watch_companion=missing_executable_metadata")
        sys.exit(1)
    if modern_watch_app:
        if runs_independently is not True:
            print("archive_watch_companion=invalid_modern_metadata")
            print(f"watch_runs_independently={runs_independently!r}")
            sys.exit(1)
        if (watch_apps[0] / "PlugIns" / "OpenMatesWatchExtension.appex").exists():
            print("archive_watch_companion=unexpected_extension")
            sys.exit(1)
        print("archive_watch_companion=passed")
        return
    if not legacy_watchkit_app:
        print("archive_watch_companion=missing_watch_application_marker")
        sys.exit(1)
    extension_path = watch_apps[0] / "PlugIns" / "OpenMatesWatchExtension.appex" / "Info.plist"
    if not extension_path.exists():
        print("archive_watch_companion=missing_extension")
        sys.exit(1)
    try:
        with extension_path.open("rb") as handle:
            extension_info = plistlib.load(handle)
    except Exception as exc:
        print(f"archive_watch_companion=invalid_extension_info_plist:{type(exc).__name__}")
        sys.exit(1)
    extension_id = extension_info.get("CFBundleIdentifier")
    extension_executable = extension_info.get("CFBundleExecutable")
    extension_attributes = extension_info.get("NSExtension", {}).get("NSExtensionAttributes", {})
    runs_independently = extension_info.get("WKRunsIndependentlyOfCompanionApp")
    if extension_id != "org.openmates.app.watch.watchkitextension" or not extension_executable or extension_attributes.get("WKAppBundleIdentifier") != "org.openmates.app.watch" or runs_independently is not True:
        print("archive_watch_companion=invalid_extension_metadata")
        print(f"watch_extension_bundle_id={extension_id or 'missing'}")
        print(f"watch_extension_executable={extension_executable or 'missing'}")
        print(f"watch_extension_app_bundle_id={extension_attributes.get('WKAppBundleIdentifier') or 'missing'}")
        print(f"watch_extension_runs_independently={runs_independently!r}")
        sys.exit(1)
    print("archive_watch_companion=passed")



preflight_signing()
build_translations()
build_tokens()
if has_app_store_connect_api_auth():
    clean_openmates_provisioning_profiles()
    sync_bundle_capabilities()
    create_or_download_app_store_profiles()
else:
    print("profile_create=missing_app_store_connect_api_auth")
    if not load_installed_app_store_profiles():
        restore_latest_openmates_profile_backup()
        if not load_installed_app_store_profiles():
            print("hint=Set App Store Connect API credentials in ~/.config/openmates/apple-remote.json or keep valid OpenMates App Store profiles installed on the Mac.")
            sys.exit(2)


derived = tempfile.mkdtemp(prefix="openmates-testflight-")
archive_path = pathlib.Path(derived) / archive_filename
export_path = pathlib.Path(derived) / "export"
export_options_path = pathlib.Path(derived) / "ExportOptions.plist"

export_options = {
    "destination": "export" if target_platform == "watchos" else "upload",
    "method": "app-store-connect",
    "provisioningProfiles": profile_names,
    "signingCertificate": distribution_identity_sha1 if target_platform == "macos" else distribution_identity_name,
    "signingStyle": "manual",
    "teamID": "Z9B2YFKN2X",
    "testFlightInternalTestingOnly": internal_only,
    "uploadSymbols": True,
}
export_options["manageAppVersionAndBuildNumber"] = requested_build_number is None
if target_platform == "macos":
    export_options["installerSigningCertificate"] = installer_identity_sha1
with export_options_path.open("wb") as handle:
    plistlib.dump(export_options, handle)

common_auth_args = auth_args()
archive_cmd = [
    "xcodebuild",
    "-project",
    "apple/OpenMates.xcodeproj",
    "-scheme",
    scheme_name,
    "-configuration",
    "Release",
    "-destination",
    archive_destination,
    "-archivePath",
    str(archive_path),
    "DEVELOPMENT_TEAM=Z9B2YFKN2X",
    "archive",
]
if archive_without_signing:
    archive_cmd.insert(-1, "CODE_SIGNING_ALLOWED=NO")
else:
    archive_cmd.insert(-2, "-allowProvisioningUpdates")
    archive_cmd[-2:-2] = common_auth_args
if build_keychain_path and not archive_without_signing:
    archive_cmd.insert(-1, f"OTHER_CODE_SIGN_FLAGS=--keychain {build_keychain_path}")
if requested_build_number:
    archive_cmd.insert(-1, f"CURRENT_PROJECT_VERSION={requested_build_number}")
if target_platform == "watchos":
    watch_profile = profile_names.get("org.openmates.app.watch")
    if not watch_profile:
        print("archive_status=missing_watch_profile")
        sys.exit(1)
    archive_cmd[-1:-1] = [
        "CODE_SIGN_STYLE=Manual",
        f"CODE_SIGN_IDENTITY={distribution_identity_name}",
        f"PROVISIONING_PROFILE_SPECIFIER={watch_profile}",
    ]

print("archive_status=started")
archive = subprocess.run(archive_cmd, capture_output=True, text=True, timeout=1800)
if archive.returncode != 0:
    print_tail("archive_status", archive.stdout + archive.stderr, derived)
    sys.exit(archive.returncode)
print("archive_status=passed")
stamp_unsigned_macos_archive_entitlements()
assert_ios_archive_passkey_entitlements()
assert_ios_archive_embeds_watch_companion()

export_cmd = [
    "xcodebuild",
    "-exportArchive",
    "-archivePath",
    str(archive_path),
    "-exportPath",
    str(export_path),
    "-exportOptionsPlist",
    str(export_options_path),
    "-allowProvisioningUpdates",
    *common_auth_args,
]

if testflight_whats_new and target_platform != "watchos":
    while len(previous_testflight_build_ids) < 20:
        previous_build = latest_app_store_build_for_notes(
            excluded_build_ids=previous_testflight_build_ids,
            wait_for_new=False,
        )
        if not previous_build or not previous_build.get("id"):
            break
        previous_testflight_build_ids.add(previous_build["id"])
    print(f"whats_new_previous_build_count={len(previous_testflight_build_ids)}")

print("upload_status=started")
export = subprocess.run(export_cmd, capture_output=True, text=True, timeout=1800)
if export.returncode != 0:
    export_output = export.stdout + export.stderr
    print_tail("upload_status", export_output, derived)
    distribution_log_dirs = [pathlib.Path(derived)]
    for match in re.findall(r'Created bundle at path "([^"]+)"', export_output):
        distribution_log_dirs.append(pathlib.Path(match))
    for log_dir in distribution_log_dirs:
        for log_path in log_dir.glob("**/*.log"):
            try:
                log_text = log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "requires a provisioning profile" in log_text or "Provisioning" in log_text:
                print_tail("export_log", log_text, derived, limit=220)
    sys.exit(export.returncode)
if target_platform == "watchos":
    ipa_candidates = sorted(export_path.rglob("*.ipa"))
    if not ipa_candidates:
        print("upload_status=no_watch_ipa")
        sys.exit(1)
    upload = subprocess.run(
        [
            "xcrun",
            "altool",
            "--upload-package",
            str(ipa_candidates[0]),
            "--api-key",
            os.environ["APP_STORE_CONNECT_API_KEY_ID"],
            "--api-issuer",
            os.environ["APP_STORE_CONNECT_API_ISSUER_ID"],
            "--p8-file-path",
            os.environ["APP_STORE_CONNECT_API_KEY_PATH"],
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if upload.returncode != 0:
        print_tail("upload_status", upload.stdout + upload.stderr, derived)
        sys.exit(upload.returncode)
print("upload_status=passed")
upsert_testflight_whats_new()
for line in (export.stdout + export.stderr).replace(derived, "<macos-peer-tmp>").splitlines()[-40:]:
    print(line)
'''


RELEASE_ARCHIVE_PREFLIGHT_SCRIPT = r'''
import pathlib
import plistlib
import shutil
import subprocess
import sys
import tempfile

target_platform = sys.argv[1]
platforms = {
    "ios": ("OpenMates_iOS", "generic/platform=iOS", "OpenMates.xcarchive"),
    "macos": ("OpenMates_macOS", "generic/platform=macOS", "OpenMatesMac.xcarchive"),
    "watchos": ("OpenMatesWatch", "generic/platform=watchOS", "OpenMatesWatch.xcarchive"),
}
if target_platform not in platforms:
    print(f"release_archive_preflight=unsupported:{target_platform}")
    sys.exit(2)

scheme_name, archive_destination, archive_filename = platforms[target_platform]
derived = tempfile.mkdtemp(prefix="openmates-release-preflight-")
archive_path = pathlib.Path(derived) / archive_filename

def fail(label, result):
    print(f"release_archive_preflight={label}")
    for line in (result.stdout + result.stderr).replace(derived, "<macos-peer-tmp>").splitlines()[-120:]:
        print(line)
    sys.exit(result.returncode or 1)

def assert_ios_archive_passkey_entitlements():
    if target_platform != "ios":
        return
    entitlements_path = pathlib.Path("apple/OpenMates/Resources/OpenMatesPasskey.entitlements")
    try:
        with entitlements_path.open("rb") as handle:
            entitlements = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        print("release_archive_preflight=invalid_ios_entitlements")
        sys.exit(1)
    domains = entitlements.get("com.apple.developer.associated-domains", [])
    groups = entitlements.get("com.apple.security.application-groups", [])
    if "webcredentials:openmates.org" not in domains or "group.org.openmates.app.shared" not in groups:
        print("release_archive_preflight=missing_ios_entitlements")
        sys.exit(1)

def assert_ios_archive_embeds_watch_companion():
    if target_platform != "ios":
        return
    watch_apps = sorted((archive_path / "Products" / "Applications" / "OpenMates.app" / "Watch").glob("*.app"))
    if not watch_apps:
        print("release_archive_preflight=missing_watch_companion")
        sys.exit(1)
    info_path = watch_apps[0] / "Info.plist"
    try:
        with info_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        print("release_archive_preflight=invalid_watch_companion")
        sys.exit(1)
    if info.get("CFBundleIdentifier") != "org.openmates.app.watch" or info.get("WKCompanionAppBundleIdentifier") != "org.openmates.app":
        print("release_archive_preflight=invalid_watch_companion")
        sys.exit(1)

try:
    archive_cmd = [
        "xcodebuild", "-project", "apple/OpenMates.xcodeproj", "-scheme", scheme_name,
        "-configuration", "Release", "-destination", archive_destination,
        "-derivedDataPath", str(pathlib.Path(derived) / "DerivedData"),
        "-archivePath", str(archive_path),
        "CODE_SIGNING_ALLOWED=NO", "CODE_SIGNING_REQUIRED=NO", "archive",
    ]
    result = subprocess.run(archive_cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        fail("archive_failed", result)
    assert_ios_archive_passkey_entitlements()
    assert_ios_archive_embeds_watch_companion()
    print(f"release_archive_preflight=passed:{target_platform}")
finally:
    shutil.rmtree(derived, ignore_errors=True)
'''


XCODE_CACHE_REPORT_SCRIPT = r'''
import os
import subprocess
from pathlib import Path

paths = {
    "derived-data": "~/Library/Developer/Xcode/DerivedData",
    "module-cache": "~/Library/Developer/Xcode/DerivedData/ModuleCache.noindex",
    "swiftpm-cache": "~/Library/Caches/org.swift.swiftpm",
    "simulator-caches": "~/Library/Developer/CoreSimulator/Caches",
    "archives": "~/Library/Developer/Xcode/Archives",
    "device-support": "~/Library/Developer/Xcode/iOS DeviceSupport",
}


def size_mb(path):
    expanded = Path(os.path.expanduser(path))
    if not expanded.exists():
        return None
    result = subprocess.run(["du", "-sk", str(expanded)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    return int(result.stdout.split()[0]) // 1024


disk = subprocess.run(["df", "-H", os.path.expanduser("~")], capture_output=True, text=True, check=False)
print("disk_usage_home_start")
for line in disk.stdout.splitlines():
    print(line)
print("disk_usage_home_end")
for label, path in paths.items():
    value = size_mb(path)
    print(f"cache_{label}_mb={value if value is not None else 'missing'}")
'''


XCODE_CACHE_CLEAN_SCRIPT = r'''
import os
import shutil
import sys
from pathlib import Path

targets = {
    "derived-data": "~/Library/Developer/Xcode/DerivedData",
    "module-cache": "~/Library/Developer/Xcode/DerivedData/ModuleCache.noindex",
    "swiftpm-cache": "~/Library/Caches/org.swift.swiftpm",
    "simulator-caches": "~/Library/Developer/CoreSimulator/Caches",
    "device-support": "~/Library/Developer/Xcode/iOS DeviceSupport",
}

requested = sys.argv[1:]
if not requested:
    print("clean_status=no_targets")
    sys.exit(2)

for target in requested:
    if target not in targets:
        print(f"clean_status=unknown_target:{target}")
        sys.exit(2)

for target in requested:
    path = Path(os.path.expanduser(targets[target]))
    if not path.exists():
        print(f"clean_{target}=missing")
        continue
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    print(f"clean_{target}=removed")
print("clean_status=passed")
'''


ENSURE_IOS_DISTRIBUTION_CERTIFICATE_SCRIPT = r'''
import base64
import json
import os
import pathlib
import shutil
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

create = sys.argv[1] == "1"
certificate_type = sys.argv[2] if len(sys.argv) > 2 else "IOS_DISTRIBUTION"
team_id = "Z9B2YFKN2X"
if certificate_type == "IOS_DISTRIBUTION":
    identity_label = "distribution_identity"
    identity_markers = ("Apple Distribution:", "iPhone Distribution:")
    certificate_common_name = "OpenMates iOS Distribution"
elif certificate_type == "DISTRIBUTION":
    identity_label = "distribution_identity"
    identity_markers = ("Apple Distribution:",)
    certificate_common_name = "OpenMates Apple Distribution"
elif certificate_type == "MAC_INSTALLER_DISTRIBUTION":
    identity_label = "installer_distribution_identity"
    identity_markers = ("3rd Party Mac Developer Installer", "Mac Installer Distribution")
    certificate_common_name = "OpenMates Mac Installer Distribution"
elif certificate_type == "DEVELOPMENT":
    identity_label = "development_identity"
    identity_markers = ("Apple Development:",)
    certificate_common_name = "OpenMates Apple Development"
elif certificate_type == "IOS_DEVELOPMENT":
    identity_label = "development_identity"
    identity_markers = ("iPhone Developer:",)
    certificate_common_name = "OpenMates iOS Development"
else:
    print(f"unsupported_certificate_type={certificate_type}")
    sys.exit(2)


def print_tail(label, text, tmp_dir=None, limit=80):
    print(f"{label}=failed")
    sanitized = text
    if tmp_dir:
        sanitized = sanitized.replace(tmp_dir, "<macos-peer-tmp>")
    api_key_path = os.environ.get("APP_STORE_CONNECT_API_KEY_PATH")
    if api_key_path:
        sanitized = sanitized.replace(api_key_path, "<app-store-connect-api-key>")
    for line in sanitized.splitlines()[-limit:]:
        print(line)


def parse_keychain_list(output):
    keychains = []
    for line in output.splitlines():
        cleaned = line.strip().strip('"')
        if cleaned:
            keychains.append(cleaned)
    return keychains


def build_keychain():
    config_dir = pathlib.Path.home() / ".config" / "openmates"
    config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    password_path = config_dir / "apple-build-keychain-password"
    if password_path.exists():
        password = password_path.read_text(encoding="utf-8").strip()
    else:
        password = secrets.token_urlsafe(32)
        password_path.write_text(password, encoding="utf-8")
        password_path.chmod(0o600)

    keychain = pathlib.Path.home() / "Library" / "Keychains" / "openmates-build.keychain-db"
    if not keychain.exists():
        create_keychain = subprocess.run(["security", "create-keychain", "-p", password, str(keychain)], capture_output=True, text=True, timeout=30)
        if create_keychain.returncode != 0:
            print_tail("build_keychain_create", create_keychain.stdout + create_keychain.stderr)
            sys.exit(create_keychain.returncode)

    unlock = subprocess.run(["security", "unlock-keychain", "-p", password, str(keychain)], capture_output=True, text=True, timeout=30)
    if unlock.returncode != 0:
        print_tail("build_keychain_unlock", unlock.stdout + unlock.stderr)
        sys.exit(unlock.returncode)

    settings = subprocess.run(["security", "set-keychain-settings", "-lut", "21600", str(keychain)], capture_output=True, text=True, timeout=30)
    if settings.returncode != 0:
        print_tail("build_keychain_settings", settings.stdout + settings.stderr)
        sys.exit(settings.returncode)

    current = subprocess.run(["security", "list-keychains", "-d", "user"], capture_output=True, text=True, timeout=30)
    existing = parse_keychain_list(current.stdout) if current.returncode == 0 else []
    ordered = [str(keychain), *[item for item in existing if item != str(keychain)]]
    search_list = subprocess.run(["security", "list-keychains", "-d", "user", "-s", *ordered], capture_output=True, text=True, timeout=30)
    if search_list.returncode != 0:
        print_tail("build_keychain_search_list", search_list.stdout + search_list.stderr)
        sys.exit(search_list.returncode)

    return keychain, password


def existing_build_keychain_args():
    password_path = pathlib.Path.home() / ".config" / "openmates" / "apple-build-keychain-password"
    keychain = pathlib.Path.home() / "Library" / "Keychains" / "openmates-build.keychain-db"
    if not keychain.exists() or not password_path.exists():
        return []
    password = password_path.read_text(encoding="utf-8").strip()
    unlock = subprocess.run(["security", "unlock-keychain", "-p", password, str(keychain)], capture_output=True, text=True, timeout=30)
    if unlock.returncode != 0:
        print_tail("build_keychain_unlock", unlock.stdout + unlock.stderr)
        sys.exit(unlock.returncode)
    return [str(keychain)]


def has_requested_identity():
    keychain_args = existing_build_keychain_args()
    if certificate_type == "MAC_INSTALLER_DISTRIBUTION":
        certificate = subprocess.run(
            ["security", "find-certificate", "-a", "-c", "3rd Party Mac Developer Installer", *keychain_args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if certificate.returncode not in (0, 44):
            print_tail("identity_check", certificate.stdout + certificate.stderr)
            sys.exit(certificate.returncode)
        return any(marker in certificate.stdout for marker in identity_markers)
    identities = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning", *keychain_args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if identities.returncode != 0:
        print_tail("identity_check", identities.stdout + identities.stderr)
        sys.exit(identities.returncode)
    return any(any(marker in line for marker in identity_markers) for line in identities.stdout.splitlines())


def require_env(name):
    value = os.environ.get(name)
    if not value:
        print(f"missing_env={name}")
        sys.exit(2)
    return value


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def der_ecdsa_to_raw_jws_signature(der_signature):
    if len(der_signature) < 8 or der_signature[0] != 0x30:
        raise ValueError("Unexpected ECDSA signature format")
    index = 2
    if der_signature[1] & 0x80:
        length_bytes = der_signature[1] & 0x7F
        index = 2 + length_bytes
    if der_signature[index] != 0x02:
        raise ValueError("Missing ECDSA R integer")
    r_length = der_signature[index + 1]
    r_start = index + 2
    r = der_signature[r_start:r_start + r_length].lstrip(b"\x00")
    s_index = r_start + r_length
    if der_signature[s_index] != 0x02:
        raise ValueError("Missing ECDSA S integer")
    s_length = der_signature[s_index + 1]
    s_start = s_index + 2
    s = der_signature[s_start:s_start + s_length].lstrip(b"\x00")
    return r.rjust(32, b"\x00") + s.rjust(32, b"\x00")


def app_store_connect_jwt(key_path, key_id, issuer_id):
    now = int(time.time())
    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    payload = {"iss": issuer_id, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"}
    signing_input = ".".join([
        b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ])
    signer = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", key_path, "-binary"],
        input=signing_input.encode("ascii"),
        capture_output=True,
        timeout=30,
    )
    if signer.returncode != 0:
        print_tail("jwt_signing", signer.stderr.decode("utf-8", "replace"))
        sys.exit(signer.returncode)
    try:
        signature = der_ecdsa_to_raw_jws_signature(signer.stdout)
    except ValueError as exc:
        print(f"jwt_signing=failed:{exc}")
        sys.exit(1)
    return f"{signing_input}.{b64url(signature)}"


def create_certificate(csr_content):
    key_path = os.path.expanduser(require_env("APP_STORE_CONNECT_API_KEY_PATH"))
    key_id = require_env("APP_STORE_CONNECT_API_KEY_ID")
    issuer_id = require_env("APP_STORE_CONNECT_API_ISSUER_ID")
    token = app_store_connect_jwt(key_path, key_id, issuer_id)
    body = json.dumps({
        "data": {
            "type": "certificates",
            "attributes": {
                "certificateType": certificate_type,
                "csrContent": csr_content,
            },
        }
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.appstoreconnect.apple.com/v1/certificates",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", "replace")
        print(f"certificate_create_http_status={exc.code}")
        print_tail("certificate_create", body_text)
        if exc.code == 403:
            print("hint=App Store Connect API key needs certificate access, or an Account Holder/Admin must create the Apple Distribution certificate.")
        if exc.code == 409:
            print("hint=Apple may already have the maximum active distribution certificates; revoke an unused one or download/import an existing certificate with its private key.")
        sys.exit(1)


if has_requested_identity():
    print(f"{identity_label}=present")
    sys.exit(0)

print(f"{identity_label}=missing")
if not create:
    print(f"hint=Run with --create to generate a local private key, request an {certificate_type} certificate, and import both into the Mac build keychain.")
    sys.exit(1)

tmp_dir = tempfile.mkdtemp(prefix="openmates-ios-distribution-cert-")
try:
    private_key = pathlib.Path(tmp_dir) / "openmates-ios-distribution.key"
    csr_path = pathlib.Path(tmp_dir) / "openmates-ios-signing.csr"
    cert_path = pathlib.Path(tmp_dir) / "openmates-ios-signing.cer"

    keygen = subprocess.run(["openssl", "genrsa", "-out", str(private_key), "2048"], capture_output=True, text=True, timeout=30)
    if keygen.returncode != 0:
        print_tail("private_key_create", keygen.stdout + keygen.stderr, tmp_dir)
        sys.exit(keygen.returncode)

    csr = subprocess.run(
        ["openssl", "req", "-new", "-key", str(private_key), "-out", str(csr_path), "-subj", f"/CN={certificate_common_name}/OU={team_id}/O=OpenMates"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if csr.returncode != 0:
        print_tail("csr_create", csr.stdout + csr.stderr, tmp_dir)
        sys.exit(csr.returncode)

    keychain, keychain_password = build_keychain()
    import_key = subprocess.run(
        ["security", "import", str(private_key), "-k", str(keychain), "-T", "/usr/bin/codesign", "-T", "/usr/bin/productbuild", "-T", "/usr/bin/xcodebuild", "-T", "/usr/bin/security"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if import_key.returncode != 0:
        print_tail("private_key_import", import_key.stdout + import_key.stderr, tmp_dir)
        print("hint=The dedicated OpenMates build keychain could not import the private key.")
        sys.exit(import_key.returncode)

    partition_list = subprocess.run(
        ["security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:", "-s", "-k", keychain_password, str(keychain)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if partition_list.returncode != 0:
        print_tail("private_key_partition_list", partition_list.stdout + partition_list.stderr, tmp_dir)
        sys.exit(partition_list.returncode)

    response = create_certificate(csr_path.read_text(encoding="utf-8"))
    certificate_content = response.get("data", {}).get("attributes", {}).get("certificateContent")
    if not certificate_content:
        print("certificate_create=missing_certificate_content")
        sys.exit(1)
    cert_path.write_bytes(base64.b64decode(certificate_content))

    import_cert = subprocess.run(["security", "import", str(cert_path), "-k", str(keychain)], capture_output=True, text=True, timeout=60)
    if import_cert.returncode != 0:
        print_tail("certificate_import", import_cert.stdout + import_cert.stderr, tmp_dir)
        sys.exit(import_cert.returncode)
finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)

if has_requested_identity():
    print("certificate_create=passed")
    print(f"{identity_label}=present")
    sys.exit(0)

print("certificate_create=imported_but_identity_missing")
print("hint=Open Keychain Access and verify the Apple signing certificate is paired with its private key.")
sys.exit(1)
'''


REVOKE_APPLE_CERTIFICATE_SCRIPT = r'''
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

target_sha1 = sys.argv[1].replace(":", "").upper()
list_only = target_sha1 == "LIST"


def require_env(name):
    value = os.environ.get(name)
    if not value:
        print(f"missing_env={name}")
        sys.exit(2)
    return value


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def der_ecdsa_to_raw_jws_signature(der_signature):
    if len(der_signature) < 8 or der_signature[0] != 0x30:
        raise ValueError("Unexpected ECDSA signature format")
    index = 2
    if der_signature[1] & 0x80:
        length_bytes = der_signature[1] & 0x7F
        index = 2 + length_bytes
    if der_signature[index] != 0x02:
        raise ValueError("Missing ECDSA R integer")
    r_length = der_signature[index + 1]
    r_start = index + 2
    r = der_signature[r_start:r_start + r_length].lstrip(b"\x00")
    s_index = r_start + r_length
    if der_signature[s_index] != 0x02:
        raise ValueError("Missing ECDSA S integer")
    s_length = der_signature[s_index + 1]
    s_start = s_index + 2
    s = der_signature[s_start:s_start + s_length].lstrip(b"\x00")
    return r.rjust(32, b"\x00") + s.rjust(32, b"\x00")


def app_store_connect_jwt(key_path, key_id, issuer_id):
    now = int(time.time())
    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    payload = {"iss": issuer_id, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"}
    signing_input = ".".join([
        b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ])
    signer = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", os.path.expanduser(key_path), "-binary"],
        input=signing_input.encode("ascii"),
        capture_output=True,
        timeout=30,
    )
    if signer.returncode != 0:
        print("jwt_signing=failed")
        sys.exit(signer.returncode)
    signature = der_ecdsa_to_raw_jws_signature(signer.stdout)
    return f"{signing_input}.{b64url(signature)}"


def api_request(token, method, path):
    request = urllib.request.Request(
        f"https://api.appstoreconnect.apple.com{path}",
        headers={"Authorization": f"Bearer {token}"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
            return json.loads(body.decode("utf-8")) if body else {}
    except urllib.error.HTTPError as exc:
        print(f"api_http_status={exc.code}")
        print(exc.read().decode("utf-8", "replace"))
        sys.exit(1)


token = app_store_connect_jwt(
    require_env("APP_STORE_CONNECT_API_KEY_PATH"),
    require_env("APP_STORE_CONNECT_API_KEY_ID"),
    require_env("APP_STORE_CONNECT_API_ISSUER_ID"),
)

query = urllib.parse.urlencode({"limit": "200"})
certificates = api_request(token, "GET", f"/v1/certificates?{query}").get("data", [])
for certificate in certificates:
    attributes = certificate.get("attributes", {})
    content = attributes.get("certificateContent")
    if not content:
        continue
    der = base64.b64decode(content)
    sha1 = hashlib.sha1(der).hexdigest().upper()
    if list_only:
        print(f"certificate={sha1} type={attributes.get('certificateType', 'unknown')} name={attributes.get('name', attributes.get('displayName', 'unknown'))}")
        continue
    if sha1 != target_sha1:
        continue
    certificate_id = certificate.get("id")
    certificate_type = attributes.get("certificateType", "unknown")
    api_request(token, "DELETE", f"/v1/certificates/{certificate_id}")
    print(f"certificate_revoked={target_sha1}")
    print(f"certificate_type={certificate_type}")
    sys.exit(0)

if list_only:
    sys.exit(0)

print(f"certificate_not_found={target_sha1}")
sys.exit(1)
'''


APP_STORE_BUILDS_SCRIPT = r'''
import base64
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

bundle_id = sys.argv[1]
build_limit = sys.argv[2] if len(sys.argv) > 2 else "10"
require_changelogs = len(sys.argv) > 3 and sys.argv[3] == "1"
whats_new_locale = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else "en-US"
scan_all_builds = len(sys.argv) > 5 and sys.argv[5] == "1"
MIN_TESTFLIGHT_WHATS_NEW_LINES = 5


def require_env(name):
    value = os.environ.get(name)
    if not value:
        print(f"missing_env={name}")
        sys.exit(2)
    return value


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def der_ecdsa_to_raw_jws_signature(der_signature):
    index = 2
    if der_signature[1] & 0x80:
        index = 2 + (der_signature[1] & 0x7F)
    r_length = der_signature[index + 1]
    r_start = index + 2
    r = der_signature[r_start:r_start + r_length].lstrip(b"\x00")
    s_index = r_start + r_length
    s_length = der_signature[s_index + 1]
    s_start = s_index + 2
    s = der_signature[s_start:s_start + s_length].lstrip(b"\x00")
    return r.rjust(32, b"\x00") + s.rjust(32, b"\x00")


def app_store_connect_jwt():
    now = int(time.time())
    key_path = os.path.expanduser(require_env("APP_STORE_CONNECT_API_KEY_PATH"))
    header = {"alg": "ES256", "kid": require_env("APP_STORE_CONNECT_API_KEY_ID"), "typ": "JWT"}
    payload = {"iss": require_env("APP_STORE_CONNECT_API_ISSUER_ID"), "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"}
    signing_input = ".".join([
        b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ])
    signer = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", key_path, "-binary"],
        input=signing_input.encode("ascii"),
        capture_output=True,
        timeout=30,
        check=True,
    )
    return f"{signing_input}.{b64url(der_ecdsa_to_raw_jws_signature(signer.stdout))}"


def asc_get_url(url):
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {app_store_connect_jwt()}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def asc_get(path):
    return asc_get_url(f"https://api.appstoreconnect.apple.com/v1/{path}")


def collect_build_pages(path):
    pages = []
    response = asc_get(path)
    while True:
        pages.append(response)
        next_url = response.get("links", {}).get("next") if scan_all_builds else None
        if not next_url:
            return pages
        response = asc_get_url(next_url)


def whats_new_line_count(text):
    return len([line for line in text.splitlines() if line.strip()])


apps_query = urllib.parse.urlencode({"filter[bundleId]": bundle_id, "limit": "1"})
apps = asc_get(f"apps?{apps_query}").get("data", [])
print(f"apps={len(apps)}")
if not apps:
    sys.exit(0)

app_id = apps[0].get("id")
print(f"app_id={app_id}")
builds_query = urllib.parse.urlencode({
    "filter[app]": app_id,
    "include": "preReleaseVersion",
    "limit": "200" if scan_all_builds else build_limit,
    "sort": "-uploadedDate",
})
responses = collect_build_pages(f"builds?{builds_query}")
if not any(response.get("data") for response in responses):
    relationship_query = urllib.parse.urlencode({
        "include": "preReleaseVersion",
        "limit": "200" if scan_all_builds else build_limit,
        "sort": "-uploadedDate",
    })
    responses = collect_build_pages(f"apps/{app_id}/builds?{relationship_query}")
included = [item for response in responses for item in response.get("included", [])]
pre_release_versions = {
    item.get("id"): item.get("attributes", {})
    for item in included
    if item.get("type") == "preReleaseVersions"
}
builds = [item for response in responses for item in response.get("data", [])]
print(f"builds={len(builds)}")
if scan_all_builds:
    print("build_scan=complete")
changelog_failures = []
for build in builds:
    attributes = build.get("attributes", {})
    build_id = build.get("id")
    pre_release_id = build.get("relationships", {}).get("preReleaseVersion", {}).get("data", {}).get("id")
    pre_release = pre_release_versions.get(pre_release_id, {})
    print(
        "build="
        f"{build_id} "
        f"appVersion={pre_release.get('version')} "
        f"buildNumber={attributes.get('version')} "
        f"processingState={attributes.get('processingState')} "
        f"uploadedDate={attributes.get('uploadedDate')} "
        f"platform={pre_release.get('platform')} "
        f"train={pre_release.get('version')}"
    )
    if require_changelogs and build_id:
        localizations = asc_get(f"builds/{build_id}/betaBuildLocalizations?limit=200").get("data", [])
        matching = next(
            (
                item for item in localizations
                if item.get("attributes", {}).get("locale") == whats_new_locale
            ),
            None,
        )
        whats_new = (matching or {}).get("attributes", {}).get("whatsNew") or ""
        line_count = whats_new_line_count(whats_new)
        print(f"build_changelog_lines={build_id}:{line_count}:{whats_new_locale}")
        if line_count < MIN_TESTFLIGHT_WHATS_NEW_LINES:
            changelog_failures.append(
                f"{pre_release.get('version')}({attributes.get('version')}) lines={line_count} locale={whats_new_locale}"
            )

if require_changelogs:
    if changelog_failures:
        print("changelog_status=failed")
        for failure in changelog_failures:
            print(f"changelog_failure={failure}")
        sys.exit(1)
    print("changelog_status=passed")
'''


NEXT_UNIFIED_BUILD_NUMBER_SCRIPT = r'''
import re
import sys

output = sys.stdin.read()
apps_match = re.search(r"(?m)^apps=(\d+)$", output)
if not apps_match or int(apps_match.group(1)) < 1:
    sys.exit("App Store Connect app lookup failed")
if not re.search(r"(?m)^build_scan=complete$", output):
    sys.exit("App Store Connect build scan did not complete")

raw_build_numbers = re.findall(r"buildNumber=([^\s]+)", output)
if any(not re.fullmatch(r"\d{1,4}", value) for value in raw_build_numbers):
    sys.exit("App Store Connect contains a non-integer build number")

build_numbers = [int(value) for value in raw_build_numbers]
next_build_number = max(build_numbers, default=0) + 1
if next_build_number > 9999:
    sys.exit("App Store Connect build number range is exhausted")
print(next_build_number)
'''


TESTFLIGHT_CRASHES_SCRIPT = r'''
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

bundle_id = sys.argv[1]
limit = sys.argv[2]
platform = sys.argv[3]

key_path = os.environ.get("APP_STORE_CONNECT_API_KEY_PATH")
key_id = os.environ.get("APP_STORE_CONNECT_API_KEY_ID")
issuer_id = os.environ.get("APP_STORE_CONNECT_API_ISSUER_ID")
if not key_path or not key_id or not issuer_id:
    print("testflight_crashes_status=missing_app_store_connect_api_credentials")
    sys.exit(2)


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def der_ecdsa_to_raw_jws_signature(der):
    if len(der) < 8 or der[0] != 0x30:
        raise ValueError("Unexpected DER signature")
    index = 2
    if der[index] != 0x02:
        raise ValueError("Missing r integer")
    r_len = der[index + 1]
    r = der[index + 2:index + 2 + r_len]
    index += 2 + r_len
    if der[index] != 0x02:
        raise ValueError("Missing s integer")
    s_len = der[index + 1]
    s = der[index + 2:index + 2 + s_len]
    return r.lstrip(b"\x00").rjust(32, b"\x00")[-32:] + s.lstrip(b"\x00").rjust(32, b"\x00")[-32:]


def app_store_connect_jwt():
    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    now = int(time.time())
    payload = {"iss": issuer_id, "iat": now, "exp": now + 600, "aud": "appstoreconnect-v1"}
    signing_input = f"{b64url(json.dumps(header, separators=(',', ':')).encode('utf-8'))}.{b64url(json.dumps(payload, separators=(',', ':')).encode('utf-8'))}"
    signer = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", key_path, "-binary"],
        input=signing_input.encode("ascii"),
        capture_output=True,
        timeout=30,
        check=True,
    )
    return f"{signing_input}.{b64url(der_ecdsa_to_raw_jws_signature(signer.stdout))}"


def asc_get(path):
    request = urllib.request.Request(
        f"https://api.appstoreconnect.apple.com/v1/{path}",
        headers={"Authorization": f"Bearer {app_store_connect_jwt()}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"asc_http_status={exc.code}")
        body = exc.read().decode("utf-8", errors="replace")[:400]
        if body:
            print("asc_error=" + re.sub(r"\s+", " ", body))
        raise


def safe(value):
    text = str(value or "unknown")
    text = re.sub(r"[\w.+-]+@[\w.-]+", "<tester-email>", text)
    return re.sub(r"\s+", " ", text).strip()[:120]


def crash_summary(log_text):
    if not log_text:
        return "crash_log=unavailable"
    interesting_prefixes = (
        "Exception Type:",
        "Exception Subtype:",
        "Exception Codes:",
        "Termination Reason:",
        "Triggered by Thread:",
    )
    summaries = []
    lines = log_text.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(interesting_prefixes):
            summaries.append(safe(stripped))
        if len(summaries) >= 3:
            break
    for index, line in enumerate(lines):
        if " Crashed:" in line or line.strip().endswith(" Crashed"):
            summaries.append(safe(line.strip()))
            for frame in lines[index + 1:index + 7]:
                if "OpenMates" in frame or "org.openmates" in frame:
                    summaries.append("top_openmates_frame=" + safe(frame.strip()))
                    break
            break
    if not summaries:
        return "crash_log=present"
    return " | ".join(summaries[:5])


try:
    apps_query = urllib.parse.urlencode({"filter[bundleId]": bundle_id, "limit": "1"})
    apps = asc_get(f"apps?{apps_query}").get("data", [])
    if not apps:
        print("testflight_crashes_status=no_app_for_bundle")
        print(f"bundle_id={bundle_id}")
        sys.exit(0)

    app_id = apps[0].get("id")
    query = {
        "limit": limit,
        "sort": "-createdDate",
        "include": "build",
        "fields[betaFeedbackCrashSubmissions]": "createdDate,deviceModel,osVersion,appPlatform,devicePlatform,deviceFamily,buildBundleId,build,crashLog",
        "fields[builds]": "version,uploadedDate,processingState,preReleaseVersion",
    }
    if platform:
        query["filter[appPlatform]"] = platform
    response = asc_get(f"apps/{app_id}/betaFeedbackCrashSubmissions?{urllib.parse.urlencode(query)}")
    submissions = response.get("data", [])
    builds = {
        item.get("id"): item.get("attributes", {})
        for item in response.get("included", [])
        if item.get("type") == "builds"
    }
    print("testflight_crashes_status=ok")
    print(f"crash_submission_count={len(submissions)}")
    for index, submission in enumerate(submissions, 1):
        attrs = submission.get("attributes", {})
        build_id = submission.get("relationships", {}).get("build", {}).get("data", {}).get("id")
        build = builds.get(build_id, {})
        print(
            f"crash_{index}=id={safe(submission.get('id'))} "
            f"created={safe(attrs.get('createdDate'))} "
            f"platform={safe(attrs.get('appPlatform'))} "
            f"device={safe(attrs.get('deviceModel') or attrs.get('deviceFamily'))} "
            f"os={safe(attrs.get('osVersion'))} "
            f"build={safe(build.get('version') or build_id)} "
            f"bundle={safe(attrs.get('buildBundleId'))}"
        )
        crash_log = asc_get(
            "betaFeedbackCrashSubmissions/"
            f"{urllib.parse.quote(str(submission.get('id')))}"
            "/crashLog?fields[betaCrashLogs]=logText"
        )
        log_text = crash_log.get("data", {}).get("attributes", {}).get("logText", "")
        print(f"crash_{index}_summary={crash_summary(log_text)}")
except Exception as exc:
    print("testflight_crashes_status=failed")
    print("error=" + safe(type(exc).__name__))
    sys.exit(1)
'''


class AppleRemoteError(RuntimeError):
    """Raised for expected operator/configuration errors."""


@dataclass(frozen=True)
class RemoteConfig:
    target: str
    repo_path: str | None
    source: str


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def load_local_config(path: Path = LOCAL_CONFIG_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AppleRemoteError(f"Local config must be a JSON object: {path}")
    return {str(key): str(value) for key, value in data.items() if value is not None}


def _macos_peers(status: dict[str, Any]) -> list[dict[str, Any]]:
    peers = status.get("Peer", {})
    if not isinstance(peers, dict):
        return []
    matches: list[dict[str, Any]] = []
    for peer in peers.values():
        if not isinstance(peer, dict) or not peer.get("Online"):
            continue
        os_name = str(peer.get("OS", "")).lower()
        if os_name in {"macos", "darwin"} or "mac" in os_name:
            matches.append(peer)
    return matches


def discover_macos_tailscale_ip(
    *,
    runner: CommandRunner = default_runner,
) -> str:
    result = runner(["tailscale", "status", "--json"])
    if result.returncode != 0:
        raise AppleRemoteError("Tailscale status failed or Tailscale is not running")
    status = json.loads(result.stdout)
    peers = _macos_peers(status)
    if not peers:
        raise AppleRemoteError("No online macOS Tailscale peer found")
    if len(peers) > 1:
        raise AppleRemoteError("Multiple online macOS Tailscale peers found; set OPENMATES_APPLE_SSH_TARGET")
    ips = peers[0].get("TailscaleIPs", [])
    if not isinstance(ips, list) or not ips:
        raise AppleRemoteError("Online macOS peer has no Tailscale IP")
    return str(ips[0])


def resolve_remote_config(
    *,
    env: dict[str, str] | None = None,
    local_config: dict[str, str] | None = None,
    runner: CommandRunner = default_runner,
) -> RemoteConfig:
    env = env if env is not None else dict(os.environ)
    local_config = local_config if local_config is not None else load_local_config()

    target = env.get("OPENMATES_APPLE_SSH_TARGET") or local_config.get("ssh_target")
    repo_path = env.get("OPENMATES_APPLE_REPO_PATH") or local_config.get("repo_path")

    if target:
        return RemoteConfig(target=target, repo_path=repo_path, source="configured")

    user = env.get("OPENMATES_APPLE_SSH_USER") or local_config.get("ssh_user")
    if not user:
        raise AppleRemoteError(
            "Set OPENMATES_APPLE_SSH_TARGET or OPENMATES_APPLE_SSH_USER for auto-discovered Tailscale IP"
        )
    ip = discover_macos_tailscale_ip(runner=runner)
    return RemoteConfig(target=f"{user}@{ip}", repo_path=repo_path, source="tailscale")


def ssh_command(config: RemoteConfig, remote_command: str) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={DEFAULT_CONNECT_TIMEOUT_SECONDS}",
        config.target,
        remote_command,
    ]


def redact_output(text: str, config: RemoteConfig) -> str:
    redacted = text
    for value in {config.target, config.repo_path or ""}:
        if value:
            redacted = redacted.replace(value, f"<{REMOTE_LABEL}>")
    redacted = re.sub(r"/Users/[^\s:'\"]+", f"<{REMOTE_LABEL}-path>", redacted)
    redacted = re.sub(r"/var/folders/[^\s:'\"]+", f"<{REMOTE_LABEL}-tmp>", redacted)
    return redacted


def has_destructive_token(command: str) -> bool:
    normalized = " ".join(command.split())
    multi_word_tokens = {token for token in DESTRUCTIVE_TOKENS if " " in token}
    if any(token in normalized for token in multi_word_tokens):
        return True
    try:
        words = shlex.split(normalized)
    except ValueError:
        words = normalized.split()
    return any(word in DESTRUCTIVE_TOKENS for word in words)


def run_remote(
    config: RemoteConfig,
    remote_command: str,
    *,
    runner: CommandRunner = default_runner,
    allow_destructive: bool = False,
) -> int:
    if has_destructive_token(remote_command) and not allow_destructive:
        raise AppleRemoteError("Refusing potentially destructive remote command without --allow-destructive")
    result = runner(ssh_command(config, remote_command))
    stdout = redact_output(result.stdout, config)
    stderr = redact_output(result.stderr, config)
    if stdout:
        print(stdout, end="" if stdout.endswith("\n") else "\n")
    if stderr:
        print(stderr, end="" if stderr.endswith("\n") else "\n", file=sys.stderr)
    print(f"remote={REMOTE_LABEL} exit_code={result.returncode}")
    return result.returncode


def shell_join(parts: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def strip_command_separator(parts: Sequence[str]) -> list[str]:
    if parts and parts[0] == "--":
        return list(parts[1:])
    return list(parts)


def add_app_store_connect_api_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-key-path", help="Remote Mac path to the App Store Connect API .p8 key")
    parser.add_argument("--api-key-id", help="App Store Connect API key ID")
    parser.add_argument("--api-issuer-id", help="App Store Connect API issuer ID")


def add_testflight_notes_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--whats-new",
        help=(
            "Required TestFlight What to Test text to attach to the uploaded build; "
            f"must contain at least {MIN_TESTFLIGHT_WHATS_NEW_LINES} non-empty lines"
        ),
    )
    parser.add_argument(
        "--whats-new-file",
        help=(
            "Required local file containing TestFlight What to Test text; "
            f"must contain at least {MIN_TESTFLIGHT_WHATS_NEW_LINES} non-empty lines"
        ),
    )
    parser.add_argument("--whats-new-locale", default="en-US", help="Locale for TestFlight What to Test text, default: en-US")


def testflight_whats_new_line_count(whats_new: str) -> int:
    return len([line for line in whats_new.splitlines() if line.strip()])


def validate_testflight_whats_new(whats_new: str | None) -> str:
    if not whats_new or not whats_new.strip():
        raise AppleRemoteError("TestFlight uploads require --whats-new or --whats-new-file")
    whats_new = whats_new.strip()
    if testflight_whats_new_line_count(whats_new) < MIN_TESTFLIGHT_WHATS_NEW_LINES:
        raise AppleRemoteError(
            "TestFlight What to Test text must contain at least "
            f"{MIN_TESTFLIGHT_WHATS_NEW_LINES} non-empty lines"
        )
    if len(whats_new) > 4000:
        raise AppleRemoteError("TestFlight What to Test text must be 4000 characters or less")
    return whats_new


def testflight_notes_options(args: argparse.Namespace) -> dict[str, str | None]:
    whats_new = getattr(args, "whats_new", None)
    whats_new_file = getattr(args, "whats_new_file", None)
    if whats_new and whats_new_file:
        raise AppleRemoteError("Pass either --whats-new or --whats-new-file, not both")
    if whats_new_file:
        whats_new = Path(whats_new_file).read_text(encoding="utf-8")
    whats_new = validate_testflight_whats_new(whats_new)
    return {
        "whats_new": whats_new,
        "whats_new_locale": getattr(args, "whats_new_locale", "en-US") or "en-US",
    }


def first_config_value(config: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = config.get(key)
        if value:
            return value
    return None


def app_store_connect_api_options(
    args: argparse.Namespace,
    local_config: dict[str, str],
    *,
    env: dict[str, str] | None = None,
) -> dict[str, str | None]:
    env = env if env is not None else dict(os.environ)
    return {
        "api_key_path": (
            getattr(args, "api_key_path", None)
            or env.get("APP_STORE_CONNECT_API_KEY_PATH")
            or first_config_value(local_config, "app_store_connect_api_key_path", "api_key_path")
        ),
        "api_key_id": (
            getattr(args, "api_key_id", None)
            or env.get("APP_STORE_CONNECT_API_KEY_ID")
            or first_config_value(local_config, "app_store_connect_api_key_id", "api_key_id")
        ),
        "api_issuer_id": (
            getattr(args, "api_issuer_id", None)
            or env.get("APP_STORE_CONNECT_API_ISSUER_ID")
            or first_config_value(local_config, "app_store_connect_api_issuer_id", "api_issuer_id")
        ),
    }


def require_app_store_connect_api_options(options: dict[str, str | None], command_name: str) -> None:
    missing = [
        label
        for label, value in (
            ("api_key_path", options.get("api_key_path")),
            ("api_key_id", options.get("api_key_id")),
            ("api_issuer_id", options.get("api_issuer_id")),
        )
        if not value
    ]
    if missing:
        raise AppleRemoteError(
            f"{command_name} requires App Store Connect API settings: {', '.join(missing)}. "
            "Set app_store_connect_api_key_path, app_store_connect_api_key_id, and "
            "app_store_connect_api_issuer_id in ~/.config/openmates/apple-remote.json, "
            "or pass --api-key-path/--api-key-id/--api-issuer-id."
        )


def encoded_testflight_whats_new(whats_new: str | None) -> str:
    return base64.b64encode(validate_testflight_whats_new(whats_new).encode("utf-8")).decode("ascii")


def repo_command(config: RemoteConfig, parts: Sequence[str]) -> str:
    if not config.repo_path:
        raise AppleRemoteError("Set OPENMATES_APPLE_REPO_PATH or local repo_path for repo commands")
    return f"cd {shlex.quote(config.repo_path)} && {shell_join(parts)}"


def sync_repo_command(branch: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
        raise AppleRemoteError(f"Invalid branch name for sync-repo: {branch}")
    quoted_branch = shlex.quote(branch)
    return " && ".join([
        f"git fetch origin {quoted_branch}",
        "git reset --hard",
        "git clean -fd",
        f"git checkout -B {quoted_branch} origin/{quoted_branch}",
        f"git reset --hard origin/{quoted_branch}",
        "git clean -fd",
        "git status --short",
        "git rev-parse --short HEAD",
    ])


def simulator_locked_command(parts: Sequence[str]) -> str:
    return shell_join(["python3", "-c", SIMULATOR_LOCK_SCRIPT, SIMULATOR_LOCK_PATH, *parts])


def build_ios_command(simulator: str) -> str:
    build_translations = shell_join(["npm", "run", "build:translations"])
    xcodebuild = simulator_locked_command([
        "xcodebuild",
        "-project",
        "apple/OpenMates.xcodeproj",
        "-scheme",
        "OpenMates_iOS",
        "-destination",
        f"platform=iOS Simulator,name={simulator}",
        "build",
    ])
    return f"cd frontend/packages/ui && {build_translations} && cd ../../.. && {xcodebuild}"


def test_ios_command(simulator: str, only_testing: str | None) -> str:
    build_translations = shell_join(["npm", "run", "build:translations"])
    scheme = "OpenMates_iOS"
    if only_testing and only_testing.startswith("OpenMatesUITests/"):
        scheme = "OpenMates_iOS_UI_Tests"
    elif only_testing and only_testing.startswith("OpenMatesTests/"):
        scheme = "OpenMates_iOS_Unit_Tests"
    parts = [
        "xcodebuild",
        "test",
        "-project",
        "apple/OpenMates.xcodeproj",
        "-scheme",
        scheme,
        "-destination",
        f"platform=iOS Simulator,name={simulator}",
    ]
    if only_testing:
        parts.extend(["-only-testing", only_testing])
    return f"cd frontend/packages/ui && {build_translations} && cd ../../.. && {simulator_locked_command(parts)}"


def simulator_cleanup_command(simulator: str) -> str:
    return simulator_locked_command(["xcrun", "simctl", "shutdown", simulator])


def build_macos_command() -> str:
    build_translations = shell_join(["npm", "run", "build:translations"])
    xcodebuild = shell_join([
        "xcodebuild",
        "-project",
        "apple/OpenMates.xcodeproj",
        "-scheme",
        "OpenMates_macOS",
        "-destination",
        "platform=macOS",
        "build",
    ])
    return f"cd frontend/packages/ui && {build_translations} && cd ../../.. && {xcodebuild}"


def test_macos_command(only_testing: str | None) -> str:
    build_translations = shell_join(["npm", "run", "build:translations"])
    parts = [
        "xcodebuild",
        "test",
        "-project",
        "apple/OpenMates.xcodeproj",
        "-scheme",
        "OpenMates_macOS",
        "-destination",
        "platform=macOS",
    ]
    if only_testing:
        parts.extend(["-only-testing", only_testing])
    return f"cd frontend/packages/ui && {build_translations} && cd ../../.. && {shell_join(parts)}"


def build_watch_command(simulator: str) -> str:
    return shell_join([
        "xcodebuild",
        "-project",
        "apple/OpenMates.xcodeproj",
        "-scheme",
        "OpenMatesWatch",
        "-destination",
        f"platform=watchOS Simulator,name={simulator}",
        "build",
    ])


def test_watch_command(simulator: str, only_testing: str | None) -> str:
    parts = [
        "xcodebuild",
        "test",
        "-project",
        "apple/OpenMates.xcodeproj",
        "-scheme",
        "OpenMatesWatch",
        "-destination",
        f"platform=watchOS Simulator,name={simulator}",
    ]
    if only_testing:
        parts.extend(["-only-testing", only_testing])
    return shell_join(parts)


def verify_watch_startup_command(simulator: str, duration: int) -> str:
    if duration < 5 or duration > 300:
        raise AppleRemoteError("verify-watch-startup duration must be between 5 and 300 seconds")
    return shell_join(["python3", "-c", WATCH_STARTUP_SCRIPT, simulator, str(duration)])


def device_status_command() -> str:
    return shell_join(["python3", "-c", DEVICE_STATUS_SCRIPT])


def install_ios_device_command(
    configuration: str,
    allow_provisioning_updates: bool,
    with_associated_domains: bool,
    device_index: int | None = None,
) -> str:
    parts = [
        "python3",
        "-c",
        INSTALL_IOS_DEVICE_SCRIPT,
        configuration,
        "1" if allow_provisioning_updates else "0",
        "1" if with_associated_domains else "0",
    ]
    if device_index is not None:
        parts.append(str(device_index))
    return shell_join(parts)


def app_store_connect_env_prefix(
    command: str,
    *,
    api_key_path: str | None,
    api_key_id: str | None,
    api_issuer_id: str | None,
) -> str:
    env_parts: list[str] = []
    if api_key_path:
        env_parts.append(f"APP_STORE_CONNECT_API_KEY_PATH={shlex.quote(api_key_path)}")
    if api_key_id:
        env_parts.append(f"APP_STORE_CONNECT_API_KEY_ID={shlex.quote(api_key_id)}")
    if api_issuer_id:
        env_parts.append(f"APP_STORE_CONNECT_API_ISSUER_ID={shlex.quote(api_issuer_id)}")
    if not env_parts:
        return command
    return " ".join([*env_parts, command])


def release_archive_preflight_command(platform: str) -> str:
    if platform not in {"ios", "macos", "watchos"}:
        raise AppleRemoteError(f"Unsupported release archive platform: {platform}")
    return shell_join(["python3", "-c", RELEASE_ARCHIVE_PREFLIGHT_SCRIPT, platform])


def release_preflight_then_upload_command(preflight_command: str, upload_command: str) -> str:
    """Require the non-mutating archive check immediately before an upload."""
    return f"{preflight_command} && {upload_command}"


def upload_testflight_ios_command(
    internal_only: bool,
    *,
    api_key_path: str | None = None,
    api_key_id: str | None = None,
    api_issuer_id: str | None = None,
    whats_new: str | None = None,
    whats_new_locale: str = "en-US",
) -> str:
    encoded_whats_new = encoded_testflight_whats_new(whats_new)
    command = shell_join([
        "python3",
        "-c",
        TESTFLIGHT_IOS_SCRIPT,
        "1" if internal_only else "0",
        "ios",
        encoded_whats_new,
        whats_new_locale,
    ])
    upload_command = app_store_connect_env_prefix(
        command,
        api_key_path=api_key_path,
        api_key_id=api_key_id,
        api_issuer_id=api_issuer_id,
    )
    return release_preflight_then_upload_command(release_archive_preflight_command("ios"), upload_command)


def upload_testflight_macos_command(
    internal_only: bool,
    *,
    api_key_path: str | None = None,
    api_key_id: str | None = None,
    api_issuer_id: str | None = None,
    whats_new: str | None = None,
    whats_new_locale: str = "en-US",
) -> str:
    encoded_whats_new = encoded_testflight_whats_new(whats_new)
    command = shell_join([
        "python3",
        "-c",
        TESTFLIGHT_IOS_SCRIPT,
        "1" if internal_only else "0",
        "macos",
        encoded_whats_new,
        whats_new_locale,
    ])
    upload_command = app_store_connect_env_prefix(
        command,
        api_key_path=api_key_path,
        api_key_id=api_key_id,
        api_issuer_id=api_issuer_id,
    )
    return release_preflight_then_upload_command(release_archive_preflight_command("macos"), upload_command)


def upload_testflight_watch_command(
    internal_only: bool,
    *,
    api_key_path: str | None = None,
    api_key_id: str | None = None,
    api_issuer_id: str | None = None,
    whats_new: str | None = None,
    whats_new_locale: str = "en-US",
) -> str:
    encoded_whats_new = encoded_testflight_whats_new(whats_new)
    command = shell_join([
        "python3",
        "-c",
        TESTFLIGHT_IOS_SCRIPT,
        "1" if internal_only else "0",
        "watchos",
        encoded_whats_new,
        whats_new_locale,
    ])
    upload_command = app_store_connect_env_prefix(
        command,
        api_key_path=api_key_path,
        api_key_id=api_key_id,
        api_issuer_id=api_issuer_id,
    )
    return release_preflight_then_upload_command(release_archive_preflight_command("watchos"), upload_command)


def deploy_latest_testflight_command(
    branch: str,
    internal_only: bool,
    *,
    api_key_path: str | None = None,
    api_key_id: str | None = None,
    api_issuer_id: str | None = None,
    whats_new: str | None = None,
    whats_new_locale: str = "en-US",
) -> str:
    builds_command = app_store_builds_command(
        "org.openmates.app",
        limit=50,
        scan_all_builds=True,
        api_key_path=api_key_path,
        api_key_id=api_key_id,
        api_issuer_id=api_issuer_id,
    )
    next_build_command = shell_join(["python3", "-c", NEXT_UNIFIED_BUILD_NUMBER_SCRIPT])
    select_build_number_command = (
        f'OPENMATES_UNIFIED_BUILD_NUMBER="$({builds_command} | {next_build_command})"'
        ' && test -n "$OPENMATES_UNIFIED_BUILD_NUMBER"'
        ' && export OPENMATES_UNIFIED_BUILD_NUMBER'
        ' && printf "unified_build_number=%s\\n" "$OPENMATES_UNIFIED_BUILD_NUMBER"'
    )
    commands = [
        sync_repo_command(branch),
        select_build_number_command,
        upload_testflight_ios_command(
            internal_only,
            api_key_path=api_key_path,
            api_key_id=api_key_id,
            api_issuer_id=api_issuer_id,
            whats_new=whats_new,
            whats_new_locale=whats_new_locale,
        ),
        upload_testflight_macos_command(
            internal_only,
            api_key_path=api_key_path,
            api_key_id=api_key_id,
            api_issuer_id=api_issuer_id,
            whats_new=whats_new,
            whats_new_locale=whats_new_locale,
        ),
    ]
    return " && ".join(commands)


def ensure_ios_distribution_certificate_command(
    create: bool,
    *,
    api_key_path: str | None = None,
    api_key_id: str | None = None,
    api_issuer_id: str | None = None,
    certificate_type: str = "IOS_DISTRIBUTION",
) -> str:
    command = shell_join([
        "python3",
        "-c",
        ENSURE_IOS_DISTRIBUTION_CERTIFICATE_SCRIPT,
        "1" if create else "0",
        certificate_type,
    ])
    return app_store_connect_env_prefix(
        command,
        api_key_path=api_key_path,
        api_key_id=api_key_id,
        api_issuer_id=api_issuer_id,
    )


def revoke_apple_certificate_command(
    sha1: str,
    *,
    api_key_path: str | None = None,
    api_key_id: str | None = None,
    api_issuer_id: str | None = None,
) -> str:
    command = shell_join([
        "python3",
        "-c",
        REVOKE_APPLE_CERTIFICATE_SCRIPT,
        sha1,
    ])
    return app_store_connect_env_prefix(
        command,
        api_key_path=api_key_path,
        api_key_id=api_key_id,
        api_issuer_id=api_issuer_id,
    )


def app_store_builds_command(
    bundle_id: str,
    limit: int = 10,
    require_changelogs: bool = False,
    whats_new_locale: str = "en-US",
    scan_all_builds: bool = False,
    *,
    api_key_path: str | None = None,
    api_key_id: str | None = None,
    api_issuer_id: str | None = None,
) -> str:
    if limit < 1 or limit > 50:
        raise AppleRemoteError("app-store-builds limit must be between 1 and 50")
    command = shell_join([
        "python3",
        "-c",
        APP_STORE_BUILDS_SCRIPT,
        bundle_id,
        str(limit),
        "1" if require_changelogs else "0",
        whats_new_locale,
        "1" if scan_all_builds else "0",
    ])
    return app_store_connect_env_prefix(
        command,
        api_key_path=api_key_path,
        api_key_id=api_key_id,
        api_issuer_id=api_issuer_id,
    )


def testflight_crashes_command(
    bundle_id: str,
    limit: int,
    platform: str | None,
    *,
    api_key_path: str | None = None,
    api_key_id: str | None = None,
    api_issuer_id: str | None = None,
) -> str:
    if limit < 1 or limit > 10:
        raise AppleRemoteError("testflight-crashes limit must be between 1 and 10")
    platform_value = platform or ""
    command = shell_join([
        "python3",
        "-c",
        TESTFLIGHT_CRASHES_SCRIPT,
        bundle_id,
        str(limit),
        platform_value,
    ])
    return app_store_connect_env_prefix(
        command,
        api_key_path=api_key_path,
        api_key_id=api_key_id,
        api_issuer_id=api_issuer_id,
    )


def xcode_cache_report_command() -> str:
    return shell_join(["python3", "-c", XCODE_CACHE_REPORT_SCRIPT])


def xcode_cache_clean_command(targets: Sequence[str]) -> str:
    unknown = sorted(set(targets) - set(XCODE_CACHE_TARGETS))
    if unknown:
        raise AppleRemoteError(f"Unknown Xcode cache target(s): {', '.join(unknown)}")
    return shell_join(["python3", "-c", XCODE_CACHE_CLEAN_SCRIPT, *targets])


def print_status(config: RemoteConfig, *, runner: CommandRunner = default_runner) -> int:
    print(f"remote={REMOTE_LABEL}")
    print(f"source={config.source}")
    print(f"repo_path_configured={bool(config.repo_path)}")
    result = runner(ssh_command(config, "true"))
    print(f"ssh_reachable={result.returncode == 0}")
    return 0 if result.returncode == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run redacted remote Apple development commands")
    parser.add_argument("--allow-destructive", action="store_true", help="Allow explicitly destructive remote commands")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Check redacted SSH reachability")

    run_parser = subparsers.add_parser("run", help="Run a raw remote command")
    run_parser.add_argument("remote_command", nargs=argparse.REMAINDER)

    repo_parser = subparsers.add_parser("repo", help="Run a command in the remote repo checkout")
    repo_parser.add_argument("repo_command", nargs=argparse.REMAINDER)

    sync_parser = subparsers.add_parser("sync-repo", help="Force-sync the remote repo checkout to origin/<branch>")
    sync_parser.add_argument("--branch", default="dev")

    build_parser_ = subparsers.add_parser("build-ios", help="Build OpenMates_iOS remotely")
    build_parser_.add_argument("--simulator", default="iPhone 17")

    test_parser = subparsers.add_parser("test-ios", help="Run OpenMates_iOS tests remotely")
    test_parser.add_argument("--simulator", default="iPhone 17")
    test_parser.add_argument("--only-testing")

    subparsers.add_parser("build-macos", help="Build OpenMates_macOS remotely")

    test_macos_parser = subparsers.add_parser("test-macos", help="Run OpenMates_macOS tests remotely")
    test_macos_parser.add_argument("--only-testing")

    build_watch_parser = subparsers.add_parser("build-watch", help="Build OpenMatesWatch remotely")
    build_watch_parser.add_argument("--simulator", default="Apple Watch Series 11 (46mm)")

    test_watch_parser = subparsers.add_parser("test-watch", help="Run OpenMatesWatch tests remotely")
    test_watch_parser.add_argument("--simulator", default="Apple Watch Series 11 (46mm)")
    test_watch_parser.add_argument("--only-testing")

    verify_watch_parser = subparsers.add_parser(
        "verify-watch-startup",
        help="Build, install, launch, and poll OpenMatesWatch for startup crashes",
    )
    verify_watch_parser.add_argument("--simulator", default="Apple Watch Series 11 (46mm)")
    verify_watch_parser.add_argument("--duration", type=int, default=60)

    device_parser = subparsers.add_parser("device-status", help="Show sanitized physical iOS device readiness")
    device_parser.set_defaults(_uses_repo=True)

    install_parser = subparsers.add_parser("install-ios-device", help="Build and install OpenMates_iOS to a paired iOS/iPadOS device")
    install_parser.add_argument("--configuration", default="Debug", choices=["Debug", "Release"])
    install_parser.add_argument("--device-index", type=int, help="Sanitized index from device-status output")
    install_parser.add_argument("--allow-provisioning-updates", action="store_true")
    install_parser.add_argument(
        "--with-associated-domains",
        action="store_true",
        help="Use passkey/webcredentials Associated Domains entitlements for paid-team builds",
    )

    release_preflight_parser = subparsers.add_parser(
        "release-archive-preflight",
        help="Run a non-uploading Release archive preflight before Apple distribution",
    )
    release_preflight_parser.add_argument("--platform", choices=["ios", "macos", "watchos"], required=True)

    testflight_parser = subparsers.add_parser("upload-testflight-ios", help="Archive and upload OpenMates_iOS to TestFlight")
    testflight_parser.add_argument(
        "--external-capable",
        action="store_true",
        help="Do not mark the uploaded build as internal-testing-only",
    )
    add_testflight_notes_args(testflight_parser)
    add_app_store_connect_api_args(testflight_parser)

    testflight_macos_parser = subparsers.add_parser("upload-testflight-macos", help="Archive and upload OpenMates_macOS to TestFlight")
    testflight_macos_parser.add_argument(
        "--external-capable",
        action="store_true",
        help="Do not mark the uploaded build as internal-testing-only",
    )
    add_testflight_notes_args(testflight_macos_parser)
    add_app_store_connect_api_args(testflight_macos_parser)

    testflight_watch_parser = subparsers.add_parser("upload-testflight-watch", help="Archive and upload OpenMatesWatch to TestFlight")
    testflight_watch_parser.add_argument(
        "--external-capable",
        action="store_true",
        help="Do not mark the uploaded build as internal-testing-only",
    )
    add_testflight_notes_args(testflight_watch_parser)
    add_app_store_connect_api_args(testflight_watch_parser)

    deploy_testflight_parser = subparsers.add_parser(
        "deploy-latest-testflight",
        help="Force-sync the remote checkout and upload latest iOS, watchOS, and macOS builds to TestFlight",
    )
    deploy_testflight_parser.add_argument("--branch", default="dev", help="Remote origin branch to deploy, default: dev")
    deploy_testflight_parser.add_argument(
        "--external-capable",
        action="store_true",
        help="Do not mark uploaded builds as internal-testing-only",
    )
    add_testflight_notes_args(deploy_testflight_parser)
    add_app_store_connect_api_args(deploy_testflight_parser)

    certificate_parser = subparsers.add_parser(
        "ensure-ios-distribution-certificate",
        help="Check or create the local Apple Distribution certificate needed for TestFlight signing",
    )
    certificate_parser.add_argument(
        "--create",
        action="store_true",
        help="Create a durable Apple Developer distribution certificate via App Store Connect API and import it into the Mac keychain",
    )
    add_app_store_connect_api_args(certificate_parser)

    apple_distribution_certificate_parser = subparsers.add_parser(
        "ensure-apple-distribution-certificate",
        help="Check or create a cross-platform Apple Distribution certificate in the build keychain",
    )
    apple_distribution_certificate_parser.add_argument(
        "--create",
        action="store_true",
        help="Create a durable Apple Distribution certificate via App Store Connect API and import it into the Mac build keychain",
    )
    add_app_store_connect_api_args(apple_distribution_certificate_parser)

    mac_installer_certificate_parser = subparsers.add_parser(
        "ensure-mac-installer-distribution-certificate",
        help="Check or create a Mac Installer Distribution certificate in the build keychain",
    )
    mac_installer_certificate_parser.add_argument(
        "--create",
        action="store_true",
        help="Create a durable Mac Installer Distribution certificate via App Store Connect API and import it into the Mac build keychain",
    )
    add_app_store_connect_api_args(mac_installer_certificate_parser)

    development_certificate_parser = subparsers.add_parser(
        "ensure-ios-development-certificate",
        help="Check or create a local Apple Development certificate in the build keychain for SSH archives",
    )
    development_certificate_parser.add_argument(
        "--create",
        action="store_true",
        help="Create a durable Apple Developer development certificate via App Store Connect API and import it into the Mac build keychain",
    )
    add_app_store_connect_api_args(development_certificate_parser)

    revoke_certificate_parser = subparsers.add_parser(
        "revoke-apple-certificate",
        help="Revoke one Apple Developer certificate by SHA-1 fingerprint via App Store Connect API",
    )
    revoke_certificate_parser.add_argument("--sha1", required=True, help="Certificate SHA-1 fingerprint to revoke")
    add_app_store_connect_api_args(revoke_certificate_parser)

    app_store_builds_parser = subparsers.add_parser(
        "app-store-builds",
        help="List recent App Store Connect builds and processing state for a bundle ID",
    )
    app_store_builds_parser.add_argument("--bundle-id", default="org.openmates.app")
    app_store_builds_parser.add_argument("--limit", type=int, default=10, help="Number of recent builds to inspect, 1-50")
    app_store_builds_parser.add_argument(
        "--require-changelogs",
        action="store_true",
        help="Fail if any inspected build lacks TestFlight What to Test text with at least 5 non-empty lines",
    )
    app_store_builds_parser.add_argument("--whats-new-locale", default="en-US", help="Locale to audit, default: en-US")
    add_app_store_connect_api_args(app_store_builds_parser)

    testflight_crashes_parser = subparsers.add_parser(
        "testflight-crashes",
        help="List recent sanitized TestFlight beta crash submissions for a bundle ID",
    )
    testflight_crashes_parser.add_argument("--bundle-id", default="org.openmates.app")
    testflight_crashes_parser.add_argument("--limit", type=int, default=3, help="Number of recent crash submissions to show, 1-10")
    testflight_crashes_parser.add_argument(
        "--platform",
        choices=["IOS", "MAC_OS", "TV_OS", "VISION_OS"],
        help="Optional App Store Connect app platform filter",
    )
    add_app_store_connect_api_args(testflight_crashes_parser)

    simctl_parser = subparsers.add_parser("simctl", help="Run xcrun simctl remotely")
    simctl_parser.add_argument("simctl_args", nargs=argparse.REMAINDER)

    cleanup_parser = subparsers.add_parser("cleanup", help="Shutdown booted simulators after verification")
    cleanup_parser.add_argument("--simulator", default="booted")

    subparsers.add_parser("xcode-cache-report", help="Report sanitized Xcode cache sizes on the Mac")

    cache_clean_parser = subparsers.add_parser("xcode-cache-clean", help="Remove selected Xcode caches on the Mac")
    cache_clean_parser.add_argument("targets", nargs="+", choices=sorted(XCODE_CACHE_TARGETS))

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        local_config = load_local_config()
        config = resolve_remote_config(local_config=local_config)
        api_options = app_store_connect_api_options(args, local_config)
        if args.command == "status":
            return print_status(config)
        if args.command == "run":
            remote_command = strip_command_separator(args.remote_command)
            if not remote_command:
                raise AppleRemoteError("run requires a command after --")
            return run_remote(config, shell_join(remote_command), allow_destructive=args.allow_destructive)
        if args.command == "repo":
            remote_command = strip_command_separator(args.repo_command)
            if not remote_command:
                raise AppleRemoteError("repo requires a command after --")
            return run_remote(config, repo_command(config, remote_command), allow_destructive=args.allow_destructive)
        if args.command == "sync-repo":
            return run_remote(
                config,
                repo_command(config, ["bash", "-lc", sync_repo_command(args.branch)]),
                allow_destructive=True,
            )
        if args.command == "build-ios":
            return run_remote(config, repo_command(config, ["bash", "-lc", build_ios_command(args.simulator)]))
        if args.command == "test-ios":
            return run_remote(config, repo_command(config, ["bash", "-lc", test_ios_command(args.simulator, args.only_testing)]))
        if args.command == "build-macos":
            return run_remote(config, repo_command(config, ["bash", "-lc", build_macos_command()]))
        if args.command == "test-macos":
            return run_remote(config, repo_command(config, ["bash", "-lc", test_macos_command(args.only_testing)]))
        if args.command == "build-watch":
            return run_remote(config, repo_command(config, ["bash", "-lc", build_watch_command(args.simulator)]))
        if args.command == "test-watch":
            return run_remote(config, repo_command(config, ["bash", "-lc", test_watch_command(args.simulator, args.only_testing)]))
        if args.command == "verify-watch-startup":
            return run_remote(config, repo_command(config, ["bash", "-lc", verify_watch_startup_command(args.simulator, args.duration)]))
        if args.command == "device-status":
            return run_remote(config, repo_command(config, ["bash", "-lc", device_status_command()]))
        if args.command == "install-ios-device":
            return run_remote(
                config,
                repo_command(config, [
                    "bash",
                    "-lc",
                    install_ios_device_command(
                        args.configuration,
                        args.allow_provisioning_updates,
                        args.with_associated_domains,
                        args.device_index,
                    ),
                ]),
            )
        if args.command == "release-archive-preflight":
            return run_remote(
                config,
                repo_command(config, ["bash", "-lc", release_archive_preflight_command(args.platform)]),
            )
        if args.command == "upload-testflight-ios":
            notes_options = testflight_notes_options(args)
            require_app_store_connect_api_options(api_options, "upload-testflight-ios --whats-new")
            return run_remote(
                config,
                repo_command(config, [
                    "bash",
                    "-lc",
                    upload_testflight_ios_command(
                        not args.external_capable,
                        **api_options,
                        **notes_options,
                    ),
                ]),
            )
        if args.command == "upload-testflight-macos":
            notes_options = testflight_notes_options(args)
            require_app_store_connect_api_options(api_options, "upload-testflight-macos --whats-new")
            return run_remote(
                config,
                repo_command(config, [
                    "bash",
                    "-lc",
                    upload_testflight_macos_command(
                        not args.external_capable,
                        **api_options,
                        **notes_options,
                    ),
                ]),
            )
        if args.command == "upload-testflight-watch":
            notes_options = testflight_notes_options(args)
            require_app_store_connect_api_options(api_options, "upload-testflight-watch --whats-new")
            return run_remote(
                config,
                repo_command(config, [
                    "bash",
                    "-lc",
                    upload_testflight_watch_command(
                        not args.external_capable,
                        **api_options,
                        **notes_options,
                    ),
                ]),
            )
        if args.command == "deploy-latest-testflight":
            notes_options = testflight_notes_options(args)
            require_app_store_connect_api_options(api_options, "deploy-latest-testflight --whats-new")
            return run_remote(
                config,
                repo_command(config, [
                    "bash",
                    "-lc",
                    deploy_latest_testflight_command(
                        args.branch,
                        not args.external_capable,
                        **api_options,
                        **notes_options,
                    ),
                ]),
                allow_destructive=True,
            )
        if args.command == "ensure-ios-distribution-certificate":
            return run_remote(
                config,
                repo_command(config, [
                    "bash",
                    "-lc",
                    ensure_ios_distribution_certificate_command(
                        args.create,
                        **api_options,
                    ),
                ]),
            )
        if args.command == "ensure-ios-development-certificate":
            return run_remote(
                config,
                repo_command(config, [
                    "bash",
                    "-lc",
                    ensure_ios_distribution_certificate_command(
                        args.create,
                        **api_options,
                        certificate_type="DEVELOPMENT",
                    ),
                ]),
            )
        if args.command == "ensure-apple-distribution-certificate":
            return run_remote(
                config,
                repo_command(config, [
                    "bash",
                    "-lc",
                    ensure_ios_distribution_certificate_command(
                        args.create,
                        **api_options,
                        certificate_type="DISTRIBUTION",
                    ),
                ]),
            )
        if args.command == "ensure-mac-installer-distribution-certificate":
            return run_remote(
                config,
                repo_command(config, [
                    "bash",
                    "-lc",
                    ensure_ios_distribution_certificate_command(
                        args.create,
                        **api_options,
                        certificate_type="MAC_INSTALLER_DISTRIBUTION",
                    ),
                ]),
            )
        if args.command == "revoke-apple-certificate":
            return run_remote(
                config,
                repo_command(config, [
                    "bash",
                    "-lc",
                    revoke_apple_certificate_command(
                        args.sha1,
                        **api_options,
                    ),
                ]),
            )
        if args.command == "app-store-builds":
            if args.require_changelogs:
                require_app_store_connect_api_options(api_options, "app-store-builds --require-changelogs")
            return run_remote(
                config,
                repo_command(config, [
                    "bash",
                    "-lc",
                    app_store_builds_command(
                        args.bundle_id,
                        args.limit,
                        args.require_changelogs,
                        args.whats_new_locale,
                        **api_options,
                    ),
                ]),
            )
        if args.command == "testflight-crashes":
            require_app_store_connect_api_options(api_options, "testflight-crashes")
            return run_remote(
                config,
                repo_command(config, [
                    "bash",
                    "-lc",
                    testflight_crashes_command(
                        args.bundle_id,
                        args.limit,
                        args.platform,
                        **api_options,
                    ),
                ]),
            )
        if args.command == "simctl":
            simctl_args = strip_command_separator(args.simctl_args)
            if not simctl_args:
                raise AppleRemoteError("simctl requires arguments after --")
            return run_remote(config, shell_join(["xcrun", "simctl", *simctl_args]), allow_destructive=args.allow_destructive)
        if args.command == "cleanup":
            return run_remote(
                config,
                simulator_cleanup_command(args.simulator),
                allow_destructive=True,
            )
        if args.command == "xcode-cache-report":
            return run_remote(config, shell_join(["bash", "-lc", xcode_cache_report_command()]))
        if args.command == "xcode-cache-clean":
            if not args.allow_destructive:
                raise AppleRemoteError("xcode-cache-clean requires --allow-destructive")
            return run_remote(
                config,
                shell_join(["bash", "-lc", xcode_cache_clean_command(args.targets)]),
                allow_destructive=True,
            )
        raise AppleRemoteError(f"Unsupported command: {args.command}")
    except AppleRemoteError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
