// Guest-safe native Memories parity coverage using deterministic public examples.
// Verifies custom product UI, category/detail navigation, and read-only guest state.
// Authenticated encrypted CRUD remains a reserved-account integration check.
// No credentials, encryption keys, or private memory values are used here.

import XCTest

@MainActor
final class SettingsMemoriesParityUITests: XCTestCase {
    func testGuestMemoryExamplesRenderWithoutStockTableChrome() {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-account-settings-fixture",
            "--ui-test-memory-fixture",
        ]
        app.launch()

        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-memories-row"].waitForExistence(timeout: 8))
        app.descendants(matching: .any)["settings-memories-row"].tap()

        XCTAssertTrue(app.descendants(matching: .any)["settings-memories-page"].waitForExistence(timeout: 8))
        XCTAssertFalse(app.tables.firstMatch.exists)
        let category = app.descendants(matching: .any)["settings-memory-category-travel-preferred_activities"]
        XCTAssertTrue(category.waitForExistence(timeout: 5))
        category.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-memory-entry-example-travel-preferred-activities-0"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.descendants(matching: .any)["settings-memory-add"].exists)
    }
}
