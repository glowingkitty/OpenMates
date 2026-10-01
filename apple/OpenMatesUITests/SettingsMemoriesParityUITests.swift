// Guest-safe native Memories parity coverage using deterministic public examples.
// Verifies custom product UI, category/detail navigation, and read-only guest state.
// Authenticated encrypted CRUD remains a reserved-account integration check.
// No credentials, encryption keys, or private memory values are used here.

import XCTest

@MainActor
final class SettingsMemoriesParityUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity,settings-ui.navigation.parent-return
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
        capture("memories-guest-hub", app: app)
        category.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-memory-entry-example-travel-preferred-activities-0"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.descendants(matching: .any)["settings-memory-add"].exists)
        XCTAssertFalse(app.buttons["settings-memory-previous-category"].exists)
        let next = app.buttons["settings-memory-next-category"]
        XCTAssertTrue(next.isHittable)
        capture("memories-guest-category", app: app)
        next.tap()
        let previous = app.buttons["settings-memory-previous-category"]
        XCTAssertTrue(previous.waitForExistence(timeout: 5)); XCTAssertTrue(previous.isHittable)
        XCTAssertFalse(app.buttons["settings-memory-next-category"].exists)
        capture("memories-guest-next-sibling", app: app)
        previous.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-memory-entry-example-travel-preferred-activities-0"].waitForExistence(timeout: 5))
        app.descendants(matching: .any)["settings-memory-entry-example-travel-preferred-activities-0"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-memory-detail"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Beach walks"].firstMatch.exists)
        XCTAssertFalse(app.descendants(matching: .any)["settings-memory-edit"].exists)
        XCTAssertFalse(app.descendants(matching: .any)["settings-memory-delete"].exists)
        XCTAssertFalse(app.descendants(matching: .any)["settings-memory-save"].exists)
        capture("memories-guest-detail", app: app)
        let back = app.buttons["settings-destination-back"]
        XCTAssertTrue(back.isHittable); back.tap()
        XCTAssertTrue(app.descendants(matching: .any)["app-settings-memories-category"].waitForExistence(timeout: 5))
        back.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-memories-hub"].waitForExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity,settings-ui.navigation.parent-return
    func testSyntheticTypedEditorValidatesCreatesEditsAndReturnsThroughDetails() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-account-settings-fixture", "--ui-test-memory-editor-fixture"]
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15)); app.buttons["settings-button"].tap()
        let memories = app.descendants(matching: .any)["settings-memories-row"]
        XCTAssertTrue(memories.waitForExistence(timeout: 8)); memories.tap()
        let add = app.buttons["settings-memory-add"]
        XCTAssertTrue(add.waitForExistence(timeout: 8)); XCTAssertTrue(add.isHittable); add.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-memory-editor"].waitForExistence(timeout: 5))
        let save = app.buttons["settings-memory-save"]
        capture("memories-synthetic-editor", app: app)
        save.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-memory-editor-error"].waitForExistence(timeout: 5))
        let name = app.textFields["settings-memory-field-name"]
        XCTAssertTrue(name.isHittable); name.tap(); name.typeText("Synthetic beach walks")
        app.swipeUp(); XCTAssertTrue(save.isEnabled)
        capture("memories-synthetic-create", app: app)
        save.tap()
        XCTAssertTrue(app.descendants(matching: .any)["app-settings-memories-category"].waitForExistence(timeout: 5))
        let row = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "settings-memory-entry-")).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 5)); XCTAssertTrue(row.isHittable); row.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-memory-detail"].waitForExistence(timeout: 5))
        let edit = app.buttons["settings-memory-edit"]
        XCTAssertTrue(edit.isHittable)
        capture("memories-synthetic-created-detail", app: app)
        edit.tap()
        XCTAssertTrue(name.waitForExistence(timeout: 5)); XCTAssertEqual(name.value as? String, "Synthetic beach walks")
        XCTAssertFalse(save.isEnabled)
        capture("memories-synthetic-edit", app: app)
        name.tap(); name.press(forDuration: 1.1)
        let menuSelectAll = app.menuItems["Select All"]
        let selectAll = menuSelectAll.exists ? menuSelectAll : app.buttons["Select All"]
        XCTAssertTrue(selectAll.waitForExistence(timeout: 5), "Native Select All must replace the complete existing memory value")
        selectAll.tap()
        name.typeText("Synthetic beach walks updated")
        XCTAssertEqual(name.value as? String, "Synthetic beach walks updated")
        app.swipeUp(); XCTAssertTrue(save.isEnabled); save.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-memory-detail"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Synthetic beach walks updated"].firstMatch.exists)
        capture("memories-synthetic-updated-detail", app: app)
        app.buttons["settings-destination-back"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["app-settings-memories-category"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.tables.firstMatch.exists)
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
