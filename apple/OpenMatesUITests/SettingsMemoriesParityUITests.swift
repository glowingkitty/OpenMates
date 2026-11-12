// Native Settings > Memories coverage without credentials: the core-backed
// list page renders with OpenMates primitives and the app discovery link
// round-trips. Memory document CRUD is proven by SettingsMemoryDocumentsModelTests
// (view model over a fake core store); real-account CRUD stays a reserved check.
// No credentials, encryption keys, or private memory values are used here.

import XCTest

@MainActor
final class SettingsMemoriesParityUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testMemoriesListRendersCoreBackedPageWithoutStockTableChrome() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-account-settings-fixture"]
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15)); app.buttons["settings-button"].tap()
        let memories = app.descendants(matching: .any)["settings-memories-row"]
        XCTAssertTrue(memories.waitForExistence(timeout: 8)); memories.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-memories-page"].waitForExistence(timeout: 8))
        XCTAssertTrue(app.descendants(matching: .any)["settings-memories-hub"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["settings-memories-sources-help"].exists)
        XCTAssertTrue(app.buttons["settings-memory-discover-apps"].isHittable)
        XCTAssertFalse(app.tables.firstMatch.exists)
        capture("memories-list", app: app)
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity,settings-ui.navigation.parent-return
    func testDiscoverAppsOpensFilteredInternalCatalogAndReturnsToMemories() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-account-settings-fixture", "--ui-test-memory-fixture", "--ui-test-app-store-fixture"]
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15)); app.buttons["settings-button"].tap()
        XCTAssertFalse(app.descendants(matching: .any)["settings-apps-row"].exists)
        let memories = app.descendants(matching: .any)["settings-memories-row"]
        XCTAssertTrue(memories.waitForExistence(timeout: 8)); memories.tap()
        let discover = app.buttons["settings-memory-discover-apps"]
        XCTAssertTrue(discover.waitForExistence(timeout: 8)); discover.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-all-apps-page"].waitForExistence(timeout: 8))
        XCTAssertTrue(app.descendants(matching: .any)["settings-all-app-row-weather"].exists)
        XCTAssertFalse(app.descendants(matching: .any)["settings-all-app-row-docs"].exists)
        XCTAssertFalse(app.buttons["settings-all-apps-back"].exists)
        capture("memories-internal-discover-catalog", app: app)
        app.descendants(matching: .any)["settings-all-app-row-weather"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-app-detail-page"].waitForExistence(timeout: 5))
        app.buttons["settings-destination-back"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-all-apps-page"].waitForExistence(timeout: 5))
        app.buttons["settings-destination-back"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-memories-hub"].waitForExistence(timeout: 5))
    }
    private func capture(_ name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

}
