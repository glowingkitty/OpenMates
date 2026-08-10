// Focused source-contract coverage for Apple Privacy settings parity.
// Verifies backend payloads, retention policy constants, diagnostic preferences,
// connected-account safe summaries, and debug-session response decoding.
// Network and account secrets are replaced with synthetic values in these tests.
// UI interaction coverage lives in SettingsPrivacyParityUITests.

import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class SettingsPrivacyParityTests: XCTestCase {
    func testPrivacyRoutesUseCanonicalBackendContracts() {
        XCTAssertEqual(PrivacyAPIContract.autoDeleteChatsPath, "/v1/settings/auto-delete-chats")
        XCTAssertEqual(PrivacyAPIContract.connectedAccountsPath, "/v1/connected-accounts")
        XCTAssertEqual(PrivacyAPIContract.debugSessionPath, "/v1/settings/debug-session")
        XCTAssertEqual(PrivacyAPIContract.debugLogsPath, "/v1/settings/debug-logs")
        XCTAssertNil(PrivacyAPIContract.autoDeleteFilesPath)
    }

    func testAutoDeletionPeriodEncodesBackendPeriodSchema() throws {
        let data = try JSONEncoder().encode(AutoDeleteChatsRequest(period: .sixMonths))
        let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: String])

        XCTAssertEqual(payload, ["period": "6m"])
        XCTAssertEqual(AutoDeletionPeriod.from(days: 730), .twoYears)
        XCTAssertEqual(AutoDeletionPeriod.from(days: nil), .never)
    }

    func testFixedRetentionPoliciesMatchWebContract() {
        XCTAssertEqual(PrivacyRetentionPolicy.filesDays, 90)
        XCTAssertEqual(PrivacyRetentionPolicy.usageDataRetentionYears, 3)
        XCTAssertEqual(PrivacyRetentionPolicy.complianceLogRetentionYears, 1)
        XCTAssertEqual(PrivacyRetentionPolicy.invoiceRetentionYears, 10)
    }

    func testDiagnosticsPreferencePersistsThroughInjectedStore() {
        let suite = "SettingsPrivacyParityTests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        let preferences = PrivacyDiagnosticsPreferences(defaults: defaults)

        XCTAssertTrue(preferences.stabilityLogsEnabled)
        XCTAssertFalse(preferences.detailedDebugLoggingEnabled)
        preferences.setStabilityLogsEnabled(false)
        preferences.setDetailedDebugLoggingEnabled(true)

        let restored = PrivacyDiagnosticsPreferences(defaults: defaults)
        XCTAssertFalse(restored.stabilityLogsEnabled)
        XCTAssertTrue(restored.detailedDebugLoggingEnabled)
        defaults.removePersistentDomain(forName: suite)
    }

    func testConnectedAccountSummaryExcludesSecretEnvelope() throws {
        let row = ConnectedAccountEncryptedRow(
            id: "fixture-account",
            encryptedProviderType: "encrypted-provider",
            encryptedAccountLabel: "encrypted-label",
            encryptedRefreshTokenBundle: "refresh_token_fixture_secret",
            encryptedCapabilities: "encrypted-capabilities",
            encryptedAppPermissions: "encrypted-permissions",
            encryptedAccountDirectoryHint: nil,
            updatedAt: 0
        )
        let summary = ConnectedAccountSummary(
            id: row.id,
            providerId: "google_calendar",
            appId: "calendar",
            label: "Calendar fixture",
            capabilities: ["read"],
            runtimeModes: [:]
        )

        XCTAssertEqual(summary.label, "Calendar fixture")
        XCTAssertEqual(summary.providerId, "google_calendar")
        XCTAssertEqual(summary.capabilities, ["read"])
        XCTAssertFalse(String(describing: summary).contains("refresh_token"))
    }

    func testDebugSessionResponseUsesSnakeCaseBackendPayload() throws {
        let data = Data(#"{"active":true,"debugging_id":"dbg-abc123","expires_at":"2026-07-12T12:00:00Z","duration":"1h"}"#.utf8)
        let response = try JSONDecoder().decode(PrivacyDebugSession.self, from: data)

        XCTAssertTrue(response.active)
        XCTAssertEqual(response.debuggingId, "dbg-abc123")
        XCTAssertEqual(response.duration, .oneHour)
    }
}
