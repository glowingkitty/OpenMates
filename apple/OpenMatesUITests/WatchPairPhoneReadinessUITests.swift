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
            // This explicitly opted-in real-account run retains private startup
            // stages so a readiness failure can be located without another login.
            "--ui-test-expose-chat-ids",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"
        ])
        let probe = app.descendants(matching: .any).matching(identifier: "read-only-responsiveness-metrics").firstMatch
        guard probe.waitForExistence(timeout: 30) else { throw XCTSkip("Account and server readiness probe unavailable") }
        guard fields(probe)["server-kind"] == "development" else { throw XCTSkip("Preserved existing server selection; DEV required") }
        // The same task-owned Simulator also runs isolated auth/navigation
        // fixtures. These exact synthetic identities have no server account;
        // they may proceed through normal login, while every other cached
        // identity remains protected by the existing personal-account fence.
        let fixtureAccounts = Set(["ui-test-chat-navigation-user", "ui-test-window-drafts-user"].map(hash))
        if let cached = fields(probe)["account-hash"], cached != "none", cached != account,
           !fixtureAccounts.contains(cached) {
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

    // Existing running app only: no launch, auth seeding, or Watch request injection.
    // Correlate a returned sessions page with phoneBridge.approve.completed and
    // the paired Watch's authenticated UI before claiming cross-device completion.
    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback,apple-watch.pairing.private-session,auth.session.lifecycle
    func testApproveExistingPersonalDevWatchRequestWithNormalTOTPIfRequired() throws {
        continueAfterFailure = false
        guard RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_WATCH_LIVE_APPROVAL") == "1",
              let identity = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_PERSONAL_IDENTITY_HASH"),
              let account = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_PERSONAL_ACCOUNT_HASH"),
              identity.count == 16, account.count == 16 else {
            throw XCTSkip("Explicit live Watch approval and approved identity fences required")
        }
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        guard hash(credentials.email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()) == identity else {
            throw XCTSkip("Credentials do not match the approved personal identity")
        }
        let app = XCUIApplication()
        guard [.runningForeground, .runningBackground, .runningBackgroundSuspended].contains(app.state) else {
            throw XCTSkip("Preserve the existing app; launch it normally before this test")
        }
        app.activate()
        let probe = app.descendants(matching: .any).matching(identifier: "read-only-responsiveness-metrics").firstMatch
        guard probe.waitForExistence(timeout: 5), fields(probe)["server-kind"] == "development",
              fields(probe)["account-hash"] == account else {
            throw XCTSkip("Existing phone must expose the approved DEV account fence")
        }
        let approval = app.scrollViews["settings-watch-pair-page"]
        let approve = app.buttons["watch-pair-approve-button"]
        guard approval.waitForExistence(timeout: 15), approve.waitForExistence(timeout: 5) else {
            throw XCTSkip("Start the real paired Watch request before running this test")
        }
        for _ in 0..<4 where !approve.isHittable { approval.swipeUp() }
        guard approve.isEnabled, approve.isHittable else {
            throw XCTSkip("Pending Watch approval is not actionable")
        }
        approve.tap()
        let otp = app.textFields["watch-pair-step-up-code"]
        let password = app.secureTextFields["watch-pair-step-up-password"]
        let email = app.textFields["watch-pair-step-up-email-code"]
        let sessions = app.descendants(matching: .any).matching(identifier: "settings-connected-devices-content").firstMatch
        let nextState = NSPredicate { _, _ in otp.exists || password.exists || email.exists || (sessions.exists && !approval.exists) }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: nextState, object: nil)], timeout: 30), .completed,
                       "Watch approval must expose normal verification or return to connected devices")
        if otp.exists {
            // English normal UI is required; the running app is not relaunched
            // just to change its language or discard the incoming request.
            let allow = approval.buttons.matching(NSPredicate(format: "label == %@", "Allow")).firstMatch
            guard allow.waitForExistence(timeout: 5) else {
                throw XCTSkip("Normal TOTP verification action unavailable in the running app language")
            }
            try RealAccountUITestSupport.submitCurrentWatchPairTOTP(app: app,
                credentials: credentials, field: otp, submit: allow)
        } else if password.exists || email.exists {
            throw XCTSkip("This candidate only completes the account's normal TOTP step-up")
        }
        let returned = NSPredicate { _, _ in sessions.exists && !approval.exists && !otp.exists }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: returned, object: nil)], timeout: 90), .completed,
                       "Phone approval must return to normal connected devices")
        XCTAssertEqual(fields(probe)["account-hash"], account)
        XCTAssertEqual(fields(probe)["server-kind"], "development")
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "Real existing DEV phone returns to connected devices after Watch approval"
        screenshot.lifetime = .keepAlways
        add(screenshot)
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
