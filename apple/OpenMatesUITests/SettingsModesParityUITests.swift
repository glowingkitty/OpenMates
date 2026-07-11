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

        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-settings-page"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-age-group-dropdown"].exists)
        let enable = app.descendants(matching: .any)["learning-mode-enable-button"]
        XCTAssertTrue(enable.exists && enable.isHittable)
        enable.tap()

        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-disable-button"].waitForExistence(timeout: 5))
        app.descendants(matching: .any)["learning-mode-disable-button"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-enable-button"].waitForExistence(timeout: 5))
    }

    func testAccountLearningModeRendersPasscodeProtectedManagement() {
        let app = launchSettingsFixture(extraArguments: ["--ui-test-account-settings-fixture"])
        let learningRow = app.descendants(matching: .any)["learning-mode-toggle-wrapper"]
        XCTAssertTrue(learningRow.waitForExistence(timeout: 5))
        tapToggle("learning-mode-toggle-wrapper", in: app)

        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-settings-page"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.secureTextFields["learning-mode-passcode-input"].exists)
        XCTAssertTrue(app.descendants(matching: .any)["learning-mode-enable-button"].exists)
    }

    func testIncognitoFirstActivationUsesExplainerAndHandledActivationEvent() {
        let app = launchSettingsFixture(extraArguments: ["--ui-test-account-settings-fixture", "--ui-test-reset-incognito-explainer"])

        let row = app.descendants(matching: .any)["incognito-toggle-wrapper"]
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        tapToggle("incognito-toggle-wrapper", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["incognito-info-page"].waitForExistence(timeout: 5))

        let activate = app.descendants(matching: .any)["incognito-activate-button"]
        XCTAssertTrue(activate.exists && activate.isHittable)
        activate.tap()

        XCTAssertTrue(app.descendants(matching: .any)["incognito-mode-banner"].waitForExistence(timeout: 8))
        XCTAssertFalse(app.descendants(matching: .any)["settings-menu"].exists)

        app.buttons["settings-button"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-menu"].waitForExistence(timeout: 5))
        tapToggle("incognito-toggle-wrapper", in: app)
        tapToggle("incognito-toggle-wrapper", in: app)
        XCTAssertFalse(app.descendants(matching: .any)["incognito-info-page"].exists)
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
}
