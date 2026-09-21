import XCTest
@MainActor final class ModelFixtureUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.composer.mention-to-exact-selection,ai-model-routing.composer.responsive-actions
    func testActualProviderModelToggleRoutesDraftAndAutoClearsPrefix() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "composer", "--dev-preview-variant", "model", "-AppleLanguages", "(en)"]
        app.launch()
        let selector = app.buttons["composer-model-selector"]
        XCTAssertTrue(selector.waitForExistence(timeout: 10)); XCTAssertTrue(selector.isEnabled); selector.tap()
        let provider = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "composer-model-provider-")).firstMatch
        XCTAssertTrue(provider.waitForExistence(timeout: 5)); provider.tap()
        let toggle = app.switches.matching(NSPredicate(format: "identifier BEGINSWITH %@", "composer-model-toggle-")).firstMatch
        XCTAssertTrue(toggle.waitForExistence(timeout: 5)); toggle.tap()
        let routed = app.staticTexts["dev-model-routed-text"]
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "label BEGINSWITH %@", "@ai-model:"), object: routed)], timeout: 5), .completed)
        selector.tap()
        app.buttons["composer-model-back"].tap()
        app.buttons["composer-model-auto"].tap()
        XCTAssertEqual(app.staticTexts["dev-model-selection"].label, "auto")
        XCTAssertEqual(app.staticTexts["dev-model-routed-text"].label, "Fixture request")
    }
}
