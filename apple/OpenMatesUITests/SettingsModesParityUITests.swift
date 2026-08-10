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

    func testGuestLearningModeCanBeEnabledAndDisabledForCurrentSession() {
        let app = launchSettingsFixture()

        let learningRow = app.descendants(matching: .any)["learning-mode-toggle-wrapper"]
        XCTAssertTrue(learningRow.waitForExistence(timeout: 5))
        tapToggle("learning-mode-toggle-wrapper", in: app)

        XCTAssertTrue(app.descendants(matching: .any)["settings-learning-mode-page"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-age-group-dropdown"].exists)
        let enable = app.buttons["learning-mode-enable-button"].firstMatch
        XCTAssertTrue(enable.exists && enable.isHittable)
        enable.tap()

        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-status-enabled"].firstMatch.waitForExistence(timeout: 5))
        app.buttons["learning-mode-disable-button"].firstMatch.tap()
        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-status-disabled"].firstMatch.waitForExistence(timeout: 5))
    }

    func testAccountLearningModeRendersPasscodeProtectedManagement() {
        let app = launchSettingsFixture(extraArguments: ["--ui-test-account-settings-fixture"])
        let learningRow = app.descendants(matching: .any)["learning-mode-toggle-wrapper"]
        XCTAssertTrue(learningRow.waitForExistence(timeout: 5))
        tapToggle("learning-mode-toggle-wrapper", in: app)

        XCTAssertTrue(app.secureTextFields["learning-mode-passcode-input"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["learning-mode-enable-button"].firstMatch.waitForExistence(timeout: 5))
    }

    func testIncognitoFirstActivationUsesExplainerAndHandledActivationEvent() {
        let app = launchSettingsFixture(extraArguments: ["--ui-test-account-settings-fixture", "--ui-test-reset-incognito-explainer"])

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

    private func launchSettingsFixture(extraArguments: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"] + extraArguments
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-menu"].waitForExistence(timeout: 8))
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
