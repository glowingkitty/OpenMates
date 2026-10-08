// Native settings mode flow UI coverage for deterministic guest/test state.
// Mirrors web Incognito and Learning Mode settings identifiers and verifies
// controls are rendered and clickable without private account credentials.
// Real-account API behavior remains covered by unit contract tests.
// Screenshots and labels contain synthetic fixture state only.

import XCTest

@MainActor
final class SettingsModesParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing,settings-ui.navigation.contextual-availability
    func testGuestLearningSetupCanBeEnabledAndDisabledThroughOwnedRoute() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-app-link-fixture"]
        app.launchEnvironment["UI_TEST_SETTINGS_LINK_PATH"] = "learning-mode/setup"
        app.launch()
        let link = app.descendants(matching: .any)["ui-test-settings-link"]
        XCTAssertTrue(link.waitForExistence(timeout: 15))
        XCTAssertTrue(link.isHittable)
        link.tap()

        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-settings-page"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-age-group-dropdown"].exists)
        let enable = app.buttons["learning-mode-enable-button"].firstMatch
        XCTAssertTrue(enable.exists && enable.isHittable)
        enable.tap()

        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-status-enabled"].firstMatch.waitForExistence(timeout: 5))
        app.buttons["learning-mode-disable-button"].firstMatch.tap()
        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-status-disabled"].firstMatch.waitForExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.navigation.contextual-availability,settings-ui.composition.canonical-and-accessible
    func testAccountLearningModeRendersPasscodeProtectedManagement() {
        let app = launchSettingsFixture(extraArguments: ["--ui-test-account-settings-fixture"])
        let learningRow = app.descendants(matching: .any)["learning-mode-toggle-wrapper"]
        XCTAssertTrue(learningRow.waitForExistence(timeout: 5))
        tapToggle("learning-mode-toggle-wrapper", in: app)

        XCTAssertTrue(app.secureTextFields["learning-mode-passcode-input"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["learning-mode-enable-button"].firstMatch.waitForExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing,message-input.privacy-context
    func testIncognitoFirstActivationUsesExplainerAndHandledActivationEvent() {
        let app = launchSettingsFixture(extraArguments: ["--ui-test-authenticated-chat-navigation", "--ui-test-account-settings-fixture", "--ui-test-reset-incognito-explainer"])

        let row = app.descendants(matching: .any)["incognito-toggle-wrapper"]
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        tapToggle("incognito-toggle-wrapper", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["incognito-info-page"].waitForExistence(timeout: 5))

        let activate = app.buttons["incognito-activate-button"].firstMatch
        scrollToHittable(activate, in: app)
        activate.tap()

        XCTAssertTrue(app.descendants(matching: .any)["incognito-mode-banner"].waitForExistence(timeout: 8))
        XCTAssertFalse(app.descendants(matching: .any)["settings-menu"].exists)

        app.buttons["settings-button"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-menu"].waitForExistence(timeout: 5))
        tapToggle("incognito-toggle-wrapper", in: app)
        tapToggle("incognito-toggle-wrapper", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["settings-menu"].waitForNonExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["incognito-info-page"].waitForNonExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["incognito-mode-banner"].waitForExistence(timeout: 8))
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell,settings-ui.composition.canonical-and-accessible,settings-ui.shell.lifecycle-and-routing
    func testRootQuickActionsAreSingleLineOrderedAndLabelsInvokeTheirActions() {
        let app = launchSettingsFixture(extraArguments: ["--ui-test-authenticated-chat-navigation", "--ui-test-account-settings-fixture", "--ui-test-reset-incognito-explainer"])
        let teams = app.buttons["team-quick-open"].firstMatch
        let incognito = app.buttons["incognito-toggle-wrapper-action"].firstMatch
        let learning = app.buttons["learning-mode-toggle-wrapper-action"].firstMatch
        XCTAssertTrue(teams.waitForExistence(timeout: 5)); XCTAssertTrue(teams.isHittable)
        XCTAssertTrue(incognito.exists && incognito.isHittable)
        XCTAssertTrue(learning.exists && learning.isHittable)
        XCTAssertLessThan(teams.frame.midY, incognito.frame.midY)
        XCTAssertLessThan(incognito.frame.midY, learning.frame.midY)
        XCTAssertTrue(app.buttons["team-quick-context-dropdown"].firstMatch.exists)
        XCTAssertTrue(app.switches["team-quick-toggle"].firstMatch.exists)
        XCTAssertEqual(incognito.label, "Incognito", "Quick action must expose its single title without a status subtitle")
        XCTAssertEqual(learning.label, "Learning", "Quick action must expose its single title without a status subtitle")
        XCTAssertLessThanOrEqual(app.buttons["incognito-toggle-wrapper-action"].firstMatch.staticTexts.count, 1)
        XCTAssertLessThanOrEqual(app.buttons["learning-mode-toggle-wrapper-action"].firstMatch.staticTexts.count, 1)
        learning.tap()
        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-settings-page"].waitForExistence(timeout: 5))
        app.buttons["settings-destination-back"].firstMatch.tap()
        XCTAssertTrue(app.buttons["incognito-toggle-wrapper-action"].firstMatch.waitForExistence(timeout: 5))
        app.buttons["incognito-toggle-wrapper-action"].firstMatch.tap()
        // The workspace wrapper owns the rendered ScrollView's AX identifier.
        // Its real Incognito controls identify this specific explainer surface.
        let explainers = app.scrollViews.containing(.button, identifier: "incognito-activate-button")
        let explainer = explainers.firstMatch
        XCTAssertTrue(explainer.waitForExistence(timeout: 5))
        XCTAssertEqual(explainers.count, 1, "Incognito label must open one real explainer ScrollView")
        XCTAssertTrue(explainer.frame.intersects(app.windows.firstMatch.frame))
        XCTAssertTrue(explainer.staticTexts["Incognito"].firstMatch.isHittable,
                      "The actual explainer title must be visible inside its ScrollView")
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "Root quick-action label invokes Incognito explainer"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func launchSettingsFixture(extraArguments: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"] + extraArguments
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-menu"].waitForExistence(timeout: 8))
        XCTAssertTrue(app.otherElements["workspace-settings"].firstMatch.exists,
                      "Workspace identity must belong to its containing group, preserving destination and control identities")
        return app
    }

    private func tapToggle(_ identifier: String, in app: XCUIApplication) {
        let toggle = app.switches.matching(identifier: identifier).firstMatch
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        XCTAssertTrue(toggle.isHittable)
        toggle.tap()
    }

    private func scrollToHittable(_ element: XCUIElement, in app: XCUIApplication) {
        let identifiedScrollView = app.scrollViews["incognito-info-page"].firstMatch
        for _ in 0..<6 where !element.isHittable {
            if identifiedScrollView.exists {
                identifiedScrollView.swipeUp()
            } else if app.scrollViews.count > 0 {
                app.scrollViews.element(boundBy: app.scrollViews.count - 1).swipeUp()
            }
        }
        XCTAssertTrue(element.exists)
        XCTAssertTrue(element.isHittable)
    }
}
