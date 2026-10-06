# contract-test-file: tooling
"""Focused tests for the resumable all-platform TestFlight entrypoint."""

from __future__ import annotations

import importlib.util
import json
import os
import plistlib
import sys
import struct
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "apple_testflight_release.py"


def load_module():
    scripts = str(SCRIPT.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("apple_testflight_release", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_plist(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        plistlib.dump(value, handle)


def make_archive(root: Path, platform: str, version: str = "0.21.0", build: int = 74) -> Path:
    archive = root / ("OpenMates-iOS.xcarchive" if platform == "ios" else "OpenMates-macOS.xcarchive")
    architectures = ["arm64"] if platform == "ios" else ["x86_64", "arm64"]
    write_plist(archive / "Info.plist", {"ApplicationProperties": {
        "CFBundleIdentifier": "org.openmates.app",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": str(build),
        "Architectures": architectures,
    }})
    app = archive / "Products" / "Applications" / "OpenMates.app"
    app_info = app / ("Info.plist" if platform == "ios" else "Contents/Info.plist")
    write_plist(app_info, {
        "CFBundleIdentifier": "org.openmates.app",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": str(build),
    })
    executable = app / ("OpenMates" if platform == "ios" else "Contents/MacOS/OpenMates")
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"app-binary")
    if platform == "ios":
        watch = app / "Watch" / "OpenMatesWatch.app"
        write_plist(watch / "Info.plist", {
            "CFBundleIdentifier": "org.openmates.app.watch",
            "WKCompanionAppBundleIdentifier": "org.openmates.app",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": str(build),
            "CFBundleExecutable": "OpenMatesWatch",
        })
        (watch / "OpenMatesWatch").write_bytes(b"watch-binary")
    else:
        for name, suffix in [("OpenMatesShareExtension_macOS", "sharemacos"), ("OpenMatesWidget_macOS", "widgetmacos")]:
            write_plist(app / f"Contents/PlugIns/{name}.appex/Contents/Info.plist", {
                "CFBundleIdentifier": f"org.openmates.app.{suffix}",
            })
    return archive


def extension_entitlements(bundle: Path) -> dict:
    if bundle.name == "OpenMatesWidget_macOS.appex":
        return {
            "com.apple.security.app-sandbox": True,
            "com.apple.security.network.client": True,
            "com.apple.security.application-groups": ["group.org.openmates.app.shared"],
            "keychain-access-groups": ["TEAMID.org.openmates.app.widgetmacos", "TEAMID.org.openmates.app"],
        }
    return {"com.apple.security.app-sandbox": True}


def test_archive_validation_requires_watch_and_universal_macos(tmp_path: Path) -> None:
    release = load_module()
    ios = make_archive(tmp_path, "ios")
    macos = make_archive(tmp_path, "macos")

    assert release.validate_archive(ios, "ios", "0.21.0", 74)["tree_sha256"]
    assert release.validate_archive(macos, "macos", "0.21.0", 74)["tree_sha256"]

    (ios / "Products/Applications/OpenMates.app/Watch/OpenMatesWatch.app/Info.plist").unlink()
    with pytest.raises(release.ReleaseError, match="Invalid or missing plist|identity files"):
        release.validate_archive(ios, "ios", "0.21.0", 74)

    info_path = macos / "Info.plist"
    info = release.load_plist(info_path)
    info["ApplicationProperties"]["Architectures"] = ["arm64"]
    write_plist(info_path, info)
    with pytest.raises(release.ReleaseError, match="macOS archive architectures"):
        release.validate_archive(macos, "macos", "0.21.0", 74)


def test_receipt_only_resumes_matching_fingerprint(tmp_path: Path) -> None:
    release = load_module()
    release.write_receipt(tmp_path, "archive-ios", "one", {"archive_identity": {"a": 1}})

    assert release.read_receipt(tmp_path, "archive-ios", "one")["status"] == "complete"
    assert release.read_receipt(tmp_path, "archive-ios", "two") is None


@pytest.mark.parametrize("use_credentials", [False, True])
def test_commands_pin_one_build_and_do_not_delete_simulators(tmp_path: Path, use_credentials: bool) -> None:
    release = load_module()
    credentials = release.Credentials(Path("/private/AuthKey.p8"), "KEY", "ISSUER") if use_credentials else None

    ios = release.archive_command("ios", tmp_path, 74, "TEAM", credentials)
    macos = release.archive_command("macos", tmp_path, 74, "TEAM", credentials)
    all_text = " ".join([*ios, *macos])

    assert all_text.count("CURRENT_PROJECT_VERSION=74") == 2
    assert "OpenMates_iOS" in ios
    assert "OpenMates_macOS" in macos
    assert "ENABLE_USER_SCRIPT_SANDBOXING=NO" in ios
    assert "ENABLE_USER_SCRIPT_SANDBOXING=NO" in macos
    assert "ARCHS=arm64 x86_64" in macos
    for command in (ios, macos):
        assert command.count("-jobs") == 1
        assert command[command.index("-jobs") + 1] == "1"
        assert command.count("SWIFT_USE_PARALLEL_WHOLE_MODULE_OPTIMIZATION=NO") == 1
        assert command.count("SWIFT_USE_PARALLEL_WMO_TARGETS=NO") == 1
        assert command.count("OTHER_SWIFT_FLAGS=$(inherited) -j1 -num-threads 1") == 1
    assert "simctl" not in all_text
    assert "delete" not in all_text
    assert "VERCEL" not in SCRIPT.read_text(encoding="utf-8")


def test_commands_support_signed_in_xcode_without_api_credentials(tmp_path: Path) -> None:
    release = load_module()

    archive = release.archive_command("ios", tmp_path, 74, "TEAM", None)
    export = release.export_command("ios", tmp_path, tmp_path / "ExportOptions.plist", None)

    assert "-allowProvisioningUpdates" in archive
    assert "-authenticationKeyPath" not in archive
    assert "-authenticationKeyPath" not in export


def test_release_unlocks_existing_build_keychain_before_archiving(tmp_path: Path, monkeypatch) -> None:
    release = load_module()
    password_path = tmp_path / ".config/openmates/apple-build-keychain-password"
    password_path.parent.mkdir(parents=True)
    password_path.write_text("local-secret", encoding="utf-8")
    keychain = tmp_path / "Library/Keychains/openmates-build.keychain-db"
    keychain.parent.mkdir(parents=True)
    keychain.touch()
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        return release.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(release.subprocess, "run", run)
    assert release.prepare_build_keychain(tmp_path)
    assert [command[1] for command in commands] == [
        "unlock-keychain", "set-keychain-settings", "set-key-partition-list"
    ]
    assert commands[-1][-1] == str(keychain)


def test_release_without_local_build_keychain_uses_default_signing(tmp_path: Path) -> None:
    release = load_module()
    assert release.prepare_build_keychain(tmp_path) is False


def test_archive_distribution_is_a_resumable_upload_receipt(tmp_path: Path) -> None:
    release = load_module()
    archive = make_archive(tmp_path, "ios")
    info_path = archive / "Info.plist"
    info = release.load_plist(info_path)
    info["Distributions"] = [{
        "uploadedBuildNumber": "74",
        "uploadEvent": {"state": "success"},
    }]
    write_plist(info_path, info)

    assert release.archive_reports_successful_upload(archive, 74)
    assert not release.archive_reports_successful_upload(archive, 75)


def test_stale_archive_is_preserved_instead_of_deleted(tmp_path: Path) -> None:
    release = load_module()
    release_dir = tmp_path / "testflight-build-74"
    archive = make_archive(release_dir, "ios")

    preserved = release.preserve_stale_archive(archive, release_dir, "ios")

    assert preserved.exists()
    assert not archive.exists()
    assert preserved.parent == release_dir / "stale"


def test_release_lock_prevents_concurrent_uploads(tmp_path: Path) -> None:
    release = load_module()
    first = release.acquire_release_lock(tmp_path)
    try:
        with pytest.raises(release.ReleaseError, match="holds the release lock"):
            release.acquire_release_lock(tmp_path)
    finally:
        first.close()


def test_macos_stamping_signs_both_extensions_before_parent_with_own_entitlements(tmp_path: Path, monkeypatch) -> None:
    release = load_module()
    calls = []
    monkeypatch.setattr(release, "run_logged", lambda command, log_path, timeout: calls.append(command))
    archive = make_archive(tmp_path, "macos")
    extension_info = archive / "Products/Applications/OpenMates.app/Contents/PlugIns/OpenMatesShareExtension_macOS.appex/Contents/Info.plist"
    write_plist(extension_info, {"CFBundleIdentifier": "org.openmates.app.sharemacos"})

    release.stamp_unsigned_macos_archive(archive, tmp_path / "stamp.log", "TEAMID")

    assert "OpenMatesShareExtension_macOS.appex" in calls[0][-1]
    assert calls[1][-1].endswith("OpenMatesWidget_macOS.appex")
    assert calls[2][-1].endswith("OpenMates.app")
    assert all("--entitlements" in command for command in calls)
    assert all("--deep" not in command for command in calls)
    with Path(calls[2][-2]).open("rb") as handle:
        app_entitlements = plistlib.load(handle)
    with Path(calls[1][-2]).open("rb") as handle:
        widget_entitlements = plistlib.load(handle)
    with Path(calls[0][-2]).open("rb") as handle:
        share_entitlements = plistlib.load(handle)
    assert app_entitlements["com.apple.developer.aps-environment"] == "production"
    assert "aps-environment" not in app_entitlements
    assert app_entitlements["com.apple.security.files.user-selected.read-only"] is True
    assert app_entitlements["com.apple.security.device.audio-input"] is True
    assert app_entitlements["keychain-access-groups"] == ["TEAMID.org.openmates.app"] * 2
    assert "$(OPENMATES_DEV_WEBCREDENTIALS)" not in app_entitlements["com.apple.developer.associated-domains"]
    assert "webcredentials:app.dev.openmates.org" in app_entitlements["com.apple.developer.associated-domains"]
    assert {"applinks:openmates.org", "applinks:app.openmates.org", "applinks:app.dev.openmates.org"}.issubset(
        app_entitlements["com.apple.developer.associated-domains"]
    )
    assert share_entitlements["keychain-access-groups"] == [
        "TEAMID.org.openmates.app.sharemacos", "TEAMID.org.openmates.app"
    ]
    assert widget_entitlements == extension_entitlements(Path("OpenMatesWidget_macOS.appex"))
    project = (SCRIPT.parent.parent / "apple/project.yml").read_text()
    widget_target = project.split("  OpenMatesWidget_macOS:\n", 1)[1].split("\n  OpenMatesUITests:", 1)[0]
    assert "PRODUCT_BUNDLE_IDENTIFIER: org.openmates.app.widgetmacos" in widget_target
    assert "CODE_SIGN_ENTITLEMENTS: OpenMatesWidget/MacWidget.entitlements" in widget_target


@pytest.mark.parametrize("has_framework", [False, True])
def test_macos_stamping_signs_only_archive_onnx_copy_before_parent(
    tmp_path: Path, monkeypatch, has_framework: bool,
) -> None:
    release = load_module()
    archive = make_archive(tmp_path, "macos")
    app = archive / "Products/Applications/OpenMates.app"
    framework = app / "Contents/Frameworks/onnxruntime.framework"
    source = tmp_path / "SwiftPM/onnxruntime.framework/onnxruntime"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source-framework")
    if has_framework:
        framework.mkdir(parents=True)
        (framework / "onnxruntime").write_bytes(source.read_bytes())
    calls = []
    monkeypatch.setattr(release, "run_logged", lambda command, log_path, timeout: calls.append(command))

    release.stamp_unsigned_macos_archive(archive, tmp_path / "stamp.log", "TEAMID")

    expected = [str(app / "Contents/PlugIns/OpenMatesShareExtension_macOS.appex"),
                str(app / "Contents/PlugIns/OpenMatesWidget_macOS.appex")]
    if has_framework:
        expected.append(str(framework))
    expected.append(str(app))
    assert [command[-1] for command in calls] == expected
    if has_framework:
        assert calls[-2] == ["codesign", "--force", "--sign", "-", "--timestamp=none", str(framework)]
    assert all("--deep" not in command for command in calls)
    assert source.read_bytes() == b"source-framework"


def test_macos_stamping_onnx_signing_failure_stops_before_parent(tmp_path: Path, monkeypatch) -> None:
    release = load_module()
    archive = make_archive(tmp_path, "macos")
    app = archive / "Products/Applications/OpenMates.app"
    framework = app / "Contents/Frameworks/onnxruntime.framework"
    framework.mkdir(parents=True)
    calls = []

    def run(command, log_path, timeout):
        calls.append(command)
        if command[-1] == str(framework):
            raise release.ReleaseError("synthetic ONNX signing failure")

    monkeypatch.setattr(release, "run_logged", run)
    with pytest.raises(release.ReleaseError, match="synthetic ONNX signing failure"):
        release.stamp_unsigned_macos_archive(archive, tmp_path / "stamp.log", "TEAMID")
    assert calls[-1][-1] == str(framework)
    assert not any(command[-1] == str(app) for command in calls)


@pytest.mark.parametrize("bundle_path", [
    "Contents", "Contents/PlugIns/OpenMatesShareExtension_macOS.appex/Contents",
    "Contents/PlugIns/OpenMatesWidget_macOS.appex/Contents",
])
def test_macos_stamping_rejects_wrong_bundle_identity_before_any_signing(tmp_path: Path, monkeypatch, bundle_path: str) -> None:
    release = load_module()
    archive = make_archive(tmp_path, "macos")
    info = archive / "Products/Applications/OpenMates.app" / bundle_path / "Info.plist"
    write_plist(info, {"CFBundleIdentifier": "org.unrelated.app"})
    calls = []
    monkeypatch.setattr(release, "run_logged", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(release.ReleaseError, match="bundle identifiers do not match"):
        release.stamp_unsigned_macos_archive(archive, tmp_path / "stamp.log", "TEAMID")
    assert calls == []


def test_macos_stamping_rejects_missing_widget_before_any_signing(tmp_path: Path, monkeypatch) -> None:
    release = load_module()
    archive = make_archive(tmp_path, "macos")
    (archive / "Products/Applications/OpenMates.app/Contents/PlugIns/OpenMatesWidget_macOS.appex/Contents/Info.plist").unlink()
    calls = []
    monkeypatch.setattr(release, "run_logged", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(release.ReleaseError, match="Invalid or missing plist"):
        release.stamp_unsigned_macos_archive(archive, tmp_path / "stamp.log", "TEAMID")
    assert calls == []


@pytest.mark.parametrize("failed_index", [0, 1])
def test_macos_stamping_nested_failure_stops_before_parent(tmp_path: Path, monkeypatch, failed_index: int) -> None:
    release = load_module()
    archive = make_archive(tmp_path, "macos")
    calls = []

    def run(command, log_path, timeout):
        calls.append(command)
        if len(calls) - 1 == failed_index:
            raise release.ReleaseError("synthetic nested signing failure")

    monkeypatch.setattr(release, "run_logged", run)
    with pytest.raises(release.ReleaseError, match="synthetic nested signing failure"):
        release.stamp_unsigned_macos_archive(archive, tmp_path / "stamp.log", "TEAMID")
    assert len(calls) == failed_index + 1
    assert not any(command[-1].endswith("OpenMates.app") for command in calls)


@pytest.mark.parametrize("key,value,error", [
    ("com.apple.security.app-sandbox", False, "app-sandbox"),
    ("com.apple.security.network.client", None, "network.client"),
    ("com.apple.security.application-groups", [], "shared app-group"),
    ("com.apple.security.application-groups", "group.org.openmates.app.shared", "shared app-group"),
    ("keychain-access-groups", [], "keychain"),
    ("keychain-access-groups", ["TEAMID.org.openmates.app.sharemacos", "TEAMID.org.openmates.app"], "keychain"),
    ("keychain-access-groups", ["TEAMID.org.openmates.app.widgetmacos", "FOREIGN.org.openmates.app"], "keychain"),
])
@pytest.mark.parametrize("resumed", [False, True])
def test_macos_widget_entitlements_are_required_for_new_and_resumed_archives(
    tmp_path: Path, monkeypatch, key: str, value: object, error: str, resumed: bool,
) -> None:
    release = load_module()
    archive = make_archive(tmp_path, "macos")
    widget = extension_entitlements(Path("OpenMatesWidget_macOS.appex"))
    widget[key] = value
    app = release.resolved_macos_entitlements(
        SCRIPT.parent.parent / "apple/OpenMates/Resources/OpenMatesMacOS.entitlements", "TEAMID", "org.openmates.app")
    monkeypatch.setattr(release, "signed_entitlements", lambda bundle: (
        app if bundle.name == "OpenMates.app" else widget if bundle.name == "OpenMatesWidget_macOS.appex"
        else extension_entitlements(bundle)))
    identity = {"tree_sha256": "unchanged"}
    monkeypatch.setattr(release, "validate_archive", lambda *args: identity)
    with pytest.raises(release.ReleaseError, match=error):
        if resumed:
            release.validate_resumed_archive(archive, "macos", "0.27.0", 91, {"archive_identity": identity})
        else:
            release.validate_release_entitlements(archive, "macos")


def test_macos_archive_rejects_missing_or_unresolved_apns_entitlement(tmp_path: Path, monkeypatch) -> None:
    release = load_module()
    archive = make_archive(tmp_path, "macos")

    def signed_entitlements(bundle: Path) -> dict:
        if bundle.name == "OpenMates.app":
            return {
                "com.apple.security.app-sandbox": True,
                "com.apple.security.files.user-selected.read-only": True,
                "com.apple.security.device.audio-input": True,
                "com.apple.developer.aps-environment": environment,
                "com.apple.developer.associated-domains": [
                    "webcredentials:app.dev.openmates.org",
                    "applinks:openmates.org", "applinks:app.openmates.org", "applinks:app.dev.openmates.org",
                ],
            }
        return extension_entitlements(bundle)

    monkeypatch.setattr(release, "signed_entitlements", signed_entitlements)
    for environment in (None, "$(APS_ENVIRONMENT)", "development"):
        with pytest.raises(release.ReleaseError, match="concrete production APNs entitlement"):
            release.validate_release_entitlements(archive, "macos")
    environment = "production"
    release.validate_release_entitlements(archive, "macos")


def test_macos_archive_rejects_missing_dev_passkey_domain(tmp_path: Path, monkeypatch) -> None:
    release = load_module()
    archive = make_archive(tmp_path, "macos")

    def signed_entitlements(bundle: Path) -> dict:
        if bundle.name == "OpenMates.app":
            return {
                "com.apple.security.app-sandbox": True,
                "com.apple.security.files.user-selected.read-only": True,
                "com.apple.security.device.audio-input": True,
                "com.apple.developer.aps-environment": "production",
                "com.apple.developer.associated-domains": ["webcredentials:openmates.org"],
            }
        return extension_entitlements(bundle)

    monkeypatch.setattr(release, "signed_entitlements", signed_entitlements)
    with pytest.raises(release.ReleaseError, match="dev passkey associated domain"):
        release.validate_release_entitlements(archive, "macos")


def test_resumed_macos_archive_rejects_missing_dev_passkey_domain(tmp_path: Path, monkeypatch) -> None:
    release = load_module()
    archive = make_archive(tmp_path, "macos")
    identity = {"tree_sha256": "unchanged"}
    monkeypatch.setattr(release, "validate_archive", lambda *args: identity)

    def signed_entitlements(bundle: Path) -> dict:
        if bundle.name == "OpenMates.app":
            return {
                "com.apple.security.app-sandbox": True,
                "com.apple.security.files.user-selected.read-only": True,
                "com.apple.security.device.audio-input": True,
                "com.apple.developer.aps-environment": "production",
                "com.apple.developer.associated-domains": ["webcredentials:openmates.org"],
            }
        return extension_entitlements(bundle)

    monkeypatch.setattr(release, "signed_entitlements", signed_entitlements)
    with pytest.raises(release.ReleaseError, match="dev passkey associated domain"):
        release.validate_resumed_archive(
            archive, "macos", "0.23.0", 84, {"archive_identity": identity},
        )


@pytest.mark.parametrize("platform", ["ios", "macos"])
def test_archive_rejects_missing_shared_link_domains(tmp_path: Path, monkeypatch, platform: str) -> None:
    release = load_module()
    archive = make_archive(tmp_path, platform)
    associated = ["webcredentials:openmates.org", "webcredentials:app.dev.openmates.org"]

    def signed_entitlements(bundle: Path) -> dict:
        if bundle.name == "OpenMates.app":
            return {
                "com.apple.security.app-sandbox": True,
                "com.apple.security.files.user-selected.read-only": True,
                "com.apple.security.device.audio-input": True,
                "com.apple.developer.aps-environment": "production",
                "com.apple.security.application-groups": ["group.org.openmates.app.shared"],
                "com.apple.developer.associated-domains": associated,
            }
        return extension_entitlements(bundle)

    monkeypatch.setattr(release, "signed_entitlements", signed_entitlements)
    with pytest.raises(release.ReleaseError, match="shared-link associated domains"):
        release.validate_release_entitlements(archive, platform)
    associated.extend(["applinks:openmates.org", "applinks:app.openmates.org", "applinks:app.dev.openmates.org"])
    release.validate_release_entitlements(archive, platform)


def test_universal_links_claim_only_short_shares_and_workflow_recipients() -> None:
    root = SCRIPT.parent.parent
    association = json.loads((root / "frontend/apps/web_app/static/.well-known/apple-app-site-association").read_text())
    assert association["webcredentials"]["apps"] == ["Z9B2YFKN2X.org.openmates.app"]
    detail = association["applinks"]["details"][0]
    assert detail["appIDs"] == ["Z9B2YFKN2X.org.openmates.app"]
    assert {component["/"] for component in detail["components"]} == {
        "/s", "/s/*", "/share/workflow-template/*",
    }
    for name in ["OpenMatesPasskey.entitlements", "OpenMatesMacOS.entitlements"]:
        source = root / "apple/OpenMates/Resources" / name
        with source.open("rb") as handle:
            entitlements = plistlib.load(handle)
        assert {"applinks:openmates.org", "applinks:app.openmates.org", "applinks:app.dev.openmates.org"}.issubset(
            entitlements["com.apple.developer.associated-domains"]
        )


def test_platform_processing_requires_both_platform_records() -> None:
    release = load_module()
    records = [
        release.BuildRecord("ios-id", "0.21.0", 74, "VALID", "IOS"),
        release.BuildRecord("mac-id", "0.21.0", 74, "PROCESSING", "MAC_OS"),
    ]

    assert release.platform_record(records, "0.21.0", 74, "ios").processing_state == "VALID"
    assert release.platform_record(records, "0.21.0", 74, "macos").processing_state == "PROCESSING"
    assert release.platform_record(records, "0.21.0", 75, "ios") is None


def test_existing_app_store_build_requires_matching_source_bound_receipt() -> None:
    release = load_module()
    existing = release.BuildRecord("build-id", "0.21.0", 74, "VALID", "IOS")

    with pytest.raises(release.ReleaseError, match="no upload receipt"):
        release.prove_existing_upload(existing, None, "ios")
    with pytest.raises(release.ReleaseError, match="does not match"):
        release.prove_existing_upload(existing, {"build_id": "other-id"}, "ios")
    with pytest.raises(release.ReleaseError, match="no matching build ID"):
        release.prove_existing_upload(existing, {"build_id": None}, "ios")
    assert release.prove_existing_upload(existing, {"build_id": "build-id"}, "ios")["build_id"] == "build-id"


def test_xcarchive_upload_provenance_can_be_bound_to_app_store_build_id(tmp_path: Path) -> None:
    release = load_module()
    archive = make_archive(tmp_path, "ios")
    info_path = archive / "Info.plist"
    info = release.load_plist(info_path)
    info["Distributions"] = [{"uploadedBuildNumber": "74", "uploadEvent": {"state": "success"}}]
    write_plist(info_path, info)
    identity = release.validate_archive(archive, "ios", "0.21.0", 74)
    receipt = {
        "build_id": None,
        "upload_provenance": "xcarchive_distribution",
        "archive_tree_sha256": identity["tree_sha256"],
    }
    existing = release.BuildRecord("asc-id", "0.21.0", 74, "VALID", "IOS")

    details = release.prove_existing_upload(
        existing, receipt, "ios", archive_path=archive, archive_identity_value=identity,
    )

    assert details["build_id"] == "asc-id"
    with pytest.raises(release.ReleaseError, match="no matching build ID"):
        release.prove_existing_upload(
            existing, {**receipt, "archive_tree_sha256": "wrong"}, "ios",
            archive_path=archive, archive_identity_value=identity,
        )


def test_source_enumeration_includes_ignored_generated_and_canonical_inputs(tmp_path: Path, monkeypatch) -> None:
    release = load_module()
    canonical = tmp_path / "canonical" / "messages.yml"
    generated = tmp_path / "generated" / "en.json"
    canonical.parent.mkdir()
    generated.parent.mkdir()
    canonical.write_text("hello: Hello\n", encoding="utf-8")
    generated.write_text('{"hello":"Hello"}\n', encoding="utf-8")
    (tmp_path / ".gitignore").write_text("generated/\n", encoding="utf-8")
    monkeypatch.setattr(release, "SOURCE_INPUTS", ("canonical", "generated"))
    monkeypatch.setattr(release, "project_external_inputs", lambda repo_root: [])

    assert release.source_files(tmp_path) == [canonical, generated]


def test_project_external_resources_are_derived_and_invalidate_source_identity(tmp_path: Path, monkeypatch) -> None:
    release = load_module()
    project = tmp_path / "apple" / "project.yml"
    project.parent.mkdir()
    project.write_text(
        """
targets:
  OpenMates:
    sources:
      - path: ../frontend/packages/ui/static/images/mates
      - path: ../frontend/packages/ui/src/demo_chats/data/example_chats
      - path: ../shared/future-bundled-resources
""".strip() + "\n",
        encoding="utf-8",
    )
    mates = tmp_path / "frontend/packages/ui/static/images/mates/avatar.jpg"
    examples = tmp_path / "frontend/packages/ui/src/demo_chats/data/example_chats/example.json"
    future = tmp_path / "shared/future-bundled-resources/payload.dat"
    for path, content in ((mates, b"avatar"), (examples, b"example"), (future, b"future")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    monkeypatch.setattr(release, "SOURCE_INPUTS", ("apple/project.yml",))

    derived = release.project_external_inputs(tmp_path)
    before = release.source_content_identity(tmp_path)
    mates.write_bytes(b"changed-avatar")
    after_mates = release.source_content_identity(tmp_path)
    examples.write_bytes(b"changed-example")
    after_examples = release.source_content_identity(tmp_path)
    future.write_bytes(b"changed-future")
    after_future = release.source_content_identity(tmp_path)

    assert "frontend/packages/ui/static/images/mates" in derived
    assert "frontend/packages/ui/src/demo_chats/data/example_chats" in derived
    assert "shared/future-bundled-resources" in derived
    assert before["content_sha256"] != after_mates["content_sha256"]
    assert after_mates["content_sha256"] != after_examples["content_sha256"]
    assert after_examples["content_sha256"] != after_future["content_sha256"]


def test_generation_runs_before_archiving_and_propagates_failure(tmp_path: Path, monkeypatch) -> None:
    release = load_module()
    commands = []
    monkeypatch.setattr(release, "run_logged", lambda command, log_path, timeout: commands.append((command, log_path)))

    release.generate_release_inputs(tmp_path)

    assert [command[-1] for command, _ in commands] == ["build:translations", "build:tokens"]
    assert [path.name for _, path in commands] == ["generate-translations.log", "generate-tokens.log"]

    def fail_generation(command, log_path, timeout):
        raise release.ReleaseError("generation failed")

    monkeypatch.setattr(release, "run_logged", fail_generation)
    with pytest.raises(release.ReleaseError, match="generation failed"):
        release.generate_release_inputs(tmp_path)


def test_generation_preserves_only_identical_existing_known_apple_output_mtimes(tmp_path: Path, monkeypatch) -> None:
    release = load_module()
    monkeypatch.setattr(release, "REPO_ROOT", tmp_path)
    swift = tmp_path / "frontend/packages/ui/src/tokens/generated/swift"
    locales = tmp_path / "frontend/packages/ui/src/i18n/locales"
    swift.mkdir(parents=True)
    locales.mkdir(parents=True)
    identical = [swift / "ColorTokens.generated.swift", locales / "en.json"]
    changed = swift / "SpacingTokens.generated.swift"
    deleted = swift / "GradientTokens.generated.swift"
    replaced = swift / "Tokens.generated.swift"
    new = swift / "IconMapping.generated.swift"
    unrelated = swift / "authored.swift"
    before, after = 1_700_000_000_000_000_000, 1_700_000_001_000_000_000
    for output in [*identical, changed, deleted, replaced, unrelated]:
        output.write_bytes(b"original")
        os.utime(output, ns=(before, before))

    def generate(command, log_path, timeout):
        paths = [locales / "en.json"] if command[-1] == "build:translations" else [identical[0], changed, unrelated]
        for output in paths:
            output.write_bytes(b"changed" if output == changed else b"original")
            os.utime(output, ns=(after, after))
        if command[-1] == "build:tokens":
            deleted.unlink()
            replacement = swift / "replacement.tmp"
            replacement.write_bytes(b"original")
            os.utime(replacement, ns=(after, after))
            replacement.replace(replaced)
            new.write_bytes(b"new")
            os.utime(new, ns=(after, after))

    monkeypatch.setattr(release, "run_logged", generate)
    release.generate_release_inputs(tmp_path)
    assert all(output.stat().st_mtime_ns == before for output in identical)
    assert changed.read_bytes() == b"changed"
    assert not deleted.exists()
    assert all(output.stat().st_mtime_ns == after for output in [changed, replaced, new, unrelated])


def test_complete_archive_hash_covers_resources_extensions_and_frameworks(tmp_path: Path) -> None:
    release = load_module()
    archive = make_archive(tmp_path, "ios")
    nested_files = [
        archive / "Products/Applications/OpenMates.app/Resources/model.json",
        archive / "Products/Applications/OpenMates.app/PlugIns/Share.appex/payload.bin",
        archive / "Products/Applications/OpenMates.app/Frameworks/Support.framework/Support",
    ]
    for index, path in enumerate(nested_files):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"content-{index}".encode())
    previous = release.validate_archive(archive, "ios", "0.21.0", 74)
    for index, path in enumerate(nested_files):
        path.write_bytes(path.read_bytes() + f"-changed-{index}".encode())
        current = release.validate_archive(archive, "ios", "0.21.0", 74)
        assert previous["file_count"] == current["file_count"]
        assert previous["tree_sha256"] != current["tree_sha256"]
        previous = current


def test_untrusted_archive_adoption_option_is_removed() -> None:
    release = load_module()
    with pytest.raises(SystemExit):
        release.build_parser().parse_args(["--adopt-existing-archives"])


def test_help_and_dry_run_are_available_without_credentials(monkeypatch, capsys) -> None:
    release = load_module()
    with pytest.raises(SystemExit) as exited:
        release.build_parser().parse_args(["--help"])
    assert exited.value.code == 0
    assert "iOS+Watch" in capsys.readouterr().out


def test_export_options_are_reused_and_validated(tmp_path: Path) -> None:
    release = load_module()
    path = tmp_path / "ExportOptions.plist"
    write_plist(path, {
        "destination": "upload",
        "manageAppVersionAndBuildNumber": False,
        "method": "app-store-connect",
        "signingStyle": "automatic",
        "teamID": "TEAM",
        "testFlightInternalTestingOnly": True,
        "uploadSymbols": True,
    })

    assert len(release.validate_export_options(path, "TEAM")) == 64
    with pytest.raises(release.ReleaseError, match="teamID"):
        release.validate_export_options(path, "OTHER")


@pytest.mark.parametrize("bridge,required", [
    ("PairOpaqueBridge", (
        "Cargo.toml", "Cargo.lock", "src/lib.rs", "include/PairOpaqueBridge.h",
        "build-apple.sh", "localize-runtime.sh", "local-runtime-symbols.txt",
    )),
])
def test_rust_bridge_source_changes_invalidate_archives_but_build_caches_do_not(
    tmp_path: Path, monkeypatch, bridge: str, required: tuple[str, ...],
) -> None:
    release = load_module()
    bridge_inputs = tuple(path for path in release.SOURCE_INPUTS if path.startswith(f"apple/{bridge}/"))
    monkeypatch.setattr(release, "SOURCE_INPUTS", bridge_inputs)
    monkeypatch.setattr(release, "project_external_inputs", lambda repo_root: [])
    bridge_root = tmp_path / "apple" / bridge
    for relative in required:
        path = bridge_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture source\n")
    before = release.source_content_identity(tmp_path)
    for relative in required:
        path = bridge_root / relative
        path.write_text(path.read_text() + "changed\n")
        after = release.source_content_identity(tmp_path)
        assert after["content_sha256"] != before["content_sha256"], relative
        before = after
    cached = bridge_root / "target/release/bridge.a"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"reproducible build cache")
    assert release.source_content_identity(tmp_path) == before


@pytest.mark.parametrize("permission", [
    "com.apple.security.files.user-selected.read-only",
    "com.apple.security.device.audio-input",
])
@pytest.mark.parametrize("value", [None, False, "true"])
@pytest.mark.parametrize("resumed", [False, True])
def test_macos_release_rejects_missing_effective_lab_permissions(
    tmp_path: Path, monkeypatch, permission: str, value: object, resumed: bool,
) -> None:
    release = load_module()
    archive = make_archive(tmp_path, "macos")
    entitlements = release.resolved_macos_entitlements(
        SCRIPT.parent.parent / "apple/OpenMates/Resources/OpenMatesMacOS.entitlements",
        "TEAMID", "org.openmates.app",
    )
    entitlements[permission] = value
    monkeypatch.setattr(release, "signed_entitlements", lambda bundle: (
        entitlements if bundle.name == "OpenMates.app" else extension_entitlements(bundle)
    ))
    identity = {"tree_sha256": "unchanged"}
    monkeypatch.setattr(release, "validate_archive", lambda *args: identity)
    with pytest.raises(release.ReleaseError, match=permission):
        if resumed:
            release.validate_resumed_archive(archive, "macos", "0.27.0", 89, {"archive_identity": identity})
        else:
            release.validate_release_entitlements(archive, "macos")


def test_onnx_normalizer_sources_invalidate_release_identity(tmp_path: Path, monkeypatch) -> None:
    release = load_module()
    assert not any("LocalNeuralTTSKitten" in path for path in release.SOURCE_INPUTS)
    inputs = tuple(path for path in release.SOURCE_INPUTS if path == "apple/LocalModelBridge")
    assert inputs == ("apple/LocalModelBridge",)
    monkeypatch.setattr(release, "SOURCE_INPUTS", inputs)
    monkeypatch.setattr(release, "project_external_inputs", lambda repo_root: [])
    source = tmp_path / "apple/LocalModelBridge/normalize_onnx_macos.py"
    source.parent.mkdir(parents=True)
    source.write_text("source")
    before = release.source_content_identity(tmp_path)
    source.write_text("changed source")
    assert release.source_content_identity(tmp_path)["content_sha256"] != before["content_sha256"]


def thin_macho_fixture() -> bytes:
    header = struct.pack("<IiiIIIII", 0xFEEDFACF, 0x100000C, 0, 6, 1, 152, 0, 0)
    segment = struct.pack("<II16sQQQQiiII", 0x19, 152, b"__TEXT", 0, 4, 184, 4, 5, 5, 1, 0)
    section = struct.pack("<16s16sQQIIIIIIII", b"__text", b"__TEXT", 0, 4, 184, 0, 0, 0, 0, 0, 0, 0)
    return header + segment + section + b"code" + b"signature"


def test_compiled_section_identity_ignores_signature_and_detects_code(tmp_path: Path) -> None:
    release = load_module()
    binary = tmp_path / "binary"
    binary.write_bytes(thin_macho_fixture())
    before = release.macho_section_identity(binary)
    binary.write_bytes(thin_macho_fixture()[:188] + b"new signature")
    assert release.macho_section_identity(binary) == before
    binary.write_bytes(thin_macho_fixture()[:184] + b"edit" + b"signature")
    assert release.macho_section_identity(binary) != before


def test_ios_onnx_packaging_repairs_minimum_and_preserves_signing(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace
    release = load_module()
    archive = make_archive(tmp_path, "ios")
    app = archive / "Products/Applications/OpenMates.app"
    framework = app / "Frameworks/onnxruntime.framework"
    info = framework / "Info.plist"
    write_plist(info, {"CFBundleExecutable": "onnxruntime", "CFBundleIdentifier": "com.microsoft.onnxruntime"})
    for binary in (framework / "onnxruntime", app / "OpenMates"):
        binary.write_bytes(thin_macho_fixture())
    monkeypatch.setattr(release.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="platform IOS\nminos 17.0\n"))
    monkeypatch.setattr(release, "signed_entitlements", lambda path: {"application-identifier": "TEAM.org.openmates.app"})
    calls = []
    def run(command, log_path, timeout):
        calls.append(command)
        if "-d" in command:
            prefix = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--extract-certificates="))
            Path(prefix + "0").write_bytes(b"original certificate")
    monkeypatch.setattr(release, "run_logged", run)
    receipt = release.normalize_ios_onnx_packaging(archive, tmp_path / "normalization.log")
    assert release.load_plist(info)["MinimumOSVersion"] == "17.0"
    assert receipt["app_entitlements_unchanged"] and receipt["deep_signature_verified"]
    assert receipt["before_archive_identity"] != receipt["after_archive_identity"]
    assert len(list(tmp_path.glob("onnx-ios-packaging-*/framework-Info-original.plist"))) == 1
    signing = [command for command in calls if "--sign" in command]
    assert [command[-1] for command in signing] == [str(framework), str(app)]
    assert all("--preserve-metadata=identifier,entitlements,requirements,flags,runtime" in command for command in signing)
    assert signing[0][signing[0].index("--sign") + 1] != "-"
    assert release.normalize_ios_onnx_packaging(archive, tmp_path / "normalization.log") is None


@pytest.mark.parametrize("build_info", ["platform MACOS\nminos 17.0\n", "platform IOS\nminos 16.0\n"])
def test_ios_onnx_packaging_rejects_unknown_runtime_before_mutation(tmp_path: Path, monkeypatch, build_info: str) -> None:
    from types import SimpleNamespace
    release = load_module()
    archive = make_archive(tmp_path, "ios")
    info = archive / "Products/Applications/OpenMates.app/Frameworks/onnxruntime.framework/Info.plist"
    write_plist(info, {"CFBundleExecutable": "onnxruntime"})
    before = info.read_bytes()
    monkeypatch.setattr(release.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=build_info))
    with pytest.raises(release.ReleaseError, match="supported Mach-O"):
        release.normalize_ios_onnx_packaging(archive, tmp_path / "normalization.log")
    assert info.read_bytes() == before
