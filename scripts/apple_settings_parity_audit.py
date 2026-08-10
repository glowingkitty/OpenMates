#!/usr/bin/env python3
"""Audit Apple settings against the current web settings contract.

The audit is Linux-safe and intentionally distinguishes reachable native routes
from planned declarations. It also rejects known stock product controls and
stale endpoint strings in Apple settings sources so fixture-only UI cannot hide
broken production behavior.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROUTES_PATH = REPO_ROOT / "frontend/packages/ui/src/components/settings/settingsRoutes.ts"
APPLE_SETTINGS_ROOT = REPO_ROOT / "apple/OpenMates/Sources/Features/Settings"
APPLE_SETTINGS_VIEW = APPLE_SETTINGS_ROOT / "Views/SettingsView.swift"
APPLE_PRIVACY_MODELS = APPLE_SETTINGS_ROOT / "Privacy/PrivacySettingsModels.swift"
APPLE_NATIVE_DIAGNOSTICS = REPO_ROOT / "apple/OpenMates/Sources/Core/Diagnostics/NativeDiagnostics.swift"
ACCOUNT_SECURITY_FILES = (
    APPLE_SETTINGS_ROOT / "Services/AccountSecurityService.swift",
    APPLE_SETTINGS_ROOT / "Services/PasskeyRegistrationCoordinator.swift",
    APPLE_SETTINGS_ROOT / "Views/SettingsEmailView.swift",
    APPLE_SETTINGS_ROOT / "Views/SettingsProfilePictureView.swift",
    APPLE_SETTINGS_ROOT / "Views/SettingsStorageFull.swift",
    APPLE_SETTINGS_ROOT / "Views/SettingsAccountChatsView.swift",
    APPLE_SETTINGS_ROOT / "Views/SettingsExportAccountView.swift",
    APPLE_SETTINGS_ROOT / "Views/SettingsSessionPairingView.swift",
    REPO_ROOT / "apple/OpenMates/Sources/Features/Chat/Views/ChatImportView.swift",
)
ACCOUNT_SECURITY_ENDPOINTS = (
    "/v1/auth/passkeys",
    "/v1/auth/passkey/registration/initiate",
    "/v1/auth/passkey/registration/complete",
    "/v1/auth/2fa/setup/initiate",
    "/v1/auth/recovery-key/regenerate",
    "/v1/auth/sessions/logout-others",
    "/v1/settings/user/email/confirm-change",
    "/v1/settings/storage/files",
    "/v1/settings/chats/delete-old",
    "/v1/settings/export-account-data",
    "/v1/auth/pair/initiate",
    "/v1/settings/import-chat",
)

FORBIDDEN_CONTROLS = (
    "List {",
    "Form {",
    "NavigationStack {",
    "NavigationLink {",
    ".navigationTitle(",
    ".toolbar {",
    "ToolbarItem",
    "Image(systemName:",
)
STALE_ENDPOINTS = (
    "/v1/settings/memories",
    "/v1/mates",
    "/v1/settings/privacy/debug-logs",
    "/v1/settings/billing/auto-topup",
    "/v1/settings/billing/invoices",
)
PRIVACY_ENDPOINTS = (
    "/v1/settings/auto-delete-chats",
    "/v1/connected-accounts",
    "/v1/settings/debug-session",
    "/v1/settings/debug-logs",
)


def _object_body(source: str, declaration: str) -> str:
    match = re.search(
        rf"{re.escape(declaration)}[^=]*=\s*\{{(?P<body>.*?)^\s*\}};",
        source,
        flags=re.DOTALL | re.MULTILINE,
    )
    return match.group("body") if match else ""


def extract_web_base_routes(source: str) -> set[str]:
    """Return literal route keys from the baseSettingsViews object."""
    body = _object_body(source, "export const baseSettingsViews")
    routes: set[str] = set()
    for line in body.splitlines():
        match = re.match(r'^\s*(?:"([^"]+)"|([a-zA-Z0-9_-]+))\s*:', line)
        if match:
            routes.add(match.group(1) or match.group(2))
    return routes


def extract_swift_string_set(source: str, name: str) -> set[str]:
    match = re.search(
        rf"static let {re.escape(name)}:\s*Set<String>\s*=\s*\[(?P<body>.*?)\]",
        source,
        flags=re.DOTALL,
    )
    if not match:
        return set()
    return set(re.findall(r'"([^"]+)"', match.group("body")))


def audit_route_contract(web_source: str, apple_source: str) -> list[str]:
    """Compare web routes only with native routes declared reachable."""
    web_routes = extract_web_base_routes(web_source)
    native_routes = extract_swift_string_set(apple_source, "nativeRoutes")
    errors: list[str] = []

    if not web_routes:
        errors.append("could not extract web baseSettingsViews routes")
        return errors
    if not native_routes:
        errors.append("could not extract reachable Apple nativeRoutes")
        return errors

    for route in sorted(native_routes - web_routes):
        errors.append(f"stale Apple route not present in web settings: {route}")
    for route in sorted(web_routes - native_routes):
        errors.append(f"missing reachable Apple route: {route}")
    return errors


def audit_swift_source(source: str, *, path: str) -> list[str]:
    """Return deterministic settings-source contract violations."""
    errors: list[str] = []
    for forbidden in FORBIDDEN_CONTROLS:
        if forbidden in source:
            errors.append(f"{path}: forbidden native product control: {forbidden}")
    for endpoint in STALE_ENDPOINTS:
        if endpoint in source:
            errors.append(f"{path}: stale or nonexistent endpoint: {endpoint}")
    if re.search(r"\bprint\s*\(", source):
        errors.append(f"{path}: use NativeDiagnostics instead of print(")
    if "UIApplication.shared.open" in source or "NSWorkspace.shared.open" in source:
        errors.append(f"{path}: browser fallback is forbidden")
    return errors


def audit_privacy_contract(source: str) -> list[str]:
    """Verify privacy settings use real routes and privacy-safe payloads."""
    errors: list[str] = []
    for endpoint in PRIVACY_ENDPOINTS:
        if endpoint not in source:
            errors.append(f"privacy contract missing endpoint: {endpoint}")
    has_period_dictionary = '"period"' in source
    has_typed_period_request = "struct AutoDeleteChatsRequest" in source and "let period: AutoDeletionPeriod" in source
    if not has_period_dictionary and not has_typed_period_request:
        errors.append("privacy contract must send the auto-delete period payload")
    if "/v1/settings/auto-delete-files" in source:
        errors.append("privacy contract references nonexistent file auto-delete endpoint")
    for declaration in (
        "usageDataRetentionYears = 3",
        "complianceLogRetentionYears = 1",
        "invoiceRetentionYears = 10",
    ):
        if declaration not in source:
            errors.append(f"privacy retention contract missing: {declaration}")
    if "NativeClientLogCollector.sanitize" not in source:
        errors.append("privacy diagnostics contract must sanitize forwarded content")
    return errors


def audit_repository_routes() -> list[str]:
    return audit_route_contract(
        WEB_ROUTES_PATH.read_text(encoding="utf-8"),
        APPLE_SETTINGS_VIEW.read_text(encoding="utf-8"),
    )


def audit_repository_source() -> list[str]:
    errors: list[str] = []
    for path in sorted(APPLE_SETTINGS_ROOT.rglob("*.swift")):
        errors.extend(
            audit_swift_source(
                path.read_text(encoding="utf-8", errors="replace"),
                path=path.relative_to(REPO_ROOT).as_posix(),
            )
        )
    return errors


def audit_repository_privacy() -> list[str]:
    source = APPLE_PRIVACY_MODELS.read_text(encoding="utf-8")
    source += APPLE_NATIVE_DIAGNOSTICS.read_text(encoding="utf-8")
    return audit_privacy_contract(source)


def audit_account_security_contract() -> list[str]:
    """Check TASK-9-owned files for native UI and current endpoint contracts."""
    errors: list[str] = []
    combined = ""
    for path in ACCOUNT_SECURITY_FILES:
        display_path = path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else path.name
        if not path.exists():
            errors.append(f"missing account/security source: {display_path}")
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        combined += source
        errors.extend(audit_swift_source(source, path=display_path))
        if "try?" in source:
            errors.append(f"{display_path}: silent try? is forbidden")
        if "UIApplication.shared.open" in source or "NSWorkspace.shared.open" in source:
            errors.append(f"{display_path}: browser fallback is forbidden")
    for endpoint in ACCOUNT_SECURITY_ENDPOINTS:
        if endpoint not in combined:
            errors.append(f"missing account/security endpoint contract: {endpoint}")
    return errors


def _report(errors: list[str], label: str) -> int:
    if errors:
        print(f"Apple settings {label} audit failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Apple settings {label} audit passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check-routes", action="store_true")
    group.add_argument("--check-source", action="store_true")
    args = parser.parse_args()

    if args.check_routes:
        return _report(audit_repository_routes(), "route")
    return _report(audit_repository_source(), "source")


if __name__ == "__main__":
    raise SystemExit(main())
