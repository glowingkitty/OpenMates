#!/usr/bin/env python3
"""Tests for deterministic Apple remote TestFlight deployment commands.

These tests keep the SSH/App Store Connect workflow from regressing into a
late Xcode archive failure. The remote Mac must not need a logged-in Xcode
account when App Store Connect API credentials and generated profiles are the
intended source of truth.
"""

from __future__ import annotations

import base64
import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "apple_remote.py"
APPLE_PROJECT_YAML = ROOT / "apple" / "project.yml"
WATCH_INFO_PLIST = ROOT / "apple" / "OpenMatesWatch" / "Info.plist"
XCODE_PROJECT_FILE = ROOT / "apple" / "OpenMates.xcodeproj" / "project.pbxproj"


def load_apple_remote():
    spec = importlib.util.spec_from_file_location("apple_remote", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["apple_remote"] = module
    spec.loader.exec_module(module)
    return module


def test_testflight_profiles_are_prepared_before_archive() -> None:
    apple_remote = load_apple_remote()
    script = apple_remote.TESTFLIGHT_IOS_SCRIPT

    archive_index = script.index('print("archive_status=started")')
    assert script.index("if has_app_store_connect_api_auth():") < archive_index
    assert script.index("create_or_download_app_store_profiles()") < archive_index
    assert script.index("load_installed_app_store_profiles()") < archive_index
    assert 'archive_without_signing = False' in script


def test_ios_archive_entitlements_are_checked_before_upload() -> None:
    apple_remote = load_apple_remote()
    script = apple_remote.TESTFLIGHT_IOS_SCRIPT

    assert script.index("assert_ios_archive_passkey_entitlements()") < script.index('print("upload_status=started")')
    assert "webcredentials:openmates.org" in script
    assert "com.apple.developer.associated-domains" in script
    assert "APP_GROUP_IDENTIFIER" in script


def test_created_profiles_use_decoded_installed_uuid_for_export() -> None:
    apple_remote = load_apple_remote()
    script = apple_remote.TESTFLIGHT_IOS_SCRIPT

    assert "profile_data = decoded_profile(profile_path)" in script
    assert "installed_uuid = profile_data.get(\"UUID\") if profile_data else None" in script
    assert "profile_names[identifier] = installed_uuid or profile_uuid" in script


def test_deploy_latest_testflight_syncs_then_uploads_ios_and_macos() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.deploy_latest_testflight_command(
        "dev",
        True,
        whats_new="Release notes",
        api_key_path="/private/key.p8",
        api_key_id="KEY123",
        api_issuer_id="ISSUER123",
    )

    assert command.index("git fetch origin dev") < command.index("APP_STORE_CONNECT_API_KEY_PATH=/private/key.p8")
    assert command.count("python3 -c") == 2
    assert "APP_STORE_CONNECT_API_KEY_ID=KEY123" in command
    assert "APP_STORE_CONNECT_API_ISSUER_ID=ISSUER123" in command
    assert " watchos " not in command
    assert "macos" in command


def test_upload_testflight_ios_can_attach_whats_new_text() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.upload_testflight_ios_command(
        True,
        whats_new="Fixed login and sync.",
        whats_new_locale="en-US",
    )
    encoded = base64.b64encode(b"Fixed login and sync.").decode("ascii")
    script = apple_remote.TESTFLIGHT_IOS_SCRIPT

    assert encoded in command
    assert "en-US" in command
    assert "upsert_testflight_whats_new()" in script
    assert "betaBuildLocalizations" in script
    assert "whats_new_previous_build=" in script
    assert script.index('print("upload_status=passed")') < script.rindex("upsert_testflight_whats_new()")


def test_deploy_latest_testflight_passes_whats_new_to_upload_commands() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.deploy_latest_testflight_command("dev", True, whats_new="Release notes")
    encoded = base64.b64encode(b"Release notes").decode("ascii")

    assert command.count(encoded) == 2
    assert "whats_new_status=skipped_watchos" in apple_remote.TESTFLIGHT_IOS_SCRIPT


def test_ios_testflight_archive_requires_embedded_watch_companion() -> None:
    apple_remote = load_apple_remote()
    script = apple_remote.TESTFLIGHT_IOS_SCRIPT

    assert '"org.openmates.app.watch",' in script
    assert 'REQUIRED_APP_GROUP_BUNDLE_IDS = set(BUNDLE_IDS) - {"org.openmates.app.watch"}' in script
    assert '"provisioningProfiles": profile_names' in script
    assert "assert_ios_archive_embeds_watch_companion()" in script
    assert "archive_watch_companion=missing" in script
    assert "WKCompanionAppBundleIdentifier" in script
    assert "WKRunsIndependentlyOfCompanionApp" in script
    assert script.index("assert_ios_archive_embeds_watch_companion()") < script.index('print("upload_status=started")')


def test_watch_distribution_is_embedded_companion_not_separate_upload() -> None:
    project_yaml = APPLE_PROJECT_YAML.read_text(encoding="utf-8")
    watch_info = WATCH_INFO_PLIST.read_text(encoding="utf-8")
    xcode_project = XCODE_PROJECT_FILE.read_text(encoding="utf-8")

    assert "- target: OpenMatesWatch" in project_yaml
    assert "platforms: [iOS]" in project_yaml
    assert "embed: true" in project_yaml
    assert "WKCompanionAppBundleIdentifier" in project_yaml
    assert "WKRunsIndependentlyOfCompanionApp" in project_yaml
    assert "PRODUCT_NAME: OpenMatesWatch" in project_yaml
    assert "SKIP_INSTALL: YES" in project_yaml
    assert "CFBundlePackageType: APPL" in project_yaml
    assert "CFBundleIconName: WatchAppIcon" in project_yaml
    assert "ASSETCATALOG_COMPILER_APPICON_NAME: WatchAppIcon" in project_yaml
    assert "OpenMatesWatch/Assets.xcassets" in project_yaml
    assert "type: application" in project_yaml
    assert "WKWatchOnly" not in watch_info
    assert "WKCompanionAppBundleIdentifier" in watch_info
    assert "WKRunsIndependentlyOfCompanionApp" in watch_info
    assert "CFBundlePackageType" in watch_info
    assert "CFBundleIconName" in watch_info
    assert "OpenMatesWatch.app in Embed Watch Content" in xcode_project
    assert 'dstPath = "$(CONTENTS_FOLDER_PATH)/Watch";' in xcode_project
    assert "C0FFEE000000000000047018 /* OpenMatesWatch */" in xcode_project
    assert "PRODUCT_NAME = OpenMatesWatch;" in xcode_project
    assert "SKIP_INSTALL = YES;" in xcode_project
    assert "ASSETCATALOG_COMPILER_APPICON_NAME = WatchAppIcon;" in xcode_project
    assert "C0FFEE000000000000049025 /* Assets.xcassets in Resources */" in xcode_project
    assert "productType = \"com.apple.product-type.application\";" in xcode_project


def test_testflight_notes_options_rejects_duplicate_sources() -> None:
    apple_remote = load_apple_remote()

    with pytest.raises(apple_remote.AppleRemoteError, match="either --whats-new or --whats-new-file"):
        apple_remote.testflight_notes_options(
            Namespace(whats_new="Inline", whats_new_file="notes.txt", whats_new_locale="en-US")
        )


def test_testflight_notes_options_requires_changelog() -> None:
    apple_remote = load_apple_remote()

    with pytest.raises(apple_remote.AppleRemoteError, match="require --whats-new or --whats-new-file"):
        apple_remote.testflight_notes_options(
            Namespace(whats_new=None, whats_new_file=None, whats_new_locale="en-US")
        )


def test_upload_testflight_command_requires_changelog() -> None:
    apple_remote = load_apple_remote()

    with pytest.raises(apple_remote.AppleRemoteError, match="require --whats-new or --whats-new-file"):
        apple_remote.upload_testflight_ios_command(True)


def test_upload_testflight_watch_uses_watch_scheme_and_profile_contract() -> None:
    apple_remote = load_apple_remote()
    command = apple_remote.upload_testflight_watch_command(True, whats_new="Release notes")
    script = apple_remote.TESTFLIGHT_IOS_SCRIPT

    assert "watchos" in command
    assert 'scheme_name = "OpenMatesWatch"' in script
    assert 'archive_destination = "generic/platform=watchOS"' in script
    assert '"org.openmates.app.watch"' in script
    assert "REQUIRED_KEYCHAIN_GROUP_BUNDLE_IDS = set(BUNDLE_IDS)" not in script
    assert 'enable_bundle_capability(bundle_id, "KEYCHAIN_SHARING")' not in script
    assert 'if target_platform == "watchos":' in script
    assert "PROVISIONING_PROFILE_SPECIFIER={watch_profile}" in script
    assert "CODE_SIGN_STYLE=Manual" in script
    assert '"destination": "export" if target_platform == "watchos" else "upload"' in script
    assert '"method": "release-testing" if target_platform == "watchos" else "app-store-connect"' in script
    assert '"--upload-package"' in script
    assert '"--p8-file-path"' in script


def test_deploy_latest_testflight_parser_has_no_platform_override() -> None:
    apple_remote = load_apple_remote()

    parser = apple_remote.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["deploy-latest-testflight", "--platform", "ios"])


def test_app_store_connect_options_resolve_from_config() -> None:
    apple_remote = load_apple_remote()

    options = apple_remote.app_store_connect_api_options(
        Namespace(api_key_path=None, api_key_id=None, api_issuer_id=None),
        {
            "app_store_connect_api_key_path": "/remote/AuthKey.p8",
            "app_store_connect_api_key_id": "CONFIGKEY",
            "app_store_connect_api_issuer_id": "CONFIGISSUER",
        },
        env={},
    )

    assert options == {
        "api_key_path": "/remote/AuthKey.p8",
        "api_key_id": "CONFIGKEY",
        "api_issuer_id": "CONFIGISSUER",
    }


def test_deploy_latest_requires_complete_app_store_connect_options() -> None:
    apple_remote = load_apple_remote()

    with pytest.raises(apple_remote.AppleRemoteError, match="deploy-latest-testflight requires App Store Connect API settings"):
        apple_remote.require_app_store_connect_api_options(
            {"api_key_path": None, "api_key_id": "KEY", "api_issuer_id": "ISSUER"},
            "deploy-latest-testflight",
        )
