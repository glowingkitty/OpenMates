// Guest-safe native Mates list/detail/composer handoff parity coverage.
// Verifies shared artwork, prompt expansion, and native new-chat transition.
// The test must never invoke Safari or an external browser destination.
// It uses canonical public mate metadata and no private account state.

import XCTest

@MainActor
final class SettingsMatesParityUITests: XCTestCase {
    func testMateDetailsPromptAndNativeStartChatHandoff() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"]
        app.launch()

        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        let matesRow = app.descendants(matching: .any)["settings-mates-row"]
        XCTAssertTrue(matesRow.waitForExistence(timeout: 8))
        matesRow.tap()

        XCTAssertTrue(app.descendants(matching: .any)["settings-mates-page"].waitForExistence(timeout: 8))
        XCTAssertFalse(app.tables.firstMatch.exists)
        let mate = app.descendants(matching: .any)["settings-mate-software_development"]
        XCTAssertTrue(mate.waitForExistence(timeout: 5))
        mate.tap()

        XCTAssertTrue(app.descendants(matching: .any)["settings-mate-detail"].waitForExistence(timeout: 5))
        let promptToggle = app.descendants(matching: .any)["settings-mate-prompt-toggle"]
        scrollToHittable(promptToggle, in: app)
        promptToggle.tap()
        XCTAssertTrue(app.descendants(matching: .any)["mate-system-prompt"].waitForExistence(timeout: 5))
        let startChat = app.descendants(matching: .any)["settings-mate-start-chat"]
        scrollToHittable(startChat, in: app)
        startChat.tap()
        XCTAssertTrue(app.descendants(matching: .any)["message-composer"].waitForExistence(timeout: 8))
        XCTAssertNotEqual(XCUIApplication(bundleIdentifier: "com.apple.mobilesafari").state, .runningForeground)
    }

    private func scrollToHittable(_ element: XCUIElement, in app: XCUIApplication) {
        for _ in 0..<6 where !element.isHittable {
            app.scrollViews.lastMatch.swipeUp()
        }
        XCTAssertTrue(element.isHittable)
    }
}
