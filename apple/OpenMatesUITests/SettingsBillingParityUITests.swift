// UI smoke coverage for native settings and billing parity entry points.
// Runs unauthenticated against public settings only, avoiding credentials,
// invoices, customer IDs, payment data, and private account screenshots.

import XCTest

@MainActor
final class SettingsBillingParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testPublicSettingsMenuExposesStablePreferenceIdentifiers() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"]
        app.launch()

        let settingsButton = app.buttons["settings-button"]
        XCTAssertTrue(settingsButton.waitForExistence(timeout: 15))
        settingsButton.tap()

        XCTAssertTrue(
            app.descendants(matching: .any)["settings-menu"].waitForExistence(timeout: 10),
            "Expected settings menu. Visible UI: \(visibleStateLabels(in: app))"
        )

        for identifier in [
            "settings-pricing-row",
            "settings-ai-row",
            "settings-interface-row",
            "settings-newsletter-row",
            "settings-support-row",
            "settings-report-issue-row",
        ] {
            XCTAssertTrue(
                app.descendants(matching: .any)[identifier].waitForExistence(timeout: 5),
                "Expected \(identifier). Visible UI: \(visibleStateLabels(in: app))"
            )
        }

        XCTAssertFalse(
            app.descendants(matching: .any)["settings-billing-row"].exists,
            "Unauthenticated settings must not expose billing account actions"
        )
        XCTAssertFalse(app.tables.firstMatch.exists, "Settings home must not render default List/table chrome")

        app.descendants(matching: .any)["settings-interface-row"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-interface-page"].waitForExistence(timeout: 10))

        attachScreenshot(name: "Public settings identifiers")
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func visibleStateLabels(in app: XCUIApplication) -> String {
        let buttons = elementSummaries(app.buttons.allElementsBoundByIndex, prefix: "button")
        let staticTexts = elementSummaries(app.staticTexts.allElementsBoundByIndex, prefix: "text")
        return (buttons + staticTexts).prefix(30).joined(separator: " | ")
    }

    private func elementSummaries(_ elements: [XCUIElement], prefix: String) -> [String] {
        elements.compactMap { element in
            let identifier = element.identifier.trimmingCharacters(in: .whitespacesAndNewlines)
            let label = element.label.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !identifier.isEmpty || !label.isEmpty else { return nil }
            if identifier.isEmpty { return "\(prefix):\(redact(label))" }
            if label.isEmpty || label == identifier { return "\(prefix)#\(identifier)" }
            return "\(prefix)#\(identifier)=\(redact(label))"
        }
    }

    private func redact(_ value: String) -> String {
        value.contains("@") ? "<email>" : value
    }
}
