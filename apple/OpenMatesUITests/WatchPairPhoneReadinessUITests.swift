// Real-account phone readiness for Watch pairing; no inference or auth seeding.
// Specification: specifications/features/auth/specification.yml
// Assertions: auth.login.method-convergence, auth.session.lifecycle
import CryptoKit
import XCTest

@MainActor
final class WatchPairPhoneReadinessUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence,auth.session.lifecycle,sync.surface.semantic-parity
    func testPersonalDevPhoneLoginAndWelcomeSyncReadiness() throws {
        continueAfterFailure = false
        guard RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_WATCH_PHONE_READINESS") == "1",
              let identity = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_PERSONAL_IDENTITY_HASH"),
              let account = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_PERSONAL_ACCOUNT_HASH"),
              identity.count == 16, account.count == 16 else {
            throw XCTSkip("Explicit personal DEV readiness opt-in and identity fences required")
        }
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        let normalizedEmail = credentials.email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard hash(normalizedEmail) == identity else {
            throw XCTSkip("Credentials do not match the approved personal identity")
        }
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp(extraArguments: [
            "--ui-test-open-login", "--ui-test-read-only-performance",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"
        ])
        let probe = app.descendants(matching: .any).matching(identifier: "read-only-responsiveness-metrics").firstMatch
        guard probe.waitForExistence(timeout: 30) else { throw XCTSkip("Account and server readiness probe unavailable") }
        guard fields(probe)["server-kind"] == "development" else { throw XCTSkip("Preserved existing server selection; DEV required") }
        if let cached = fields(probe)["account-hash"], cached != "none", cached != account {
            throw XCTSkip("Preserved another authenticated account")
        }
        // Submit the focused production SecureField once via Return. The
        // authenticated editor, approved account/server and real sync markers
        // below remain the readiness proof when pre-submit AX snapshots vanish.
        RealAccountUITestSupport.logIn(app: app, credentials: credentials, submitPasswordUsingKeyboard: true)
        let verified = NSPredicate { _, _ in
            self.fields(probe)["account-hash"] == account && self.fields(probe)["server-kind"] == "development"
        }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: verified, object: nil)], timeout: 30), .completed,
                       "Normal authentication must confirm the approved DEV account")
        XCTAssertTrue(syncMarker(app).waitForExistence(timeout: 45))
        // Existing resume route preserves the current draft.
        app.terminate()
        app.launchArguments.removeAll { $0 == "--ui-test-open-login" }
        app.launchArguments.append("--ui-test-start-new-chat")
        app.launch()
        XCTAssertTrue(syncMarker(app).waitForExistence(timeout: 45))
        XCTAssertTrue(app.descendants(matching: .any).matching(identifier: "chat-workspace-welcome").firstMatch.waitForExistence(timeout: 20))
        XCTAssertEqual(fields(probe)["account-hash"], account)
        XCTAssertEqual(fields(probe)["server-kind"], "development")
    }

    private func hash(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).prefix(8).map { String(format: "%02x", $0) }.joined()
    }
    private func fields(_ probe: XCUIElement) -> [String: String] {
        Dictionary(probe.label.split(separator: ";").compactMap {
            let parts = $0.split(separator: "=", maxSplits: 1)
            return parts.count == 2 ? (String(parts[0]), String(parts[1])) : nil
        }, uniquingKeysWith: { _, latest in latest })
    }
    private func syncMarker(_ app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "identifier == %@ AND value == %@", "chat-sync-complete", "true")).firstMatch
    }
}
