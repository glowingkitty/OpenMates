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
for index, device in enumerate(wired, 1):
    properties = device.get("deviceProperties", {})
    connection = device.get("connectionProperties", {})
    print(f"wired_{index}_pairing={connection.get('pairingState', 'unknown')}")
    print(f"wired_{index}_developer_mode={properties.get('developerModeStatus', 'unknown')}")
    print(f"wired_{index}_os={properties.get('osVersionNumber', properties.get('osVersion', 'unknown'))}")
sys.exit(0 if wired else 3)
'''


INSTALL_IOS_DEVICE_SCRIPT = r'''
import json
import os
import plistlib
import pathlib
import subprocess
import sys
import tempfile

configuration = sys.argv[1]
allow_provisioning_updates = sys.argv[2] == "1"
with_associated_domains = sys.argv[3] == "1"


def print_tail(label, text, device_id, app_path=None, limit=160):
    print(f"{label}=failed")
    sanitized = text.replace(device_id, "<device-id>")
    if app_path:
        sanitized = sanitized.replace(app_path, "<app-bundle>")
    for line in sanitized.splitlines()[-limit:]:
        print(line)


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
wired = [d for d in devices if d.get("connectionProperties", {}).get("transportType") == "wired"]
if not wired:
    print("install_status=no_wired_device")
    sys.exit(3)

device_id = wired[0].get("identifier")
if not device_id:
    print("install_status=no_device_identifier")
    sys.exit(4)

derived = tempfile.mkdtemp(prefix="openmates-device-build-")
entitlements_override = None
if with_associated_domains:
    entitlements_override = pathlib.Path("apple/OpenMates/Resources/OpenMatesPasskey.entitlements")
    print("associated_domains=enabled_for_passkey_build")
else:
    source_entitlements = pathlib.Path("apple/OpenMates/Resources/OpenMates.entitlements")
    entitlements_override = pathlib.Path(derived) / "OpenMatesWithoutAssociatedDomains.entitlements"
    with source_entitlements.open("rb") as handle:
        entitlements = plistlib.load(handle)
    entitlements.pop("com.apple.developer.associated-domains", None)
    with entitlements_override.open("wb") as handle:
        plistlib.dump(entitlements, handle)
    print("associated_domains=disabled_for_default_device_build")

build_cmd = [
    "xcodebuild",
    "-project",
    "apple/OpenMates.xcodeproj",
    "-scheme",
    "OpenMates_iOS",
    "-configuration",
    configuration,
    "-destination",
    f"id={device_id}",
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
    print_tail("build_status", build.stdout + build.stderr, device_id)
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


def repo_command(config: RemoteConfig, parts: Sequence[str]) -> str:
    if not config.repo_path:
        raise AppleRemoteError("Set OPENMATES_APPLE_REPO_PATH or local repo_path for repo commands")
    return f"cd {shlex.quote(config.repo_path)} && {shell_join(parts)}"


def build_ios_command(simulator: str) -> str:
    return shell_join([
        "xcodebuild",
        "-project",
        "apple/OpenMates.xcodeproj",
        "-scheme",
        "OpenMates_iOS",
        "-destination",
        f"platform=iOS Simulator,name={simulator}",
        "build",
    ])


def test_ios_command(simulator: str, only_testing: str | None) -> str:
    parts = [
        "xcodebuild",
        "test",
        "-project",
        "apple/OpenMates.xcodeproj",
        "-scheme",
        "OpenMates_iOS",
        "-destination",
        f"platform=iOS Simulator,name={simulator}",
    ]
    if only_testing:
        parts.extend(["-only-testing", only_testing])
    return shell_join(parts)


def device_status_command() -> str:
    return shell_join(["python3", "-c", DEVICE_STATUS_SCRIPT])


def install_ios_device_command(
    configuration: str,
    allow_provisioning_updates: bool,
    with_associated_domains: bool,
) -> str:
    return shell_join([
        "python3",
        "-c",
        INSTALL_IOS_DEVICE_SCRIPT,
        configuration,
        "1" if allow_provisioning_updates else "0",
        "1" if with_associated_domains else "0",
    ])


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

    build_parser_ = subparsers.add_parser("build-ios", help="Build OpenMates_iOS remotely")
    build_parser_.add_argument("--simulator", default="iPhone 17")

    test_parser = subparsers.add_parser("test-ios", help="Run OpenMates_iOS tests remotely")
    test_parser.add_argument("--simulator", default="iPhone 17")
    test_parser.add_argument("--only-testing")

    device_parser = subparsers.add_parser("device-status", help="Show sanitized physical iOS device readiness")
    device_parser.set_defaults(_uses_repo=True)

    install_parser = subparsers.add_parser("install-ios-device", help="Build and install OpenMates_iOS to a wired iPhone")
    install_parser.add_argument("--configuration", default="Debug", choices=["Debug", "Release"])
    install_parser.add_argument("--allow-provisioning-updates", action="store_true")
    install_parser.add_argument(
        "--with-associated-domains",
        action="store_true",
        help="Use passkey/webcredentials Associated Domains entitlements for paid-team builds",
    )

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
        config = resolve_remote_config()
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
        if args.command == "build-ios":
            return run_remote(config, repo_command(config, ["bash", "-lc", build_ios_command(args.simulator)]))
        if args.command == "test-ios":
            return run_remote(config, repo_command(config, ["bash", "-lc", test_ios_command(args.simulator, args.only_testing)]))
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
                shell_join(["xcrun", "simctl", "shutdown", args.simulator]),
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
