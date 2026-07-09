"""Tests for the redacted Apple remote command wrapper.

The wrapper is a local automation guardrail for Tailscale/SSH access to a trusted
Mac. These tests avoid network access by injecting fake command runners and focus
on safety contracts: deterministic macOS peer discovery, redacted output, and
destructive command refusal.
"""

from __future__ import annotations

import base64
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

VALID_WHATS_NEW = "\n".join([
    "Improves login reliability for beta users.",
    "Adds safer diagnostics for Apple builds.",
    "Fixes sync state reporting during startup.",
    "Updates TestFlight deployment guardrails.",
    "Documents verification evidence for releases.",
])


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


def test_redacts_macos_temporary_build_paths() -> None:
    config = apple_remote.RemoteConfig(target="operator@macos-peer.example.invalid", repo_path=None, source="test")
    temp_path = "/var/folders/aa/bb/T/openmates-device-build-example/Build/Products/OpenMates.app"

    redacted = apple_remote.redact_output(f"build path: {temp_path}", config)

    assert temp_path not in redacted
    assert "<macos-peer-tmp>" in redacted


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


def test_sync_repo_command_force_syncs_to_origin_branch() -> None:
    command = apple_remote.sync_repo_command("dev")

    assert "git fetch origin dev" in command
    assert "git reset --hard origin/dev" in command
    assert "git clean -fd" in command
    assert command.endswith("git rev-parse --short HEAD")


def test_sync_repo_command_rejects_shell_metacharacters() -> None:
    try:
        apple_remote.sync_repo_command("dev;rm-rf")
    except apple_remote.AppleRemoteError as exc:
        assert "Invalid branch" in str(exc)
    else:
        raise AssertionError("Expected AppleRemoteError")


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


def test_install_ios_device_command_uses_configuration_and_provisioning_flag() -> None:
    command = apple_remote.install_ios_device_command(
        "Debug",
        allow_provisioning_updates=True,
        with_associated_domains=False,
    )

    assert "OpenMates_iOS" in command
    assert "Debug" in command
    assert "generic/platform=iOS" in command
    assert "com.apple.developer.associated-domains" not in command
    assert "associated_domains=project_default" in command
    assert " 1" in command
    assert command.endswith(" Debug 1 0")


def test_install_ios_device_script_imports_redaction_dependencies() -> None:
    script = apple_remote.INSTALL_IOS_DEVICE_SCRIPT

    assert "import re" in script
    assert "re.sub" in script


def test_install_ios_device_command_can_enable_associated_domains_for_passkeys() -> None:
    command = apple_remote.install_ios_device_command(
        "Debug",
        allow_provisioning_updates=True,
        with_associated_domains=True,
    )

    assert "OpenMatesPasskey.entitlements" in command
    assert "associated_domains=enabled_for_passkey_build" in command
    assert command.endswith(" Debug 1 1")


def test_upload_testflight_ios_command_uses_app_store_connect_upload() -> None:
    command = apple_remote.upload_testflight_ios_command(internal_only=True, whats_new=VALID_WHATS_NEW)
    encoded = base64.b64encode(VALID_WHATS_NEW.encode("utf-8")).decode("ascii")

    assert "OpenMates_iOS" in command
    assert "app-store-connect" in command
    assert "Z9B2YFKN2X" in command
    assert "destination" in command
    assert "upload" in command
    assert "testFlightInternalTestingOnly" in command
    assert encoded in command
    assert command.endswith(f"1 ios {encoded} en-US")


def test_upload_testflight_ios_command_can_allow_external_testing() -> None:
    command = apple_remote.upload_testflight_ios_command(internal_only=False, whats_new=VALID_WHATS_NEW)
    encoded = base64.b64encode(VALID_WHATS_NEW.encode("utf-8")).decode("ascii")

    assert "testFlightInternalTestingOnly" in command
    assert command.endswith(f"0 ios {encoded} en-US")


def test_upload_testflight_ios_command_can_inject_api_key_args() -> None:
    command = apple_remote.upload_testflight_ios_command(
        internal_only=True,
        api_key_path="~/AuthKey_TEST.p8",
        api_key_id="KEYID",
        api_issuer_id="ISSUERID",
        whats_new=VALID_WHATS_NEW,
    )

    assert "APP_STORE_CONNECT_API_KEY_PATH='~/AuthKey_TEST.p8'" in command
    assert "APP_STORE_CONNECT_API_KEY_ID=KEYID" in command
    assert "APP_STORE_CONNECT_API_ISSUER_ID=ISSUERID" in command


def test_upload_testflight_macos_command_uses_mac_app_store_export() -> None:
    command = apple_remote.upload_testflight_macos_command(internal_only=True, whats_new=VALID_WHATS_NEW)
    encoded = base64.b64encode(VALID_WHATS_NEW.encode("utf-8")).decode("ascii")
    script = apple_remote.TESTFLIGHT_IOS_SCRIPT

    assert "OpenMates_macOS" in script
    assert "generic/platform=macOS" in script
    assert "MAC_APP_STORE" in script
    assert "DISTRIBUTION" in script
    assert "installerSigningCertificate" in script
    assert "distribution_identity_sha1 if target_platform == \"macos\"" in script
    assert "archive_entitlements_stamp=passed" in script
    assert "OpenMatesPasskey.entitlements" in script
    assert "bundle_id_create=passed" in script
    assert '"platform": bundle_id_platform' in script
    assert "CODE_SIGNING_ALLOWED=NO" in script
    assert "provisionprofile" in script
    assert "org.openmates.app.sharemacos" in script
    assert "profile_app_group=missing" in script
    assert "assign_app_group_to_bundle_id_in_apple_developer_portal" in script
    assert "app-store-connect" in command
    assert command.endswith(f"1 macos {encoded} en-US")


def test_upload_testflight_ios_script_preflights_signing() -> None:
    script = apple_remote.TESTFLIGHT_IOS_SCRIPT

    assert "preflight_signing" in script
    assert "distribution_identity=missing" in script
    assert "iPhone Distribution:" in script
    assert "probe_identity = distribution_identity_name or development_identity" in script
    assert "openmates-codesign-preflight" in script
    assert "CODE_SIGN_IDENTITY=iPhone Distribution" not in script
    assert "DEVELOPMENT_TEAM=Z9B2YFKN2X" in script
    assert "use_build_keychain_if_present" in script
    assert "*keychain_args" in script
    assert "OTHER_CODE_SIGN_FLAGS=--keychain" in script
    assert "clean_openmates_provisioning_profiles" in script
    assert script.index("create_or_download_app_store_profiles()") < script.rindex("plistlib.dump(export_options")
    assert "UserData" in script
    assert "org.openmates.app" in script
    assert "openmates-build.keychain-db" in script


def test_upload_testflight_script_validates_profile_app_groups_before_export() -> None:
    script = apple_remote.TESTFLIGHT_IOS_SCRIPT

    assert "APP_GROUP_IDENTIFIER = \"group.org.openmates.app.shared\"" in script
    assert "assert_profile_supports_required_entitlements(identifier, profile_path)" in script
    assert script.index("assert_profile_supports_required_entitlements(identifier, profile_path)") < script.index(
        "plistlib.dump(export_options"
    )


def test_ensure_ios_distribution_certificate_command_checks_by_default() -> None:
    command = apple_remote.ensure_ios_distribution_certificate_command(create=False)

    assert "ENSURE_IOS_DISTRIBUTION_CERTIFICATE_SCRIPT" not in command
    assert command.endswith(" 0 IOS_DISTRIBUTION")


def test_ensure_ios_distribution_certificate_command_can_create() -> None:
    command = apple_remote.ensure_ios_distribution_certificate_command(
        create=True,
        api_key_path="~/AuthKey_TEST.p8",
        api_key_id="KEYID",
        api_issuer_id="ISSUERID",
    )

    assert "IOS_DISTRIBUTION" in command
    assert "APP_STORE_CONNECT_API_KEY_PATH" in command
    assert "APP_STORE_CONNECT_API_KEY_ID=KEYID" in command
    assert command.endswith(" 1 IOS_DISTRIBUTION")


def test_ensure_ios_development_certificate_command_can_create() -> None:
    command = apple_remote.ensure_ios_distribution_certificate_command(
        create=True,
        api_key_path="~/AuthKey_TEST.p8",
        api_key_id="KEYID",
        api_issuer_id="ISSUERID",
        certificate_type="IOS_DEVELOPMENT",
    )

    assert "IOS_DEVELOPMENT" in command
    assert "APP_STORE_CONNECT_API_KEY_ID=KEYID" in command
    assert command.endswith(" 1 IOS_DEVELOPMENT")


def test_ensure_ios_development_certificate_command_uses_modern_development_type() -> None:
    parser = apple_remote.build_parser()
    args = parser.parse_args(["ensure-ios-development-certificate", "--create"])

    command = apple_remote.ensure_ios_distribution_certificate_command(
        args.create,
        certificate_type="DEVELOPMENT",
    )

    assert command.endswith(" 1 DEVELOPMENT")


def test_ensure_apple_distribution_certificate_command_uses_modern_distribution_type() -> None:
    command = apple_remote.ensure_ios_distribution_certificate_command(
        True,
        certificate_type="DISTRIBUTION",
    )

    assert command.endswith(" 1 DISTRIBUTION")


def test_ensure_mac_installer_distribution_certificate_command_uses_installer_type() -> None:
    command = apple_remote.ensure_ios_distribution_certificate_command(
        True,
        certificate_type="MAC_INSTALLER_DISTRIBUTION",
    )
    parser = apple_remote.build_parser()

    args = parser.parse_args(["ensure-mac-installer-distribution-certificate", "--create"])

    assert command.endswith(" 1 MAC_INSTALLER_DISTRIBUTION")
    assert args.create is True


def test_ensure_ios_distribution_certificate_script_uses_certificate_api() -> None:
    script = apple_remote.ENSURE_IOS_DISTRIBUTION_CERTIFICATE_SCRIPT

    assert "https://api.appstoreconnect.apple.com/v1/certificates" in script
    assert "certificateType" in script
    assert "IOS_DISTRIBUTION" in script
    assert "DISTRIBUTION" in script
    assert "MAC_INSTALLER_DISTRIBUTION" in script
    assert "3rd Party Mac Developer Installer" in script
    assert "/usr/bin/productbuild" in script
    assert "IOS_DEVELOPMENT" in script
    assert "DEVELOPMENT" in script
    assert "iPhone Distribution:" in script
    assert "Apple Development:" in script
    assert "iPhone Developer:" in script
    assert "der_ecdsa_to_raw_jws_signature" in script
    assert "build_keychain" in script
    assert "existing_build_keychain_args" in script
    assert "openmates-build.keychain-db" in script
    assert "apple-build-keychain-password" in script
    assert "set-key-partition-list" in script
    assert "security" in script
    assert "import" in script
    assert script.index("private_key_import") < script.index("response = create_certificate")


def test_revoke_apple_certificate_command_targets_sha1() -> None:
    command = apple_remote.revoke_apple_certificate_command(
        "F9AB",
        api_key_path="~/AuthKey_TEST.p8",
        api_key_id="KEYID",
        api_issuer_id="ISSUERID",
    )

    assert "F9AB" in command
    assert "APP_STORE_CONNECT_API_KEY_ID=KEYID" in command
    assert "DELETE" in command


def test_revoke_apple_certificate_script_matches_fingerprint() -> None:
    script = apple_remote.REVOKE_APPLE_CERTIFICATE_SCRIPT

    assert "hashlib.sha1" in script
    assert "/v1/certificates" in script
    assert "certificate_revoked" in script
    assert "list_only" in script


def test_app_store_builds_command_queries_builds_for_bundle_id() -> None:
    command = apple_remote.app_store_builds_command(
        "org.openmates.app",
        api_key_path="~/AuthKey_TEST.p8",
        api_key_id="KEYID",
        api_issuer_id="ISSUERID",
    )

    assert "APP_STORE_CONNECT_API_KEY_ID=KEYID" in command
    assert "org.openmates.app" in command
    assert "preReleaseVersion" in command
    assert "processingState" in command


def test_app_store_builds_command_can_audit_testflight_changelogs() -> None:
    command = apple_remote.app_store_builds_command(
        "org.openmates.app",
        limit=3,
        require_changelogs=True,
        whats_new_locale="en-US",
        api_key_path="~/AuthKey_TEST.p8",
        api_key_id="KEYID",
        api_issuer_id="ISSUERID",
    )
    script = apple_remote.APP_STORE_BUILDS_SCRIPT

    assert command.endswith(" org.openmates.app 3 1 en-US")
    assert "betaBuildLocalizations" in script
    assert "MIN_TESTFLIGHT_WHATS_NEW_LINES = 5" in script
    assert "changelog_status=failed" in script
    assert "changelog_status=passed" in script


def test_app_store_builds_command_rejects_invalid_limit() -> None:
    try:
        apple_remote.app_store_builds_command("org.openmates.app", limit=0)
    except apple_remote.AppleRemoteError as exc:
        assert "between 1 and 50" in str(exc)
    else:
        raise AssertionError("Expected AppleRemoteError")


def test_install_ios_device_script_reports_paid_team_hint() -> None:
    script = apple_remote.INSTALL_IOS_DEVICE_SCRIPT

    assert "paid_team_not_selected_in_xcode" in script
    assert "personal development teams" in script


def test_xcode_cache_clean_rejects_unknown_target() -> None:
    try:
        apple_remote.xcode_cache_clean_command(["derived-data", "unknown-cache"])
    except apple_remote.AppleRemoteError as exc:
        assert "unknown-cache" in str(exc)
    else:
        raise AssertionError("Expected AppleRemoteError")


def test_xcode_cache_clean_command_allows_known_targets() -> None:
    command = apple_remote.xcode_cache_clean_command(["derived-data", "swiftpm-cache", "device-support"])

    assert "derived-data" in command
    assert "swiftpm-cache" in command
    assert "device-support" in command


def test_device_status_command_uses_devicectl() -> None:
    command = apple_remote.device_status_command()

    assert "devicectl" in command
    assert "wired_devices" in command
