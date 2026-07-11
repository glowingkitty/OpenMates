"""Regression tests for deterministic Apple settings parity audits.

These fixtures keep route coverage honest: only reachable native routes count,
planned declarations do not. Source checks also reject stock product controls
and endpoint strings already known to be incompatible with the backend.
"""

import re
from pathlib import Path

from scripts import apple_settings_parity_audit


REPO_ROOT = Path(__file__).resolve().parents[2]
BILLING_VIEW = REPO_ROOT / "apple/OpenMates/Sources/Features/Settings/Views/SettingsBillingView.swift"
STORE_MANAGER = REPO_ROOT / "apple/OpenMates/Sources/Core/StoreKit/StoreManager.swift"
SETTINGS_SUBPAGES = REPO_ROOT / "apple/OpenMates/Sources/Features/Settings/Views/SettingsSubPages.swift"
SETTINGS_VIEW = REPO_ROOT / "apple/OpenMates/Sources/Features/Settings/Views/SettingsView.swift"
AI_VIEW = REPO_ROOT / "apple/OpenMates/Sources/Features/Settings/Views/SettingsAIFull.swift"
DEVELOPER_VIEW = REPO_ROOT / "apple/OpenMates/Sources/Features/Settings/Views/SettingsDeveloperFull.swift"
DEVICES_VIEW = REPO_ROOT / "apple/OpenMates/Sources/Features/Settings/Views/SettingsDevicesView.swift"
NEWSLETTER_VIEW = REPO_ROOT / "apple/OpenMates/Sources/Features/Settings/Views/NewsletterSettingsView.swift"
PROJECTS_VIEW = REPO_ROOT / "apple/OpenMates/Sources/Features/Settings/Views/SettingsProjectsView.swift"
LOGS_VIEW = REPO_ROOT / "apple/OpenMates/Sources/Features/Settings/Views/SettingsLogsView.swift"
SERVER_VIEW = REPO_ROOT / "apple/OpenMates/Sources/Features/Settings/Views/SettingsServerView.swift"


WEB_ROUTES = """
export const baseSettingsViews: Record<string, Component<any>> = {
  apps: SettingsAppStore,
  "apps/all": SettingsAllApps,
  privacy: SettingsPrivacy,
  "learning-mode/setup": SettingsLearningModeSetup,
};
"""


def test_extract_web_base_routes_preserves_nested_paths() -> None:
    assert apple_settings_parity_audit.extract_web_base_routes(WEB_ROUTES) == {
        "apps",
        "apps/all",
        "learning-mode/setup",
        "privacy",
    }


def test_planned_and_stale_routes_do_not_satisfy_coverage() -> None:
    apple_source = """
    static let nativeRoutes: Set<String> = ["app_store", "privacy"]
    static let nativeEquivalentOrPlannedRoutes: Set<String> = [
        "app_store/all", "learning-mode/setup"
    ]
    """

    errors = apple_settings_parity_audit.audit_route_contract(WEB_ROUTES, apple_source)

    assert "stale Apple route not present in web settings: app_store" in errors
    assert "missing reachable Apple route: apps" in errors
    assert "missing reachable Apple route: apps/all" in errors
    assert "missing reachable Apple route: learning-mode/setup" in errors


def test_matching_reachable_routes_pass() -> None:
    apple_source = """
    static let nativeRoutes: Set<String> = [
        "apps", "apps/all", "privacy", "learning-mode/setup"
    ]
    """

    assert apple_settings_parity_audit.audit_route_contract(WEB_ROUTES, apple_source) == []


def test_repository_route_inventory_matches_current_web_routes() -> None:
    assert apple_settings_parity_audit.audit_repository_routes() == []


def test_forbidden_settings_controls_and_stale_endpoints_are_rejected() -> None:
    errors = apple_settings_parity_audit.audit_swift_source(
        """
        List { Text("Memories") }
        let endpoint = "/v1/settings/memories"
        print("settings request failed")
        """,
        path="SettingsMemoriesFull.swift",
    )

    assert "SettingsMemoriesFull.swift: forbidden native product control: List {" in errors
    assert "SettingsMemoriesFull.swift: stale or nonexistent endpoint: /v1/settings/memories" in errors
    assert "SettingsMemoriesFull.swift: use NativeDiagnostics instead of print(" in errors


def test_openmates_primitives_and_current_endpoints_pass_source_audit() -> None:
    source = """
    ScrollView { LazyVStack { OMSettingsRow(title: AppStrings.settingsApps) {} } }
    let endpoint = "/v1/learning-mode"
    NativeDiagnostics.error("Settings request failed", category: "settings")
    """

    assert apple_settings_parity_audit.audit_swift_source(source, path="SettingsView.swift") == []


def test_account_security_task_uses_native_contracts() -> None:
    assert apple_settings_parity_audit.audit_account_security_contract() == []


def test_account_security_audit_rejects_browser_and_silent_fallbacks(tmp_path, monkeypatch) -> None:
    unsafe = tmp_path / "Unsafe.swift"
    unsafe.write_text(
        'Form { Text("Security") }\ntry? await request()\nUIApplication.shared.open(url)\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(apple_settings_parity_audit, "ACCOUNT_SECURITY_FILES", (unsafe,))
    monkeypatch.setattr(apple_settings_parity_audit, "ACCOUNT_SECURITY_ENDPOINTS", ())

    errors = apple_settings_parity_audit.audit_account_security_contract()

    assert any("forbidden native product control: Form {" in error for error in errors)
    assert any("silent try? is forbidden" in error for error in errors)
    assert any("browser fallback is forbidden" in error for error in errors)




def test_privacy_contract_requires_real_routes_payloads_and_retention_rules() -> None:
    source = """
    static let autoDeleteChatsPath = "/v1/settings/auto-delete-chats"
    static let connectedAccountsPath = "/v1/connected-accounts"
    static let debugSessionPath = "/v1/settings/debug-session"
    static let debugLogsPath = "/v1/settings/debug-logs"
    let body = ["period": period.rawValue]
    static let usageDataRetentionYears = 3
    static let complianceLogRetentionYears = 1
    static let invoiceRetentionYears = 10
    NativeClientLogCollector.sanitize(message)
    """

    assert apple_settings_parity_audit.audit_privacy_contract(source) == []


def test_privacy_contract_rejects_fake_file_route_and_unsanitized_diagnostics() -> None:
    source = """
    static let autoDeleteFilesPath = "/v1/settings/auto-delete-files"
    let body = ["days": 90]
    """

    errors = apple_settings_parity_audit.audit_privacy_contract(source)

    assert "privacy contract missing endpoint: /v1/settings/auto-delete-chats" in errors
    assert "privacy contract must send the auto-delete period payload" in errors
    assert "privacy contract references nonexistent file auto-delete endpoint" in errors
    assert "privacy diagnostics contract must sanitize forwarded content" in errors


def test_repository_privacy_contract_matches_backend_and_retention_rules() -> None:
    assert apple_settings_parity_audit.audit_repository_privacy() == []


ROOT = Path(__file__).resolve().parents[2]
MEMORIES_VIEW = ROOT / "apple/OpenMates/Sources/Features/Settings/Views/SettingsMemoriesFull.swift"
MATES_VIEW = ROOT / "apple/OpenMates/Sources/Features/Settings/Views/SettingsMatesView.swift"
MATES_METADATA = ROOT / "frontend/packages/ui/src/data/matesMetadata.ts"


def test_memories_use_encrypted_sdk_contract_and_custom_product_ui() -> None:
    source = MEMORIES_VIEW.read_text()

    assert "/v1/sdk/memories" in source
    assert "CryptoManager.shared" in source
    assert "wsSyncEvent" in source
    assert "/v1/settings/memories" not in source
    assert not apple_settings_parity_audit.audit_swift_source(
        source,
        path=MEMORIES_VIEW.name,
    )


def test_mates_use_canonical_metadata_and_native_composer_handoff() -> None:
    source = MATES_VIEW.read_text()
    web_source = MATES_METADATA.read_text()
    web_ids = re.findall(r'^\s+id: "([a-z_]+)",$', web_source, flags=re.MULTILINE)
    native_ids = re.findall(r'id: "([a-z_]+)",\s*nameKey:', source)

    assert native_ids == web_ids
    assert "@mate:\\(id)" in source
    assert "NotificationCenter.default.post" in source
    assert "/v1/mates" not in source
    assert "UIApplication.shared.open" not in source
    assert "NSWorkspace.shared.open" not in source
    assert not apple_settings_parity_audit.audit_swift_source(source, path=MATES_VIEW.name)


def test_billing_uses_current_backend_contracts() -> None:
    source = BILLING_VIEW.read_text(encoding="utf-8")
    subpages_source = SETTINGS_SUBPAGES.read_text(encoding="utf-8")

    assert apple_settings_parity_audit.audit_swift_source(
        source,
        path="SettingsBillingView.swift",
    ) == []

    for endpoint in (
        "/v1/settings/billing",
        "/v1/settings/usage/daily-overview",
        "/v1/settings/usage/summaries",
        "/v1/settings/usage/details",
        "/v1/settings/usage/export",
        "/v1/settings/auto-topup/low-balance",
        "/v1/payments/invoices",
        "/v1/payments/invoices/",
        "/v1/payments/redeem-gift-card",
        "/v1/payments/create-gift-card-bank-transfer-order",
        "/v1/payments/create-support-bank-transfer-order",
    ):
        assert endpoint in source

    for stale_endpoint in (
        'path: "/v1/settings/usage"',
        'path: "/v1/settings/billing/auto-topup"',
        'path: "/v1/settings/billing/invoices"',
    ):
        assert stale_endpoint not in source

    assert "InvoicesListResponse" in source
    assert "BillingOverviewResponse" in source
    assert 'path: "/v1/settings/usage"' not in subpages_source
    assert "BillingUsageView()" in subpages_source
    assert "UIApplication.shared.open(downloadURL)" not in source
    assert "NSWorkspace.shared.open(downloadURL)" not in source


def test_storekit_finishes_only_after_backend_fulfillment_succeeds() -> None:
    source = STORE_MANAGER.read_text(encoding="utf-8")

    assert "func fulfillOnBackend" in source
    assert "async throws" in source
    assert "try await fulfillOnBackend" in source
    assert "AppStrings.billingFulfillmentDelayed" in source

    fulfillment_catch = source.find("Backend fulfillment error")
    assert fulfillment_catch == -1, "fulfillment must throw instead of swallowing backend errors"

    for block_start in (
        source.index("case .success(let verification):"),
        source.index("for await result in Transaction.unfinished"),
        source.index("for await result in Transaction.updates"),
    ):
        finish = source.index("transaction.finish()", block_start)
        fulfillment = source.index("fulfillOnBackend", block_start)
        assert fulfillment < finish


def test_other_settings_use_current_native_contracts() -> None:
    settings_source = SETTINGS_VIEW.read_text(encoding="utf-8")
    ai_source = AI_VIEW.read_text(encoding="utf-8")
    developer_source = DEVELOPER_VIEW.read_text(encoding="utf-8")
    devices_source = DEVICES_VIEW.read_text(encoding="utf-8")
    newsletter_source = NEWSLETTER_VIEW.read_text(encoding="utf-8")
    projects_source = PROJECTS_VIEW.read_text(encoding="utf-8")

    assert "case projects" in settings_source
    assert "SettingsProjectsView()" in settings_source
    assert '"projects"' in settings_source
    assert '"apps"' in settings_source
    assert '"app_store"' not in apple_settings_parity_audit.extract_swift_string_set(settings_source, "nativeRoutes")

    assert 'path: "/v1/settings/ai-model-defaults"' in ai_source
    assert "/v1/settings/ai-models" not in ai_source
    assert "/v1/settings/ai-providers/" not in ai_source
    assert "default_ai_model_simple" in ai_source
    assert "default_ai_model_complex" in ai_source

    assert 'path: "/v1/settings/api-keys"' in developer_source
    assert 'path: "/v1/webhooks"' in developer_source
    assert 'path: "/v1/settings/api-key-devices"' in devices_source
    assert "UIApplication.shared.open" not in developer_source
    assert "NSWorkspace.shared.open" not in developer_source

    for endpoint in (
        "/v1/newsletter/subscribe",
        "/v1/newsletter/categories",
    ):
        assert endpoint in newsletter_source
    assert "/v1/settings/newsletter" not in newsletter_source

    for endpoint in (
        "/v1/projects",
        "/sources",
        "/settings",
    ):
        assert endpoint in projects_source


def test_admin_settings_use_current_routes_and_custom_product_ui() -> None:
    logs_source = LOGS_VIEW.read_text(encoding="utf-8")
    server_source = SERVER_VIEW.read_text(encoding="utf-8")

    assert 'path: "/v1/admin/debug/logs?limit=200"' in logs_source
    assert "/v1/admin/logs" not in logs_source
    for endpoint in (
        "/v1/settings/software_update/check",
        "/v1/settings/software_update/versions",
        "/v1/settings/software_update/config",
        "/v1/settings/software_update/install",
        "/v1/settings/software_update/install_status",
        "/v1/admin/server-stats",
        "/v1/admin/generate-gift-cards",
        "/v1/admin/gift-cards",
        "/v1/admin/free-testing-credits-budget",
        "/v1/admin/anonymous-free-usage-budget",
        "/v1/admin/test-results",
    ):
        assert endpoint in server_source

    for path, source in ((LOGS_VIEW, logs_source), (SERVER_VIEW, server_source)):
        assert apple_settings_parity_audit.audit_swift_source(source, path=path.name) == []
