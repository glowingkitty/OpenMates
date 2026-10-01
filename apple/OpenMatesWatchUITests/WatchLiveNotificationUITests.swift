// Actual DEV pairing and completion delivery. No fixture or push injection.
// A host browser approves the short URL through the personal DEV account.
import Foundation
import XCTest

final class WatchLiveNotificationUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-notifications.registration.lifecycle,apple-notifications.action.routing-coherent,apple-notifications.payload.privacy-safe
    func testPersonalDevPairingAndBackgroundCompletionNotification() throws {
        let configURL = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent(".openmates-live-test-account.env")
        let config = (try? String(contentsOf: configURL, encoding: .utf8)) ?? ""
        let prefix = "OPENMATES_WATCH_LIVE_PAIR_REQUEST_PATH="
        guard let line = config.split(separator: "\n").first(where: { $0.hasPrefix(prefix) }) else {
            throw XCTSkip("Explicit personal DEV Watch pairing bridge is unavailable")
        }
        let pairURLFile = URL(fileURLWithPath: String(line.dropFirst(prefix.count)))
        let pinFile = pairURLFile.appendingPathExtension("pin")
        let registrationFile = pairURLFile.appendingPathExtension("registered")
        let acceptanceFile = pairURLFile.appendingPathExtension("accepted")
        defer {
            try? FileManager.default.removeItem(at: pairURLFile)
            try? FileManager.default.removeItem(at: pinFile)
            try? FileManager.default.removeItem(at: registrationFile)
            try? FileManager.default.removeItem(at: acceptanceFile)
        }
        let app = XCUIApplication(bundleIdentifier: "org.openmates.app.watch")
        app.launchArguments = [] // Production push setup must remain enabled.
        addUIInterruptionMonitor(withDescription: "Watch notification permission") { alert in
            let allow = alert.buttons["Allow"]
            guard allow.exists else { return false }
            allow.tap()
            return true
        }
        app.launch()
        let hubReady = NSPredicate { _, _ in
            app.buttons["watch-hub-select-chat"].exists || app.buttons["watch-hub-section-selector"].exists
        }
        let authenticationReady = NSPredicate { _, _ in
            hubReady.evaluate(with: nil) || app.staticTexts["watch-pair-url"].exists ||
                app.buttons["watch-pair-login-without-iphone-button"].exists ||
                app.buttons["watch-pair-self-host-button"].exists
        }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: authenticationReady, object: nil)], timeout: 30), .completed)
        let alreadyPaired = hubReady.evaluate(with: nil)
        // The host may reuse only the same Simulator/account it has just
        // approved through the production DEV pairing flow. This setting
        // neither seeds credentials nor changes app authentication.
        if alreadyPaired && !config.contains("OPENMATES_WATCH_LIVE_REUSE_PAIRED_ACCOUNT=1") {
            throw XCTSkip("Host confirmation of the cached personal DEV Watch account is required")
        }
        if !alreadyPaired {
            XCTAssertTrue(app.descendants(matching: .any)["watch-root"].firstMatch.waitForExistence(timeout: 30))
            let fallback = app.buttons["watch-pair-login-without-iphone-button"]
            if fallback.exists { fallback.tap() }
            let selfHost = app.buttons["watch-pair-self-host-button"]
            if selfHost.waitForExistence(timeout: 5) {
                selfHost.tap()
                app.buttons["watch-pair-self-host-keyboard"].tap()
                let domain = app.textFields["watch-pair-self-host-input"]
                XCTAssertTrue(domain.waitForExistence(timeout: 10))
                enterWatchText("app.dev.openmates.org", in: domain, app: app)
                let connect = app.buttons["watch-pair-self-host-connect-button"]
                if !connect.isHittable { app.swipeUp() }
                connect.tap()
            }
            let shortURL = app.staticTexts["watch-pair-url"]
            XCTAssertTrue(shortURL.waitForExistence(timeout: 30))
            let urlText = "https://" + shortURL.label.filter { !$0.isWhitespace }
            let url = try XCTUnwrap(URL(string: urlText))
            XCTAssertEqual(url.host, "app.dev.openmates.org", "Never approve a production Watch login in this test")
            XCTAssertTrue(url.fragment?.hasPrefix("pair=") == true)
            try Data(urlText.utf8).write(to: pairURLFile, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: pairURLFile.path)
            let pinAvailable = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                FileManager.default.fileExists(atPath: pinFile.path)
            }, object: nil)
            XCTAssertEqual(XCTWaiter.wait(for: [pinAvailable], timeout: 300), .completed,
                "The personal DEV browser must approve this real Watch login")
            let pin = try String(contentsOf: pinFile, encoding: .utf8).filter { !$0.isWhitespace }
            XCTAssertEqual(pin.count, 6)
            let pinKeyboard = app.buttons["watch-pair-pin-keyboard"]
            XCTAssertTrue(pinKeyboard.waitForExistence(timeout: 30))
            pinKeyboard.tap()
            let pinInput = app.textFields["watch-pair-pin-input"]
            XCTAssertTrue(pinInput.waitForExistence(timeout: 10))
            // Enter the browser-issued PIN into the production PAKE flow. The
            // bridge supplies no session, token, key, or authentication bypass.
            enterWatchText(pin, in: pinInput, app: app)
            XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: hubReady, object: nil)], timeout: 90), .completed,
                "Production Watch PAKE pairing must finish")
        }
        // This real control also gives the OS permission interruption a chance
        // to present. It does not create or mutate a chat.
        let selector = app.buttons["watch-hub-section-selector"]
        let chat = app.buttons["watch-hub-select-chat"]
        if !chat.exists {
            XCTAssertTrue(selector.waitForExistence(timeout: 15))
            selector.tap()
        }
        if chat.waitForExistence(timeout: 5) { chat.tap() }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            FileManager.default.fileExists(atPath: registrationFile.path)
        }, object: nil)], timeout: 60), .completed,
            "Host must observe actual Watch backend registration acknowledgement before inference")
        let newChat = app.buttons["watch-hub-new"].exists ? app.buttons["watch-hub-new"] : app.buttons["watch-new-chat-button"]
        XCTAssertTrue(newChat.waitForExistence(timeout: 20))
        newChat.tap()
        let editor = app.textFields["watch-message-input"]
        XCTAssertTrue(editor.waitForExistence(timeout: 15))
        let existing = editor.value as? String
        XCTAssertTrue(existing == "" || existing == editor.placeholderValue, "Preserve unrelated drafts")
        let responseMarker = "WATCH" + UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(10)
        enterWatchText("For a disposable notification test, briefly explain five steps for organizing a desk. End with \(responseMarker) completed.", in: editor, app: app)
        let send = app.buttons["watch-message-send"]
        if !send.isHittable { app.swipeUp() }
        XCTAssertTrue(send.isEnabled)
        send.tap()
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            FileManager.default.fileExists(atPath: acceptanceFile.path)
        }, object: nil)], timeout: 30), .completed,
            "Host must observe actual server inference acceptance before backgrounding")
        XCUIDevice.shared.press(.home)
        let carousel = XCUIApplication(bundleIdentifier: "com.apple.Carousel")
        let notification = carousel.staticTexts["New message received"]
        XCTAssertTrue(notification.waitForExistence(timeout: 120), "Expected actual DEV completion delivery on Watch, without injection")
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        shot.name = "Actual Watch DEV completion notification"
        shot.lifetime = .keepAlways
        add(shot)
        notification.tap()
        XCTAssertTrue(app.buttons["watch-chat-back"].waitForExistence(timeout: 30))
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "\(responseMarker) completed")).firstMatch.waitForExistence(timeout: 30))
    }

    @MainActor
    private func enterWatchText(_ text: String, in field: XCUIElement, app: XCUIApplication) {
        field.tap()
        // watchOS presents Quickboard's focused TextView above the SwiftUI
        // field. Typing into the underlying field has no keyboard focus.
        let input = app.textViews.matching(NSPredicate(format: "placeholderValue == %@", field.placeholderValue ?? "")).firstMatch
        XCTAssertTrue(input.waitForExistence(timeout: 10))
        input.typeText(text)
        let done = app.buttons["Done"]
        XCTAssertTrue(done.waitForExistence(timeout: 5))
        done.tap()
    }
}
