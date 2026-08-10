// Fixture-backed macOS account/security parity coverage.
// Verifies native entry points without mutating credentials, sessions, chats,
// passkeys, recovery keys, storage, or account state.

import XCTest

@MainActor
final class SettingsMacSecurityParityUITests: XCTestCase {
    func testAccountSecurityEntrypointsUseCustomChrome() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-account-settings-fixture"]
        app.launch()

        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        XCTAssertTrue(app.buttons["settings-account-row"].waitForExistence(timeout: 8))
        app.buttons["settings-account-row"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-account-page"].waitForExistence(timeout: 8))
        XCTAssertFalse(app.tables.firstMatch.exists)
        XCTAssertFalse(app.toolbars.firstMatch.exists)
    }
}
