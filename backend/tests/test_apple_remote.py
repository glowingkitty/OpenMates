"""Tests for the redacted Apple remote command wrapper.

The wrapper is a local automation guardrail for Tailscale/SSH access to a trusted
Mac. These tests avoid network access by injecting fake command runners and focus
on safety contracts: deterministic macOS peer discovery, redacted output, and
destructive command refusal.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
APPLE_REMOTE_PATH = REPO_ROOT / "scripts" / "apple_remote.py"
spec = importlib.util.spec_from_file_location("apple_remote", APPLE_REMOTE_PATH)
assert spec and spec.loader
apple_remote = importlib.util.module_from_spec(spec)
sys.modules["apple_remote"] = apple_remote
spec.loader.exec_module(apple_remote)


def completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_discovers_single_online_macos_peer_ip() -> None:
    status = {
        "Peer": {
            "linux": {"Online": True, "OS": "linux", "TailscaleIPs": ["linux-tailnet-ip"]},
            "mac": {"Online": True, "OS": "macOS", "TailscaleIPs": ["macos-tailnet-ip"]},
            "offline_mac": {"Online": False, "OS": "macOS", "TailscaleIPs": ["offline-macos-tailnet-ip"]},
        }
    }

    def runner(_: list[str]) -> subprocess.CompletedProcess[str]:
        return completed(stdout=apple_remote.json.dumps(status))

    assert apple_remote.discover_macos_tailscale_ip(runner=runner) == "macos-tailnet-ip"


def test_resolve_requires_user_for_auto_discovered_ip() -> None:
    try:
        apple_remote.resolve_remote_config(env={}, local_config={}, runner=lambda _: completed(stdout="{}"))
    except apple_remote.AppleRemoteError as exc:
        assert "OPENMATES_APPLE_SSH_USER" in str(exc)
    else:
        raise AssertionError("Expected AppleRemoteError")


def test_redacts_target_and_repo_path_from_output() -> None:
    config = apple_remote.RemoteConfig(
        target="operator@macos-peer.example.invalid",
        repo_path="/tmp/openmates-remote-checkout",
        source="test",
    )
    text = "operator@macos-peer.example.invalid /tmp/openmates-remote-checkout build ok"

    redacted = apple_remote.redact_output(text, config)

    assert "operator" not in redacted
    assert "macos-peer.example.invalid" not in redacted
    assert "/tmp/openmates-remote-checkout" not in redacted
    assert redacted.count("<macos-peer>") == 2


def test_redacts_generic_macos_home_paths() -> None:
    config = apple_remote.RemoteConfig(target="operator@macos-peer.example.invalid", repo_path=None, source="test")
    mac_home_path = "/" + "Users/example/Library/Developer/Xcode/DerivedData/OpenMates"

    redacted = apple_remote.redact_output(f"build path: {mac_home_path}", config)

    assert mac_home_path not in redacted
    assert "<macos-peer-path>" in redacted


def test_refuses_destructive_remote_command_without_flag() -> None:
    config = apple_remote.RemoteConfig(target="operator@macos-peer.example.invalid", repo_path=None, source="test")

    try:
        apple_remote.run_remote(config, "rm -rf /tmp/example", runner=lambda _: completed())
    except apple_remote.AppleRemoteError as exc:
        assert "destructive" in str(exc)
    else:
        raise AssertionError("Expected AppleRemoteError")


def test_destructive_guard_does_not_match_substrings() -> None:
    assert not apple_remote.has_destructive_token("xcodebuild -destination 'platform=iOS Simulator,name=iPhone 17' build")


def test_repo_command_quotes_repo_path() -> None:
    config = apple_remote.RemoteConfig(target="operator@macos-peer.example.invalid", repo_path="/tmp/Open Mates", source="test")

    command = apple_remote.repo_command(config, ["git", "status", "--short"])

    assert command == "cd '/tmp/Open Mates' && git status --short"


def test_strips_optional_command_separator() -> None:
    assert apple_remote.strip_command_separator(["--", "git", "status"]) == ["git", "status"]
    assert apple_remote.strip_command_separator(["git", "status"]) == ["git", "status"]


def test_cleanup_allows_simulator_shutdown_command() -> None:
    config = apple_remote.RemoteConfig(target="operator@macos-peer.example.invalid", repo_path=None, source="test")
    commands: list[list[str]] = []

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return completed()

    exit_code = apple_remote.run_remote(
        config,
        apple_remote.shell_join(["xcrun", "simctl", "shutdown", "booted"]),
        runner=runner,
        allow_destructive=True,
    )

    assert exit_code == 0
    assert commands[0][-1] == "xcrun simctl shutdown booted"
