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

    setup_call = "\npreflight_signing()\nclean_openmates_provisioning_profiles()\nsync_bundle_capabilities()\ncreate_or_download_app_store_profiles()\n"
    assert script.index(setup_call) < script.index('print("archive_status=started")')
    assert 'archive_without_signing = True' in script


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
