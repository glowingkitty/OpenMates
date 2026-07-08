#!/usr/bin/env python3
"""Deterministic Apple release preflight audit.

This audit catches the high-churn Apple packaging and TestFlight contracts that
otherwise fail late in remote Xcode archives. It is intentionally path-scoped so
OpenCode hooks and commit guards can run it cheaply after Apple release files are
edited, while still exposing `--all` for manual full checks.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_YML = REPO_ROOT / "apple" / "project.yml"
XCODE_PROJECT = REPO_ROOT / "apple" / "OpenMates.xcodeproj" / "project.pbxproj"
MAIN_INFO_PLIST = REPO_ROOT / "apple" / "OpenMates" / "Resources" / "Info.plist"
WATCH_INFO_PLIST = REPO_ROOT / "apple" / "OpenMatesWatch" / "Info.plist"
MAIN_ENTITLEMENTS = REPO_ROOT / "apple" / "OpenMates" / "Resources" / "OpenMatesPasskey.entitlements"
APPLE_REMOTE = REPO_ROOT / "scripts" / "apple_remote.py"

APPLE_RELEASE_PATH_RE = re.compile(
    r"^(apple/project\.yml|apple/OpenMates\.xcodeproj/project\.pbxproj|apple/.+(?:Info\.plist|\.entitlements|\.xcassets)|scripts/apple_remote\.py|scripts/tests/test_apple_remote_testflight\.py|scripts/tests/test_app_version_parity\.py)"
)
REQUIRED_BUNDLE_IDS = {
    "org.openmates.app",
    "org.openmates.app.share",
    "org.openmates.app.sharemacos",
    "org.openmates.app.widget",
    "org.openmates.app.watch",
}
REQUIRED_WATCH_TERMS = {
    "project.yml embeds modern Watch app": "- target: OpenMatesWatch",
    "project.yml marks Watch dependency embedded": "embed: true",
    "project.yml uses watchOS application target": "platform: watchOS",
    "project.yml uses Watch app icon": "ASSETCATALOG_COMPILER_APPICON_NAME: WatchAppIcon",
    "project.yml keeps Watch out of top-level install": "SKIP_INSTALL: YES",
}
REQUIRED_XCODE_TERMS = {
    "Xcode embeds Watch content under Watch folder": 'dstPath = "$(CONTENTS_FOLDER_PATH)/Watch";',
    "Xcode embeds the Watch app product": "OpenMatesWatch.app in Embed Watch Content",
    "Xcode uses modern Watch application product": 'productType = "com.apple.product-type.application";',
    "Xcode skips standalone Watch install in iOS archive": "SKIP_INSTALL = YES;",
    "Xcode uses Watch app icon": "ASSETCATALOG_COMPILER_APPICON_NAME = WatchAppIcon;",
}
FORBIDDEN_XCODE_TERMS = {
    "legacy Watch extension embed": "OpenMatesWatchExtension.appex in Embed App Extensions",
    "legacy WatchKit extension target type": 'productType = "com.apple.product-type.watchkit2-extension";',
    "legacy Watch app container product type": 'productType = "com.apple.product-type.application.watchapp2-container";',
    "legacy Watch app product type": 'productType = "com.apple.product-type.application.watchapp2";',
}
REQUIRED_WATCH_PLIST_TERMS = {
    "Watch declares executable": "CFBundleExecutable",
    "Watch declares application package": "CFBundlePackageType",
    "Watch declares WKApplication": "WKApplication",
    "Watch declares companion app": "WKCompanionAppBundleIdentifier",
    "Watch declares independent runtime": "WKRunsIndependentlyOfCompanionApp",
    "Watch declares microphone usage": "NSMicrophoneUsageDescription",
    "Watch declares export compliance": "ITSAppUsesNonExemptEncryption",
}
REQUIRED_MAIN_PLIST_TERMS = {
    "main app declares microphone usage": "NSMicrophoneUsageDescription",
    "main app declares export compliance": "ITSAppUsesNonExemptEncryption",
}
REQUIRED_ENTITLEMENT_TERMS = {
    "main app keeps shared App Group": "group.org.openmates.app.shared",
    "main app keeps associated domains entitlement": "com.apple.developer.associated-domains",
    "main app keeps production webcredential domain": "webcredentials:openmates.org",
    "main app keeps dev webcredential domain": "$(OPENMATES_DEV_WEBCREDENTIALS)",
}
REQUIRED_TESTFLIGHT_TERMS = {
    "TestFlight upload requires --whats-new or --whats-new-file": "TestFlight uploads require --whats-new or --whats-new-file",
    "TestFlight changelog length is capped": "TestFlight What to Test text must be 4000 characters or less",
    "TestFlight notes are uploaded after binary upload": "upsert_testflight_whats_new()",
}


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def _staged_paths() -> list[Path]:
    result = _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    return [REPO_ROOT / line.strip() for line in result.stdout.splitlines() if line.strip()]


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _missing_terms(path: Path, terms: dict[str, str]) -> list[str]:
    text = _read(path)
    if not text:
        return [f"missing required file: {_rel(path)}"]
    return [f"{_rel(path)} missing {label}: {term}" for label, term in terms.items() if term not in text]


def _forbidden_terms(path: Path, terms: dict[str, str]) -> list[str]:
    text = _read(path)
    return [f"{_rel(path)} contains forbidden {label}: {term}" for label, term in terms.items() if term in text]


def _bundle_id_issues() -> list[str]:
    combined = "\n".join(_read(path) for path in (PROJECT_YML, XCODE_PROJECT))
    return [f"Apple project files missing bundle identifier: {bundle_id}" for bundle_id in sorted(REQUIRED_BUNDLE_IDS) if bundle_id not in combined]


def _native_target_issues() -> list[str]:
    project_text = _read(PROJECT_YML)
    xcode_text = _read(XCODE_PROJECT)
    issues: list[str] = []

    project_targets = set(re.findall(r"(?m)^  ([A-Za-z0-9_]+):\s*$", project_text))
    xcode_targets = set(re.findall(r"(?m)^\s+name = ([A-Za-z0-9_]+);\s*$", xcode_text))
    expected_xcode_targets = set(project_targets)
    if "OpenMates" in project_targets:
        expected_xcode_targets.add("OpenMates_iOS")
        expected_xcode_targets.add("OpenMates_macOS")
        expected_xcode_targets.discard("OpenMates")

    required_targets = {"OpenMates_iOS", "OpenMates_macOS", "OpenMatesWatch", "OpenMatesShareExtension", "OpenMatesShareExtension_macOS", "OpenMatesWidget"}
    for target in sorted(required_targets - xcode_targets):
        issues.append(f"{_rel(XCODE_PROJECT)} missing required native target: {target}")
    for target in sorted((expected_xcode_targets & required_targets) - xcode_targets):
        issues.append(f"{_rel(XCODE_PROJECT)} missing project.yml target mirror: {target}")
    return issues


def _has_relevant_path(paths: list[Path]) -> bool:
    return any(APPLE_RELEASE_PATH_RE.search(_rel(path)) for path in paths)


def audit_paths(paths: list[Path]) -> list[str]:
    """Return Apple release preflight failures for relevant changed paths."""
    if not _has_relevant_path(paths):
        return []

    issues: list[str] = []
    issues.extend(_missing_terms(PROJECT_YML, REQUIRED_WATCH_TERMS))
    issues.extend(_missing_terms(XCODE_PROJECT, REQUIRED_XCODE_TERMS))
    issues.extend(_forbidden_terms(XCODE_PROJECT, FORBIDDEN_XCODE_TERMS))
    issues.extend(_missing_terms(WATCH_INFO_PLIST, REQUIRED_WATCH_PLIST_TERMS))
    issues.extend(_missing_terms(MAIN_INFO_PLIST, REQUIRED_MAIN_PLIST_TERMS))
    issues.extend(_missing_terms(MAIN_ENTITLEMENTS, REQUIRED_ENTITLEMENT_TERMS))
    issues.extend(_missing_terms(APPLE_REMOTE, REQUIRED_TESTFLIGHT_TERMS))
    issues.extend(_bundle_id_issues())
    issues.extend(_native_target_issues())
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Apple release packaging and TestFlight preflight contracts.")
    parser.add_argument("paths", nargs="*", help="Specific paths to audit. Defaults to staged Apple release files.")
    parser.add_argument("--all", action="store_true", help="Run the Apple preflight regardless of changed paths.")
    parser.add_argument("--hook", action="store_true", help="Return exit 2 for hook warnings instead of exit 1.")
    args = parser.parse_args(argv)

    if args.all:
        paths = [PROJECT_YML]
    elif args.paths:
        paths = [REPO_ROOT / path for path in args.paths]
    else:
        paths = _staged_paths()

    issues = audit_paths(paths)
    if not issues:
        return 0

    print("[apple-release-preflight] Issues found:", file=sys.stderr)
    for issue in issues[:80]:
        print(f"  - {issue}", file=sys.stderr)
    if len(issues) > 80:
        print(f"  - ... {len(issues) - 80} more issue(s)", file=sys.stderr)
    return 2 if args.hook else 1


if __name__ == "__main__":
    raise SystemExit(main())
