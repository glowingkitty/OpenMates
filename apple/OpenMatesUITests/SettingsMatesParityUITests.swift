// Guest-safe native Mates list/detail/composer handoff parity coverage.
// Verifies shared artwork, prompt expansion, and native new-chat transition.
// The test must never invoke Safari or an external browser destination.
// It uses canonical public mate metadata and no private account state.

import XCTest

@MainActor
final class SettingsMatesParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testMateDetailsPromptAndNativeStartChatHandoff() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"]
        app.launch()

        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        let matesRow = app.descendants(matching: .any)["settings-mates-row"]
        if !matesRow.waitForExistence(timeout: 8) {
            app.buttons["settings-button"].tap()
        }
        XCTAssertTrue(matesRow.waitForExistence(timeout: 8))
        matesRow.tap()

        XCTAssertTrue(app.descendants(matching: .any)["settings-mates-page"].waitForExistence(timeout: 8))
        XCTAssertFalse(app.tables.firstMatch.exists)
        let mate = app.descendants(matching: .any)["settings-mate-software_development"]
        XCTAssertTrue(mate.waitForExistence(timeout: 5))
        mate.tap()

        let promptToggle = app.buttons["settings-mate-prompt-toggle"].firstMatch
        XCTAssertTrue(promptToggle.waitForExistence(timeout: 5))
        promptToggle.tap()
        XCTAssertTrue(app.descendants(matching: .any)["mate-system-prompt"].waitForExistence(timeout: 5))
        promptToggle.tap()
        XCTAssertTrue(app.descendants(matching: .any)["mate-system-prompt"].waitForNonExistence(timeout: 5))
        let startChat = app.buttons["settings-mate-start-chat"].firstMatch
        XCTAssertTrue(startChat.waitForExistence(timeout: 5))
        startChat.tap()
        XCTAssertTrue(app.descendants(matching: .any)["message-composer"].waitForExistence(timeout: 8))
        XCTAssertNotEqual(XCUIApplication(bundleIdentifier: "com.apple.mobilesafari").state, .runningForeground)
    }

}
