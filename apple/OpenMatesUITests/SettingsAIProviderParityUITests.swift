// Guest settings provider-family navigation uses public bundled model metadata.
// No credentials, purchases, provider APIs or real account mutations.
import XCTest

@MainActor
final class SettingsAIProviderParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.preferences.exclusive-tier-defaults,ai-model-routing.settings.hierarchy-canonical,ai-model-routing.catalog.capability-recommendation-variants
    func testAuthenticatedTierFixtureSelectsExclusivelyAndModelToggleStaysSeparate() {
        let app = launchAuthenticatedFixture()
        let most = app.buttons["ai-tier-row-most-demanding-modify-button"]
        XCTAssertTrue(most.waitForExistence(timeout: 8))
        XCTAssertTrue(most.isHittable)
        XCTAssertTrue(app.buttons["ai-tier-row-simple-modify-button"].exists)
        XCTAssertTrue(app.buttons["ai-tier-row-complex-modify-button"].exists)
        attachScreenshot("AI authenticated three tier defaults", app: app)
        most.tap()
        let auto = app.descendants(matching: .any)["ai-model-option-auto-toggle"].firstMatch
        XCTAssertTrue(auto.waitForExistence(timeout: 5))
        XCTAssertEqual(auto.value as? String, "On")
        let provider = app.buttons.matching(identifier: "ai-provider-family-card")
            .matching(NSPredicate(format: "value == %@", "openai")).firstMatch
        XCTAssertTrue(provider.isHittable)
        attachScreenshot("AI most demanding tier provider families", app: app)
        provider.tap()
        let first = app.descendants(matching: .any)["ai-model-option-exact-toggle-gpt-5.4"].firstMatch
        let second = app.descendants(matching: .any)["ai-model-option-exact-toggle-gpt-5.5"].firstMatch
        XCTAssertTrue(first.waitForExistence(timeout: 5))
        XCTAssertEqual(first.value as? String, "Off")
        XCTAssertTrue(first.isHittable)
        attachScreenshot("AI tier provider exact models", app: app)
        first.tap()
        expectValue("On", element: first)
        XCTAssertEqual(auto.value as? String, "Off")
        makeHittable(second, app: app)
        second.tap()
        expectValue("On", element: second)
        XCTAssertEqual(first.value as? String, "Off", "Choosing a second exact model replaces the first")
        attachScreenshot("AI tier exclusive model selection", app: app)
        app.buttons["settings-destination-back"].tap()
        app.buttons["settings-destination-back"].tap()
        XCTAssertTrue(most.waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["GPT-5.5"].exists)
        attachScreenshot("AI three tier defaults after model selection", app: app)

        let overviewProvider = app.buttons.matching(identifier: "ai-provider-family-card")
            .matching(NSPredicate(format: "value == %@", "openai")).firstMatch
        makeHittable(overviewProvider, app: app)
        overviewProvider.tap()
        let availability = app.descendants(matching: .any)["provider-model-item-toggle-gpt-5.4"].firstMatch
        XCTAssertTrue(availability.waitForExistence(timeout: 5))
        XCTAssertEqual(availability.value as? String, "On")
        availability.tap()
        expectValue("Off", element: availability)
        XCTAssertFalse(app.descendants(matching: .any)["ai-model-details"].exists, "A model toggle must not open model details")
        app.buttons["settings-destination-back"].tap()
        most.tap()
        provider.tap()
        XCTAssertFalse(first.exists, "Disabled models must leave the tier selection catalog")
        XCTAssertEqual(second.value as? String, "On", "Availability changes must preserve the selected tier default")
    }

    // contract-test: supporting surface=gui.apple assertions=ai-model-routing.preferences.exclusive-tier-defaults
    func testTierSaveFailureFixtureRollsBackToAuto() {
        let app = launchAuthenticatedFixture(failsSaves: true)
        app.buttons["ai-tier-row-most-demanding-modify-button"].tap()
        app.buttons.matching(identifier: "ai-provider-family-card")
            .matching(NSPredicate(format: "value == %@", "openai")).firstMatch.tap()
        let exact = app.descendants(matching: .any)["ai-model-option-exact-toggle-gpt-5.4"].firstMatch
        XCTAssertTrue(exact.waitForExistence(timeout: 5))
        exact.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-ai-error"].waitForExistence(timeout: 5))
        XCTAssertEqual(exact.value as? String, "Off")
        XCTAssertEqual(app.descendants(matching: .any)["ai-model-option-auto-toggle"].firstMatch.value as? String, "On")
    }

    private func launchAuthenticatedFixture(failsSaves: Bool = false) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-authenticated-chat-navigation", "--ui-test-ai-preferences-fixture"]
        if failsSaves { app.launchArguments.append("--ui-test-ai-preferences-save-failure") }
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        let ai = app.descendants(matching: .any)["settings-ai-row"].firstMatch
        XCTAssertTrue(ai.waitForExistence(timeout: 8))
        ai.tap()
        XCTAssertTrue(app.buttons["ai-tier-row-most-demanding-modify-button"].waitForExistence(timeout: 8))
        return app
    }
    private func expectValue(_ value: String, element: XCUIElement) {
        let changed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", value), object: element)
        XCTAssertEqual(XCTWaiter.wait(for: [changed], timeout: 5), .completed)
    }
    private func attachScreenshot(_ name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
    private func makeHittable(_ element: XCUIElement, app: XCUIApplication) {
        let settings = app.scrollViews["ai-settings-scroll"]
        XCTAssertTrue(settings.waitForExistence(timeout: 5))
        XCTAssertTrue(settings.isHittable)
        for _ in 0..<6 where !element.isHittable { settings.swipeUp() }
        XCTAssertTrue(element.isHittable)
    }

    // contract-test: direct surface=gui.apple assertions=settings-ui.navigation.parent-return,settings-ui.parity.web-apple-shell
    func testProviderFamilyOpensItsModelsAndReturnsThroughAIParent() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"]
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        let ai = app.descendants(matching: .any)["settings-ai-row"].firstMatch
        XCTAssertTrue(ai.waitForExistence(timeout: 8))
        XCTAssertTrue(ai.isHittable)
        ai.tap()
        let pricing = app.descendants(matching: .any)["ai-pricing-note"].firstMatch
        XCTAssertTrue(pricing.waitForExistence(timeout: 8))
        let chatGPT = app.buttons.matching(identifier: "ai-provider-family-card")
            .matching(NSPredicate(format: "value == %@", "openai")).firstMatch
        XCTAssertTrue(chatGPT.waitForExistence(timeout: 5))
        XCTAssertTrue(chatGPT.label.contains("ChatGPT"))
        XCTAssertTrue(chatGPT.label.contains("OpenAI"))
        XCTAssertTrue(chatGPT.isHittable)
        XCTAssertFalse(app.descendants(matching: .any)["ai-default-models-group"].exists)
        attachScreenshot("AI guest provider families", app: app)
        chatGPT.tap()
        XCTAssertTrue(app.descendants(matching: .any)["ai-provider-identity"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.buttons["settings-destination-back"].label, "Settings / AI")
        let model = app.buttons.matching(identifier: "provider-model-item").firstMatch
        XCTAssertTrue(model.waitForExistence(timeout: 5))
        XCTAssertTrue(model.isHittable)
        XCTAssertTrue(model.label.contains("GPT"))
        XCTAssertEqual(app.switches.count, 0, "Guest availability is read only")
        attachScreenshot("AI guest provider models", app: app)
        model.tap()
        XCTAssertTrue(app.descendants(matching: .any)["ai-model-details"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["ai-model-summary-section"].exists)
        let modelShot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        modelShot.name = "AI model detail reached from provider family"
        modelShot.lifetime = .keepAlways
        add(modelShot)
        app.buttons["settings-destination-back"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["ai-provider-identity"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.buttons["settings-destination-back"].label, "Settings / AI")
        app.buttons["settings-destination-back"].tap()
        XCTAssertTrue(pricing.waitForExistence(timeout: 5))
        XCTAssertTrue(chatGPT.isHittable)
        app.buttons["settings-destination-back"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-menu"].waitForExistence(timeout: 5))
    }
}
