import Foundation
import XCTest
@testable import OpenMates

/// The Apple shell runs the core's connected-account row plan: every field the core names is
/// encrypted or hashed, the refresh-token bundle is never stored in plaintext, and the user hash is added.
final class ConnectedAccountRowPlannerTests: XCTestCase {
    private func planner() -> ConnectedAccountRowPlanner {
        ConnectedAccountRowPlanner(encrypt: { "enc:" + $0 }, userId: { "user-1" })
    }

    private let handoff = ConnectedAccountHandoff(
        providerId: "google_calendar",
        refreshTokenBundleJSON: #"{"refresh_token":"secret-token","scopes":["calendar"]}"#,
        accountHintJSON: #"{"label":"person@example.org","account_ref":"ref-1","scopes":["calendar"]}"#
    )

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testBuildsEncryptedRowFromCorePlan() async throws {
        let row = try await planner().buildRow(accountId: "acct-1", handoff: handoff, capabilities: [])
        XCTAssertEqual(row["id"], "acct-1")
        XCTAssertEqual(row["encrypted_provider_type"], "enc:google_calendar")
        XCTAssertEqual(row["provider_type_hash"], ConnectedAccountRowPlanner.sha256Hex("google_calendar"))
        XCTAssertEqual(row["encrypted_account_label"], "enc:person@example.org")
        XCTAssertEqual(row["encrypted_refresh_token_bundle"], "enc:" + handoff.refreshTokenBundleJSON)
        XCTAssertEqual(row["hashed_user_id"], ConnectedAccountRowPlanner.sha256Hex("user-1"))
        XCTAssertNotNil(row["encrypted_app_permissions"])
        for (field, value) in row where field.hasPrefix("encrypted_") {
            XCTAssertTrue(value.hasPrefix("enc:"), "\(field) must be encrypted")
        }
        XCTAssertFalse(row.values.contains { $0.contains("secret-token") && !$0.hasPrefix("enc:") })
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testRefusesRowWhenEncryptionFails() async {
        let failing = ConnectedAccountRowPlanner(encrypt: { _ in "" }, userId: { "user-1" })
        do {
            _ = try await failing.buildRow(accountId: "acct-1", handoff: handoff, capabilities: [])
            XCTFail("expected an encryption failure")
        } catch let error as ConnectedAccountRowPlanError {
            guard case .encryptionFailed = error else { return XCTFail("unexpected \(error)") }
        } catch {
            XCTFail("unexpected \(error)")
        }
    }
}
