// macOS settings shell and route coverage for the native desktop app.
// Uses guest and synthetic account/admin fixtures without private account data.
// Verifies top-level destinations, mode entry points, role visibility, custom
// chrome, and light/dark screenshot artifacts through the real macOS target.
// Screenshots are XCTest attachments and contain only deterministic fixtures.

import XCTest

@MainActor
final class SettingsMacShellParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testGuestSettingsShellOpensAndNavigatesOnMacOS() throws {
        let app = launchSettings()

        for destination in guestDestinations {
            openDestination(destination, in: app)
            returnToMenu(in: app)
        }

        attachScreenshot(name: "Guest macOS settings shell")
    }

    func testAuthenticatedSettingsRoutesAndModesOnMacOS() throws {
        let app = launchSettings(arguments: [
            "--ui-test-account-settings-fixture",
            "--ui-test-reset-incognito-explainer",
        ])

        for destination in authenticatedDestinations {
            openDestination(destination, in: app)
            returnToMenu(in: app)
        }

        let learningMode = element("learning-mode-toggle-wrapper", in: app)
        XCTAssertTrue(learningMode.waitForExistence(timeout: 5))
        learningMode.click()
        XCTAssertTrue(element("settings-learning-mode-page", in: app).waitForExistence(timeout: 8))
        returnToMenu(in: app)

        let incognito = element("incognito-toggle-wrapper", in: app)
        XCTAssertTrue(incognito.waitForExistence(timeout: 5))
        incognito.click()
        XCTAssertTrue(element("incognito-info-page", in: app).waitForExistence(timeout: 8))
    }

    func testAdminSettingsRoutesAreFailClosedOnMacOS() throws {
        let accountApp = launchSettings(arguments: ["--ui-test-account-settings-fixture"])
        XCTAssertFalse(element("settings-server-row", in: accountApp).exists)
        XCTAssertFalse(element("settings-logs-row", in: accountApp).exists)
        accountApp.terminate()

        let adminApp = launchSettings(arguments: [
            "--ui-test-account-settings-fixture",
            "--ui-test-admin-settings-fixture",
        ])
        for destination in adminDestinations {
            openDestination(destination, in: adminApp)
            returnToMenu(in: adminApp)
        }
    }

    func testSettingsShellProducesLightAndDarkArtifactsOnMacOS() throws {
        for appearance in ["Light", "Dark"] {
            let app = launchSettings(arguments: ["-AppleInterfaceStyle", appearance])
            XCTAssertTrue(element("settings-ai-row", in: app).isHittable)
            XCTAssertFalse(app.tables.firstMatch.exists)
            attachScreenshot(name: "macOS Settings shell \(appearance.lowercased())")
            app.terminate()
        }
    }

    private var guestDestinations: [(row: String, page: String)] {
        [
            ("settings-pricing-row", "settings-pricing-page"),
            ("settings-ai-row", "settings-ai-page"),
            ("settings-apps-row", "settings-apps-page"),
            ("settings-mates-row", "settings-mates-page"),
            ("settings-interface-row", "settings-interface-page"),
            ("settings-server-connection-row", "settings-server-connection-page"),
            ("settings-newsletter-row", "settings-newsletter-page"),
            ("settings-support-row", "settings-support-page"),
            ("settings-report-issue-row", "settings-report-issue-page"),
        ]
    }

    private var authenticatedDestinations: [(row: String, page: String)] {
        [
            ("settings-memories-row", "settings-memories-page"),
            ("settings-privacy-row", "settings-privacy-page"),
            ("settings-projects-row", "settings-projects-page"),
            ("settings-billing-row", "settings-billing-page"),
            ("settings-notifications-row", "settings-notifications-page"),
            ("settings-shared-row", "settings-shared-page"),
            ("settings-account-row", "settings-account-page"),
            ("settings-developers-row", "settings-developers-page"),
        ]
    }

    private var adminDestinations: [(row: String, page: String)] {
        [
            ("settings-server-row", "settings-server-page"),
            ("settings-logs-row", "settings-logs-page"),
        ]
    }

    private func launchSettings(arguments: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"] + arguments
        app.launch()
        app.activate()

        let settingsButton = app.buttons["settings-button"]
        XCTAssertTrue(settingsButton.waitForExistence(timeout: 15))
        XCTAssertTrue(settingsButton.isHittable)
        settingsButton.click()
        XCTAssertTrue(element("settings-menu", in: app).waitForExistence(timeout: 10))
        XCTAssertFalse(app.tables.firstMatch.exists, "macOS Settings must not render default table chrome")
        return app
    }

    private func openDestination(_ destination: (row: String, page: String), in app: XCUIApplication) {
        let row = element(destination.row, in: app)
        XCTAssertTrue(row.waitForExistence(timeout: 5), "Expected row \(destination.row)")
        XCTAssertTrue(row.isHittable)
        row.click()
        XCTAssertTrue(element(destination.page, in: app).waitForExistence(timeout: 8), "Expected page \(destination.page)")
        XCTAssertTrue(element("settings-destination-back", in: app).waitForExistence(timeout: 3))
        XCTAssertFalse(app.tables.firstMatch.exists)
    }

    private func returnToMenu(in app: XCUIApplication) {
        let backButton = element("settings-destination-back", in: app)
        XCTAssertTrue(backButton.isHittable)
        backButton.click()
        XCTAssertTrue(element("settings-menu", in: app).waitForExistence(timeout: 5))
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func element(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }
}
