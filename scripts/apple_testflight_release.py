#!/usr/bin/env python3
"""Build, upload, and verify one unified OpenMates TestFlight release.

The workflow is deliberately receipt based. Re-running the same command skips a
completed stage only after its input fingerprint and output artifacts still
match. It never deletes DerivedData, archives, simulators, or installed apps.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import apple_remote


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_PATH = REPO_ROOT / "apple" / "OpenMates.xcodeproj"
PROJECT_SPEC = REPO_ROOT / "apple" / "project.yml"
BUNDLE_ID = "org.openmates.app"
TEAM_ID_PATTERN = re.compile(r"(?m)^\s*DEVELOPMENT_TEAM:\s*[\"']?([^\s\"']+)")
VERSION_PATTERN = re.compile(r"(?m)^\s*MARKETING_VERSION:\s*[\"']?([^\s\"']+)")
BUILD_PATTERN = re.compile(r"(?m)^\s*CURRENT_PROJECT_VERSION:\s*(\d+)")
SOURCE_INPUTS = (
    "package.json",
    "pnpm-lock.yaml",
    "apple/project.yml",
    "apple/OpenMates.xcodeproj",
    "apple/OpenMates",
    "apple/OpenMatesShared",
    "apple/OpenMatesNotificationService",
    "apple/OpenMatesShareExtension",
    "apple/OpenMatesShareExtensionMacOS",
    "apple/OpenMatesWatch",
    "apple/OpenMatesWatchExtension",
    "apple/OpenMatesWidget",
    "apple/AppIcon",
    "frontend/packages/ui/package.json",
    "frontend/packages/ui/scripts/build-translations.js",
    "frontend/packages/ui/scripts/build-tokens.js",
    "frontend/packages/ui/static/images/mates",
    "frontend/packages/ui/src/demo_chats/data/example_chats",
    "frontend/packages/ui/src/i18n/sources",
    "frontend/packages/ui/src/i18n/locales",
    "frontend/packages/ui/src/tokens",
)
SOURCE_EXCLUDED_PARTS = {"xcuserdata", ".DS_Store", "__pycache__"}
PROJECT_PATH_PATTERN = re.compile(r"^\s*(?:-\s*)?path:\s*([^#]+?)\s*(?:#.*)?$")
RECEIPT_SCHEMA = 1
DEFAULT_MIN_FREE_GB = 12.0
DEFAULT_TIMEOUT_SECONDS = 45 * 60
DEFAULT_POLL_SECONDS = 30
VALID_PROCESSING_STATE = "VALID"
FAILED_PROCESSING_STATES = {"FAILED", "INVALID"}


class ReleaseError(RuntimeError):
    """An expected, actionable release failure."""


def prepare_build_keychain(home: Path | None = None) -> bool:
    """Unlock the existing signing keychain for unattended Xcode archives."""
    home = home or Path.home()
    password_path = home / ".config/openmates/apple-build-keychain-password"
    keychain = home / "Library/Keychains/openmates-build.keychain-db"
    if not password_path.is_file() or not keychain.is_file():
        return False
    password = password_path.read_text(encoding="utf-8").strip()
    if not password:
        raise ReleaseError("Apple build keychain password file is empty")
    commands = (
        ("unlock", ["security", "unlock-keychain", "-p", password, str(keychain)]),
        ("keep unlocked", ["security", "set-keychain-settings", "-lut", "21600", str(keychain)]),
        ("permit codesign", [
            "security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:",
            "-s", "-k", password, str(keychain),
        ]),
    )
    for label, command in commands:
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise ReleaseError(f"Could not {label} Apple build keychain (exit {result.returncode})")
    return True


@dataclass(frozen=True)
class ProjectSettings:
    version: str
    configured_build: int
    team_id: str


@dataclass(frozen=True)
class Credentials:
    key_path: Path
    key_id: str
    issuer_id: str

    def environment(self) -> dict[str, str]:
        return {
            "APP_STORE_CONNECT_API_KEY_PATH": str(self.key_path),
            "APP_STORE_CONNECT_API_KEY_ID": self.key_id,
            "APP_STORE_CONNECT_API_ISSUER_ID": self.issuer_id,
        }

    def xcode_arguments(self) -> list[str]:
        return [
            "-authenticationKeyPath", str(self.key_path),
            "-authenticationKeyID", self.key_id,
            "-authenticationKeyIssuerID", self.issuer_id,
        ]


@dataclass(frozen=True)
class BuildRecord:
    identifier: str
    version: str
    build_number: int
    processing_state: str
    platform: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_project_settings(path: Path = PROJECT_SPEC) -> ProjectSettings:
    text = path.read_text(encoding="utf-8")
    version = VERSION_PATTERN.search(text)
    build = BUILD_PATTERN.search(text)
    team = TEAM_ID_PATTERN.search(text)
    if not version or not build or not team:
        raise ReleaseError(f"Could not read release settings from {path.relative_to(REPO_ROOT)}")
    return ProjectSettings(version.group(1), int(build.group(1)), team.group(1))


def project_external_inputs(repo_root: Path = REPO_ROOT) -> list[str]:
    project_spec = repo_root / "apple" / "project.yml"
    if not project_spec.is_file():
        raise ReleaseError("Apple project specification is missing")
    apple_root = (repo_root / "apple").resolve()
    external: set[str] = set()
    for line in project_spec.read_text(encoding="utf-8").splitlines():
        match = PROJECT_PATH_PATTERN.match(line)
        if not match:
            continue
        raw = match.group(1).strip().strip('"').strip("'")
        candidate = (apple_root / raw).resolve()
        try:
            candidate.relative_to(repo_root.resolve())
        except ValueError as exc:
            raise ReleaseError(f"Apple project input escapes the repository: {raw}") from exc
        try:
            candidate.relative_to(apple_root)
            continue
        except ValueError:
            pass
        if not candidate.exists():
            raise ReleaseError(f"External Apple project input is missing: {raw}")
        external.add(candidate.relative_to(repo_root.resolve()).as_posix())
    return sorted(external)


def source_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    files: set[Path] = set()
    for relative in (*SOURCE_INPUTS, *project_external_inputs(repo_root)):
        candidate = repo_root / relative
        if candidate.is_file():
            files.add(candidate)
            continue
        if not candidate.is_dir():
            raise ReleaseError(f"Apple release input is missing: {relative}")
        for path in candidate.rglob("*"):
            if not path.is_file() or any(part in SOURCE_EXCLUDED_PARTS for part in path.relative_to(repo_root).parts):
                continue
            files.add(path)
    return sorted(files, key=lambda item: item.as_posix())


def source_content_identity(repo_root: Path = REPO_ROOT) -> dict[str, object]:
    digest = hashlib.sha256()
    count = 0
    for path in source_files(repo_root):
        if not path.is_file():
            continue
        relative = path.relative_to(repo_root).as_posix()
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
        count += 1
    return {"content_sha256": digest.hexdigest(), "file_count": count}


def source_identity(repo_root: Path = REPO_ROOT) -> dict[str, object]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root,
        capture_output=True, text=True, check=False,
    )
    if head.returncode != 0:
        raise ReleaseError("Could not determine the source commit")
    content = source_content_identity(repo_root)
    return {
        "commit": head.stdout.strip(),
        **content,
    }


def archive_paths(release_dir: Path) -> dict[str, Path]:
    return {
        "ios": release_dir / "OpenMates-iOS.xcarchive",
        "macos": release_dir / "OpenMates-macOS.xcarchive",
    }


def load_plist(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            value = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise ReleaseError(f"Invalid or missing plist: {path}") from exc
    if not isinstance(value, dict):
        raise ReleaseError(f"Expected a plist dictionary: {path}")
    return value


def require_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise ReleaseError(f"{label} mismatch: expected {expected!r}, found {actual!r}")


def archive_identity(path: Path, platform: str) -> dict[str, object]:
    app = path / "Products" / "Applications" / "OpenMates.app"
    if platform == "macos":
        app_info = app / "Contents" / "Info.plist"
        executable = app / "Contents" / "MacOS" / "OpenMates"
        extra_files: list[Path] = []
    else:
        app_info = app / "Info.plist"
        executable = app / "OpenMates"
        watch_apps = sorted((app / "Watch").glob("*.app"))
        if len(watch_apps) != 1:
            raise ReleaseError("iOS archive must contain exactly one Watch companion app")
        watch_info = watch_apps[0] / "Info.plist"
        watch_plist = load_plist(watch_info)
        watch_executable_name = str(watch_plist.get("CFBundleExecutable") or "")
        extra_files = [watch_info, watch_apps[0] / watch_executable_name]
    required_files = [path / "Info.plist", app_info, executable, *extra_files]
    missing = [item for item in required_files if not item.is_file()]
    if missing:
        raise ReleaseError(f"Archive identity files are missing: {missing[0]}")
    digest = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    for item in sorted(path.rglob("*"), key=lambda entry: entry.relative_to(path).as_posix()):
        relative = item.relative_to(path).as_posix()
        if item.is_symlink():
            digest.update(b"link\0" + relative.encode("utf-8") + b"\0" + os.readlink(item).encode("utf-8") + b"\0")
            continue
        if not item.is_file():
            continue
        size = item.stat().st_size
        digest.update(b"file\0" + relative.encode("utf-8") + b"\0" + str(size).encode("ascii") + b"\0")
        digest.update(bytes.fromhex(sha256_file(item)))
        file_count += 1
        total_bytes += size
    try:
        display_path = str(path.relative_to(REPO_ROOT))
    except ValueError:
        display_path = str(path)
    return {
        "path": display_path,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "tree_sha256": digest.hexdigest(),
    }


def validate_archive(path: Path, platform: str, version: str, build_number: int) -> dict[str, object]:
    archive_info = load_plist(path / "Info.plist")
    properties = archive_info.get("ApplicationProperties")
    if not isinstance(properties, dict):
        raise ReleaseError(f"Archive ApplicationProperties missing: {path}")
    require_equal(properties.get("CFBundleIdentifier"), BUNDLE_ID, f"{platform} bundle ID")
    require_equal(properties.get("CFBundleShortVersionString"), version, f"{platform} marketing version")
    require_equal(str(properties.get("CFBundleVersion")), str(build_number), f"{platform} build number")
    architectures = set(properties.get("Architectures") or [])
    if platform == "macos":
        require_equal(architectures, {"arm64", "x86_64"}, "macOS archive architectures")
    elif "arm64" not in architectures:
        raise ReleaseError("iOS archive does not contain arm64")

    app = path / "Products" / "Applications" / "OpenMates.app"
    app_info_path = app / ("Contents/Info.plist" if platform == "macos" else "Info.plist")
    app_info = load_plist(app_info_path)
    require_equal(app_info.get("CFBundleIdentifier"), BUNDLE_ID, f"{platform} app bundle ID")
    require_equal(app_info.get("CFBundleShortVersionString"), version, f"{platform} app version")
    require_equal(str(app_info.get("CFBundleVersion")), str(build_number), f"{platform} app build")

    if platform == "ios":
        watch_apps = sorted((app / "Watch").glob("*.app"))
        if len(watch_apps) != 1:
            raise ReleaseError("iOS archive must contain exactly one Watch companion app")
        watch = load_plist(watch_apps[0] / "Info.plist")
        require_equal(watch.get("CFBundleIdentifier"), "org.openmates.app.watch", "Watch bundle ID")
        require_equal(watch.get("WKCompanionAppBundleIdentifier"), BUNDLE_ID, "Watch companion bundle ID")
        require_equal(watch.get("CFBundleShortVersionString"), version, "Watch marketing version")
        require_equal(str(watch.get("CFBundleVersion")), str(build_number), "Watch build number")
    return archive_identity(path, platform)


def release_fingerprint(source: dict[str, object], version: str, build_number: int, export_sha: str) -> str:
    payload = {
        "source": source,
        "version": version,
        "build_number": build_number,
        "export_options_sha256": export_sha,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def receipt_path(release_dir: Path, stage: str) -> Path:
    return release_dir / "receipts" / f"{stage}.json"


def read_receipt(release_dir: Path, stage: str, fingerprint: str) -> dict[str, object] | None:
    path = receipt_path(release_dir, stage)
    if not path.is_file():
        return None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("fingerprint") != fingerprint:
        return None
    return receipt


def write_receipt(release_dir: Path, stage: str, fingerprint: str, details: dict[str, object]) -> None:
    path = receipt_path(release_dir, stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "stage": stage,
        "status": "complete",
        "fingerprint": fingerprint,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        **details,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_export_options(path: Path, team_id: str) -> str:
    options = load_plist(path)
    required = {
        "destination": "upload",
        "manageAppVersionAndBuildNumber": False,
        "method": "app-store-connect",
        "teamID": team_id,
        "testFlightInternalTestingOnly": True,
        "uploadSymbols": True,
    }
    for key, expected in required.items():
        require_equal(options.get(key), expected, f"ExportOptions {key}")
    return sha256_file(path)


def find_export_options(release_dir: Path, explicit: Path | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    candidates.extend([
        release_dir / "ExportOptions.plist",
        release_dir / "ExportOptions-iOS.plist",
        release_dir / "ExportOptions-macOS.plist",
    ])
    candidates.extend(
        sorted(
            (REPO_ROOT / ".runtime").glob("testflight-build-*/ExportOptions-iOS.plist"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise ReleaseError("No existing ExportOptions plist found; pass --export-options")


def credentials_from_options(args: argparse.Namespace, *, required: bool) -> Credentials | None:
    local_config = apple_remote.load_local_config()
    options = apple_remote.app_store_connect_api_options(args, local_config)
    present = [bool(value) for value in options.values()]
    if any(present) and not all(present):
        apple_remote.require_app_store_connect_api_options(options, "apple_testflight_release")
    if not all(present):
        if required:
            apple_remote.require_app_store_connect_api_options(options, "apple_testflight_release")
        return None
    key_path = Path(str(options["api_key_path"])).expanduser().resolve()
    if not getattr(args, "dry_run", False) and not key_path.is_file():
        raise ReleaseError("App Store Connect API key file does not exist")
    return Credentials(key_path, str(options["api_key_id"]), str(options["api_issuer_id"]))


def run_logged(command: Sequence[str], log_path: Path, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(
            list(command), cwd=REPO_ROOT, stdout=log, stderr=subprocess.STDOUT,
            text=True, timeout=timeout, check=False,
        )
    if result.returncode == 0:
        return
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
    for line in lines:
        print(line[:500], file=sys.stderr)
    raise ReleaseError(f"Command failed; bounded tail shown, full log: {log_path.relative_to(REPO_ROOT)}")


def generate_release_inputs(release_dir: Path) -> None:
    package = "frontend/packages/ui"
    commands = (
        ("translations", ["npm", "--prefix", package, "run", "build:translations"]),
        ("tokens", ["npm", "--prefix", package, "run", "build:tokens"]),
    )
    for name, command in commands:
        print(f"stage=generate-{name} status=started log=generate-{name}.log")
        run_logged(command, release_dir / f"generate-{name}.log", timeout=10 * 60)
        print(f"stage=generate-{name} status=complete")


def archive_command(platform: str, release_dir: Path, build_number: int, team_id: str, credentials: Credentials | None) -> list[str]:
    path = archive_paths(release_dir)[platform]
    command = [
        "xcodebuild", "-project", str(PROJECT_PATH.relative_to(REPO_ROOT)),
        "-scheme", "OpenMates_iOS" if platform == "ios" else "OpenMates_macOS",
        "-configuration", "Release",
        "-destination", "generic/platform=iOS" if platform == "ios" else "generic/platform=macOS",
        "-archivePath", str(path),
        "-derivedDataPath", str(release_dir / ("ios-derived" if platform == "ios" else "mac-derived")),
        "-allowProvisioningUpdates",
        f"DEVELOPMENT_TEAM={team_id}", f"CURRENT_PROJECT_VERSION={build_number}",
    ]
    if credentials:
        command[command.index(f"DEVELOPMENT_TEAM={team_id}"):command.index(f"DEVELOPMENT_TEAM={team_id}")] = credentials.xcode_arguments()
    if platform == "macos":
        # Limit concurrent universal-architecture Swift compiles on 8 GB Macs.
        command.extend(["-jobs", "1", "ARCHS=arm64 x86_64", "ONLY_ACTIVE_ARCH=NO", "CODE_SIGNING_ALLOWED=NO"])
    command.append("archive")
    return command


def export_command(platform: str, release_dir: Path, export_options: Path, credentials: Credentials | None) -> list[str]:
    command = [
        "xcodebuild", "-exportArchive",
        "-archivePath", str(archive_paths(release_dir)[platform]),
        "-exportPath", str(release_dir / f"{platform}-upload"),
        "-exportOptionsPlist", str(export_options),
        "-allowProvisioningUpdates",
    ]
    if credentials:
        command.extend(credentials.xcode_arguments())
    return command


def run_build_listing(credentials: Credentials) -> list[BuildRecord]:
    env = {**os.environ, **credentials.environment()}
    command = [
        sys.executable, "-c", apple_remote.APP_STORE_BUILDS_SCRIPT,
        BUNDLE_ID, "50", "0", "en-US", "1",
    ]
    result = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120, check=False)
    if result.returncode != 0:
        raise ReleaseError("App Store Connect build lookup failed")
    records: list[BuildRecord] = []
    pattern = re.compile(
        r"^build=(\S+) appVersion=(\S+) buildNumber=(\d+) "
        r"processingState=(\S+) uploadedDate=\S+ platform=(\S+) train=\S+$"
    )
    for line in result.stdout.splitlines():
        match = pattern.match(line)
        if match:
            records.append(BuildRecord(match.group(1), match.group(2), int(match.group(3)), match.group(4), match.group(5)))
    if "build_scan=complete" not in result.stdout:
        raise ReleaseError("App Store Connect did not complete the build scan")
    return records


def platform_record(records: Iterable[BuildRecord], version: str, build_number: int, platform: str) -> BuildRecord | None:
    expected = "IOS" if platform == "ios" else "MAC_OS"
    return next(
        (item for item in records if item.version == version and item.build_number == build_number and item.platform == expected),
        None,
    )


def prove_existing_upload(
    existing: BuildRecord,
    receipt: dict[str, object] | None,
    platform: str,
    *,
    archive_path: Path | None = None,
    archive_identity_value: dict[str, object] | None = None,
) -> dict[str, object]:
    if not receipt:
        raise ReleaseError(
            f"App Store Connect already has {platform} build {existing.build_number}, "
            "but this source fingerprint has no upload receipt; choose another build number"
        )
    receipt_build_id = receipt.get("build_id")
    if receipt_build_id:
        if receipt_build_id != existing.identifier:
            raise ReleaseError(
                f"App Store Connect {platform} build ID does not match the source-bound upload receipt"
            )
    else:
        archive_hash = (archive_identity_value or {}).get("tree_sha256")
        if (
            receipt.get("upload_provenance") != "xcarchive_distribution"
            or not archive_hash
            or receipt.get("archive_tree_sha256") != archive_hash
            or archive_path is None
            or not archive_reports_successful_upload(archive_path, existing.build_number)
        ):
            raise ReleaseError(
                f"App Store Connect {platform} build has no matching build ID or proven xcarchive upload receipt"
            )
    if existing.platform != ("IOS" if platform == "ios" else "MAC_OS"):
        raise ReleaseError(
            f"App Store Connect build platform does not match the {platform} upload receipt"
        )
    return {
        "build_id": existing.identifier,
        "upload_accepted": True,
        "observed_in_app_store_connect": True,
    }


def next_build_number(records: Iterable[BuildRecord]) -> int:
    values = [record.build_number for record in records]
    result = max(values, default=0) + 1
    if result > 9999:
        raise ReleaseError("App Store Connect build number range is exhausted")
    return result


def ensure_disk_space(path: Path, minimum_gb: float) -> None:
    free = shutil.disk_usage(path).free
    if free < minimum_gb * 1024 ** 3:
        raise ReleaseError(f"Insufficient disk space: {free / 1024 ** 3:.1f} GiB free, {minimum_gb:.1f} GiB required")


def acquire_release_lock(release_dir: Path):
    release_dir.mkdir(parents=True, exist_ok=True)
    handle = (release_dir / ".release.lock").open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise ReleaseError(f"Another TestFlight process holds the release lock for {release_dir.name}") from exc
    return handle


def archive_reports_successful_upload(path: Path, build_number: int) -> bool:
    info = load_plist(path / "Info.plist")
    distributions = info.get("Distributions") or []
    return any(
        str(item.get("uploadedBuildNumber")) == str(build_number)
        and isinstance(item.get("uploadEvent"), dict)
        and item["uploadEvent"].get("state") == "success"
        for item in distributions
        if isinstance(item, dict)
    )


def preserve_stale_archive(path: Path, release_dir: Path, platform: str) -> Path:
    stale_dir = release_dir / "stale"
    stale_dir.mkdir(parents=True, exist_ok=True)
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = stale_dir / f"{path.name}.{suffix}.{platform}"
    counter = 1
    while target.exists():
        target = stale_dir / f"{path.name}.{suffix}.{platform}.{counter}"
        counter += 1
    path.rename(target)
    return target


def signed_entitlements(bundle: Path) -> dict[str, object]:
    result = subprocess.run(
        ["codesign", "-d", "--entitlements", ":-", str(bundle)],
        capture_output=True, check=False,
    )
    raw = result.stdout if b"<?xml" in result.stdout else result.stderr
    start = raw.find(b"<?xml")
    if result.returncode != 0 or start < 0:
        raise ReleaseError(f"Could not inspect signed entitlements for {bundle.name}")
    try:
        value = plistlib.loads(raw[start:])
    except Exception as exc:
        raise ReleaseError(f"Invalid signed entitlements for {bundle.name}") from exc
    if not isinstance(value, dict):
        raise ReleaseError(f"Signed entitlements are not a dictionary for {bundle.name}")
    return value


def validate_release_entitlements(path: Path, platform: str) -> None:
    app = path / "Products" / "Applications" / "OpenMates.app"
    entitlements = signed_entitlements(app)
    if platform == "ios":
        associated = entitlements.get("com.apple.developer.associated-domains") or []
        groups = entitlements.get("com.apple.security.application-groups") or []
        if "webcredentials:openmates.org" not in associated or "group.org.openmates.app.shared" not in groups:
            raise ReleaseError("iOS archive is missing passkey or app-group entitlements")
        return
    extension = app / "Contents" / "PlugIns" / "OpenMatesShareExtension_macOS.appex"
    extension_entitlements = signed_entitlements(extension)
    if entitlements.get("com.apple.security.app-sandbox") is not True:
        raise ReleaseError("macOS app archive is missing the App Sandbox entitlement")
    if entitlements.get("com.apple.developer.aps-environment") != "production":
        raise ReleaseError("macOS app archive is missing a concrete production APNs entitlement")
    if extension_entitlements.get("com.apple.security.app-sandbox") is not True:
        raise ReleaseError("macOS share extension archive is missing the App Sandbox entitlement")


def resolved_macos_entitlements(source: Path, team_id: str, bundle_id: str) -> dict[str, object]:
    """Expand Xcode build variables before ad hoc signing an unsigned archive."""
    variables = {
        "$(APS_ENVIRONMENT)": "production",
        "$(AppIdentifierPrefix)": f"{team_id}.",
        "$(CFBundleIdentifier)": bundle_id,
    }

    def resolve(value: object) -> object:
        if isinstance(value, str):
            if value == "$(OPENMATES_DEV_WEBCREDENTIALS)":
                return None
            for name, replacement in variables.items():
                value = value.replace(name, replacement)
            if "$(" in value:
                raise ReleaseError("Unresolved macOS entitlement build variable")
            return value
        if isinstance(value, list):
            return [resolved for item in value if (resolved := resolve(item)) is not None]
        if isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        return value

    entitlements = resolve(load_plist(source))
    if not isinstance(entitlements, dict):
        raise ReleaseError("macOS entitlements must be a dictionary")
    return entitlements


def stamp_unsigned_macos_archive(path: Path, log_path: Path, team_id: str) -> None:
    app = path / "Products" / "Applications" / "OpenMates.app"
    extension = app / "Contents" / "PlugIns" / "OpenMatesShareExtension_macOS.appex"
    app_bundle_id = load_plist(app / "Contents" / "Info.plist").get("CFBundleIdentifier")
    extension_bundle_id = load_plist(extension / "Contents" / "Info.plist").get("CFBundleIdentifier")
    if app_bundle_id != BUNDLE_ID or extension_bundle_id != f"{BUNDLE_ID}.sharemacos":
        raise ReleaseError("macOS archive bundle identifiers do not match the signing targets")
    entitlement_paths = (
        ("apple/OpenMatesShareExtensionMacOS/OpenMatesShareExtensionMacOS.entitlements", log_path.with_name("macos-share-entitlements.plist"), extension_bundle_id),
        ("apple/OpenMates/Resources/OpenMatesMacOS.entitlements", log_path.with_name("macos-app-entitlements.plist"), app_bundle_id),
    )
    for source, destination, bundle_id in entitlement_paths:
        with destination.open("wb") as handle:
            plistlib.dump(resolved_macos_entitlements(REPO_ROOT / source, team_id, bundle_id), handle)
    commands = (
        [
            "codesign", "--force", "--sign", "-", "--timestamp=none", "--entitlements",
            str(entitlement_paths[0][1]), str(extension),
        ],
        [
            "codesign", "--force", "--sign", "-", "--timestamp=none", "--entitlements",
            str(entitlement_paths[1][1]), str(app),
        ],
    )
    for index, command in enumerate(commands, 1):
        run_logged(command, log_path.with_name(f"{log_path.stem}-{index}{log_path.suffix}"), timeout=120)


def print_dry_run(commands: Iterable[tuple[str, Sequence[str]]], version: str, build_number: int) -> None:
    for stage, command in commands:
        redacted = list(command)
        if "-authenticationKeyPath" in redacted:
            redacted[redacted.index("-authenticationKeyPath") + 1] = "<api-key>"
        print(f"dry_run_stage={stage} command={subprocess.list2cmdline(redacted)}")
    print(f"testflight_release_status=dry_run version={version} build={build_number} platforms=ios+watch,macos")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build, upload, resume, and verify one unified iOS+Watch and universal macOS TestFlight release.",
        epilog=(
            "Credentials come from APP_STORE_CONNECT_API_* or ~/.config/openmates/apple-remote.json. "
            "No Vercel credential is read. Artifacts and receipts stay in .runtime/testflight-build-N/."
        ),
    )
    parser.add_argument("--build-number", type=int, help="Unified build number; default is max App Store Connect build + 1")
    parser.add_argument("--version", help="Marketing version; default comes from apple/project.yml")
    parser.add_argument("--release-dir", type=Path, help="Artifact directory; default .runtime/testflight-build-N")
    parser.add_argument("--export-options", type=Path, help="Existing validated ExportOptions plist to reuse")
    parser.add_argument("--rebuild-stale-archives", action="store_true", help="Preserve mismatched archives under release-dir/stale and rebuild them")
    parser.add_argument("--verify-only", action="store_true", help="Only verify that both uploaded platform builds finished processing; requires API credentials")
    parser.add_argument("--dry-run", action="store_true", help="Print bounded stage commands without writing, building, uploading, or polling")
    parser.add_argument("--min-free-gb", type=float, default=DEFAULT_MIN_FREE_GB, help=f"Required free disk space; default {DEFAULT_MIN_FREE_GB:g} GiB")
    parser.add_argument("--processing-timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Seconds to wait for both builds; default 2700")
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS, help="App Store Connect poll interval; default 30")
    parser.add_argument("--api-key-path", help="Local path to the App Store Connect API .p8 key")
    parser.add_argument("--api-key-id", help="App Store Connect API key ID")
    parser.add_argument("--api-issuer-id", help="App Store Connect API issuer ID")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = read_project_settings()
        version = args.version or settings.version
        credentials = credentials_from_options(args, required=args.verify_only)
        records = run_build_listing(credentials) if credentials else []
        if not args.build_number and not credentials and not args.dry_run:
            raise ReleaseError("Without App Store Connect API credentials, pass the intended --build-number explicitly")
        build_number = args.build_number or (next_build_number(records) if records else settings.configured_build)
        if not 1 <= build_number <= 9999:
            raise ReleaseError("Build number must be between 1 and 9999")
        release_dir = (args.release_dir or REPO_ROOT / ".runtime" / f"testflight-build-{build_number}").resolve()
        try:
            release_dir.relative_to(REPO_ROOT / ".runtime")
        except ValueError as exc:
            raise ReleaseError("Release directory must stay inside repository .runtime") from exc
        export_options = find_export_options(release_dir, args.export_options)
        export_sha = validate_export_options(export_options, settings.team_id)
        if args.dry_run:
            commands = [
                ("generate-translations", ["npm", "--prefix", "frontend/packages/ui", "run", "build:translations"]),
                ("generate-tokens", ["npm", "--prefix", "frontend/packages/ui", "run", "build:tokens"]),
                ("archive-ios", archive_command("ios", release_dir, build_number, settings.team_id, credentials)),
                ("archive-macos", archive_command("macos", release_dir, build_number, settings.team_id, credentials)),
                ("upload-ios", export_command("ios", release_dir, export_options, credentials)),
                ("upload-macos", export_command("macos", release_dir, export_options, credentials)),
            ]
            print_dry_run(commands, version, build_number)
            return 0

        _release_lock = acquire_release_lock(release_dir)
        ensure_disk_space(REPO_ROOT, args.min_free_gb)
        if not args.verify_only:
            if prepare_build_keychain():
                print("build_keychain=unlocked")
            generate_release_inputs(release_dir)
        source = source_identity()
        fingerprint = release_fingerprint(source, version, build_number, export_sha)
        selected_options = release_dir / "ExportOptions.plist"
        if export_options != selected_options:
            shutil.copy2(export_options, selected_options)
        export_options = selected_options

        if args.verify_only:
            assert credentials is not None
            upload_receipts = {
                platform: read_receipt(release_dir, f"upload-{platform}", fingerprint)
                for platform in ("ios", "macos")
            }
            missing_receipts = [platform for platform, receipt in upload_receipts.items() if not receipt]
            if missing_receipts:
                raise ReleaseError(
                    "Processing verification requires matching source-bound upload receipts for: "
                    + ", ".join(missing_receipts)
                )
            deadline = time.monotonic() + args.processing_timeout
            while True:
                records = run_build_listing(credentials)
                ios = platform_record(records, version, build_number, "ios")
                macos = platform_record(records, version, build_number, "macos")
                if ios and macos and ios.processing_state == VALID_PROCESSING_STATE and macos.processing_state == VALID_PROCESSING_STATE:
                    prove_existing_upload(
                        ios, upload_receipts["ios"], "ios",
                        archive_path=archive_paths(release_dir)["ios"],
                        archive_identity_value=validate_archive(
                            archive_paths(release_dir)["ios"], "ios", version, build_number,
                        ),
                    )
                    prove_existing_upload(
                        macos, upload_receipts["macos"], "macos",
                        archive_path=archive_paths(release_dir)["macos"],
                        archive_identity_value=validate_archive(
                            archive_paths(release_dir)["macos"], "macos", version, build_number,
                        ),
                    )
                    write_receipt(
                        release_dir, "processed", fingerprint,
                        {"ios_build_id": ios.identifier, "macos_build_id": macos.identifier, "processing_state": "VALID"},
                    )
                    print(f"testflight_release_status=complete version={version} build={build_number} ios=VALID watch=embedded macos=VALID")
                    return 0
                failed = [item for item in (ios, macos) if item and item.processing_state in FAILED_PROCESSING_STATES]
                if failed:
                    raise ReleaseError(f"App Store Connect processing failed for {failed[0].platform}")
                if time.monotonic() >= deadline:
                    raise ReleaseError("Timed out waiting for both iOS and macOS builds to finish processing")
                time.sleep(max(5, args.poll_seconds))

        identities: dict[str, object] = {}
        for platform in ("ios", "macos"):
            stage = f"archive-{platform}"
            path = archive_paths(release_dir)[platform]
            receipt = read_receipt(release_dir, stage, fingerprint)
            if receipt:
                identity = validate_archive(path, platform, version, build_number)
                if identity != receipt.get("archive_identity"):
                    raise ReleaseError(f"{platform} archive changed after its receipt was written")
                identities[platform] = identity
                print(f"stage={stage} status=resumed")
                continue
            if path.exists():
                any_receipt = receipt_path(release_dir, stage).exists()
                if any_receipt and args.rebuild_stale_archives:
                    preserved = preserve_stale_archive(path, release_dir, platform)
                    print(f"stage={stage} stale_archive_preserved={preserved.relative_to(REPO_ROOT)}")
                    path = archive_paths(release_dir)[platform]
                elif any_receipt:
                    raise ReleaseError(f"{platform} archive receipt does not match current source; pass --rebuild-stale-archives")
                elif args.rebuild_stale_archives:
                    preserved = preserve_stale_archive(path, release_dir, platform)
                    print(f"stage={stage} stale_archive_preserved={preserved.relative_to(REPO_ROOT)}")
                else:
                    raise ReleaseError(
                        f"Unreceipted {platform} archive has no trusted source provenance; "
                        "pass --rebuild-stale-archives"
                    )
            if not path.exists():
                print(f"stage={stage} status=started log={platform}-archive.log")
                run_logged(archive_command(platform, release_dir, build_number, settings.team_id, credentials), release_dir / f"{platform}-archive.log")
                if platform == "macos":
                    stamp_unsigned_macos_archive(path, release_dir / "macos-entitlements.log", settings.team_id)
                if source_identity()["content_sha256"] != source["content_sha256"]:
                    raise ReleaseError("Apple release source changed during archive creation")
                identity = validate_archive(path, platform, version, build_number)
            validate_release_entitlements(path, platform)
            write_receipt(release_dir, stage, fingerprint, {"source": source, "archive_identity": identity})
            identities[platform] = identity
            print(f"stage={stage} status=complete")

        records = run_build_listing(credentials) if credentials else []
        for platform in ("ios", "macos"):
            stage = f"upload-{platform}"
            existing = platform_record(records, version, build_number, platform) if credentials else None
            upload_receipt = read_receipt(release_dir, stage, fingerprint)
            if existing:
                archive_path = archive_paths(release_dir)[platform]
                details = prove_existing_upload(
                    existing, upload_receipt, platform,
                    archive_path=archive_path,
                    archive_identity_value=validate_archive(archive_path, platform, version, build_number),
                )
                write_receipt(release_dir, stage, fingerprint, details)
                print(f"stage={stage} status=resumed_from_app_store_connect")
                continue
            if upload_receipt:
                print(f"stage={stage} status=resumed")
                continue
            if not credentials and archive_reports_successful_upload(archive_paths(release_dir)[platform], build_number):
                current_identity = validate_archive(
                    archive_paths(release_dir)[platform], platform, version, build_number,
                )
                write_receipt(release_dir, stage, fingerprint, {
                    "build_id": None,
                    "upload_accepted": True,
                    "upload_provenance": "xcarchive_distribution",
                    "archive_tree_sha256": current_identity["tree_sha256"],
                })
                print(f"stage={stage} status=resumed_from_xcarchive")
                continue
            validate_archive(archive_paths(release_dir)[platform], platform, version, build_number)
            print(f"stage={stage} status=started log={platform}-upload.log")
            run_logged(export_command(platform, release_dir, export_options, credentials), release_dir / f"{platform}-upload.log")
            refreshed_identity = validate_archive(
                archive_paths(release_dir)[platform], platform, version, build_number,
            )
            validate_release_entitlements(archive_paths(release_dir)[platform], platform)
            write_receipt(
                release_dir, f"archive-{platform}", fingerprint,
                {"source": source, "archive_identity": refreshed_identity},
            )
            records = run_build_listing(credentials) if credentials else []
            uploaded = platform_record(records, version, build_number, platform) if credentials else None
            write_receipt(
                release_dir, stage, fingerprint,
                {
                    "build_id": uploaded.identifier if uploaded else None,
                    "upload_accepted": True,
                    "upload_provenance": "app_store_connect" if uploaded else "xcarchive_distribution",
                    "archive_tree_sha256": refreshed_identity["tree_sha256"],
                },
            )
            print(f"stage={stage} status=complete")

        if not credentials:
            verify_command = (
                f"python3 scripts/apple_testflight_release.py --build-number {build_number} "
                f"--version {version} --release-dir {release_dir.relative_to(REPO_ROOT)} --verify-only"
            )
            print(
                f"testflight_release_status=uploaded_processing_unverified version={version} build={build_number} "
                f"ios=uploaded watch=embedded macos=uploaded resume_command={json.dumps(verify_command)}"
            )
            return 0

        deadline = time.monotonic() + args.processing_timeout
        previous_processing: tuple[str, str] | None = None
        while True:
            records = run_build_listing(credentials)
            ios = platform_record(records, version, build_number, "ios")
            macos = platform_record(records, version, build_number, "macos")
            failed = [item for item in (ios, macos) if item and item.processing_state in FAILED_PROCESSING_STATES]
            if failed:
                raise ReleaseError(f"App Store Connect processing failed for {failed[0].platform}")
            if ios and macos and ios.processing_state == VALID_PROCESSING_STATE and macos.processing_state == VALID_PROCESSING_STATE:
                ios_upload = read_receipt(release_dir, "upload-ios", fingerprint)
                macos_upload = read_receipt(release_dir, "upload-macos", fingerprint)
                prove_existing_upload(
                    ios, ios_upload, "ios",
                    archive_path=archive_paths(release_dir)["ios"],
                    archive_identity_value=validate_archive(
                        archive_paths(release_dir)["ios"], "ios", version, build_number,
                    ),
                )
                prove_existing_upload(
                    macos, macos_upload, "macos",
                    archive_path=archive_paths(release_dir)["macos"],
                    archive_identity_value=validate_archive(
                        archive_paths(release_dir)["macos"], "macos", version, build_number,
                    ),
                )
                write_receipt(
                    release_dir, "processed", fingerprint,
                    {"ios_build_id": ios.identifier, "macos_build_id": macos.identifier, "processing_state": "VALID"},
                )
                print(f"testflight_release_status=complete version={version} build={build_number} ios=VALID watch=embedded macos=VALID")
                return 0
            current_processing = (
                ios.processing_state if ios else "NOT_FOUND",
                macos.processing_state if macos else "NOT_FOUND",
            )
            if current_processing != previous_processing:
                print(f"stage=processing ios={current_processing[0]} macos={current_processing[1]}")
                previous_processing = current_processing
            if time.monotonic() >= deadline:
                raise ReleaseError("Timed out waiting for both iOS and macOS builds to finish processing")
            time.sleep(max(5, args.poll_seconds))
    except (ReleaseError, apple_remote.AppleRemoteError, subprocess.TimeoutExpired) as exc:
        print(f"testflight_release_status=failed reason={str(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
