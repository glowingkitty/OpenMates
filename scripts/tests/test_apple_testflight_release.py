# contract-test-file: tooling
"""Focused tests for the resumable all-platform TestFlight entrypoint."""

from __future__ import annotations

import importlib.util
import plistlib
import sys
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
    return archive


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


def test_commands_pin_one_build_and_do_not_delete_simulators(tmp_path: Path) -> None:
    release = load_module()
    credentials = release.Credentials(Path("/private/AuthKey.p8"), "KEY", "ISSUER")

    ios = release.archive_command("ios", tmp_path, 74, "TEAM", credentials)
    macos = release.archive_command("macos", tmp_path, 74, "TEAM", credentials)
    all_text = " ".join([*ios, *macos])

    assert all_text.count("CURRENT_PROJECT_VERSION=74") == 2
    assert "OpenMates_iOS" in ios
    assert "OpenMates_macOS" in macos
    assert "ARCHS=arm64 x86_64" in macos
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


def test_macos_stamping_signs_extension_before_parent_app(tmp_path: Path, monkeypatch) -> None:
    release = load_module()
    calls = []
    monkeypatch.setattr(release, "run_logged", lambda command, log_path, timeout: calls.append(command))

    release.stamp_unsigned_macos_archive(tmp_path / "OpenMates-macOS.xcarchive", tmp_path / "stamp.log")

    assert "OpenMatesShareExtension_macOS.appex" in calls[0][-1]
    assert calls[1][-1].endswith("OpenMates.app")
    assert all("--entitlements" in command for command in calls)


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
