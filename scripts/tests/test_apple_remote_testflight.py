#!/usr/bin/env python3
"""Tests for deterministic Apple remote TestFlight deployment commands.

These tests keep the SSH/App Store Connect workflow from regressing into a
late Xcode archive failure. The remote Mac must not need a logged-in Xcode
account when App Store Connect API credentials and generated profiles are the
intended source of truth.
"""

from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "apple_remote.py"


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


def test_deploy_latest_testflight_syncs_then_uploads_both_platforms() -> None:
    apple_remote = load_apple_remote()

    command = apple_remote.deploy_latest_testflight_command(
        "dev",
        True,
        "both",
        api_key_path="/private/key.p8",
        api_key_id="KEY123",
        api_issuer_id="ISSUER123",
    )

    assert command.index("git fetch origin dev") < command.index("APP_STORE_CONNECT_API_KEY_PATH=/private/key.p8")
    assert command.count("python3 -c") == 2
    assert "APP_STORE_CONNECT_API_KEY_ID=KEY123" in command
    assert "APP_STORE_CONNECT_API_ISSUER_ID=ISSUER123" in command
    assert "macos" in command


def test_deploy_latest_testflight_rejects_unknown_platform() -> None:
    apple_remote = load_apple_remote()

    with pytest.raises(apple_remote.AppleRemoteError):
        apple_remote.deploy_latest_testflight_command("dev", True, "watchos")


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
