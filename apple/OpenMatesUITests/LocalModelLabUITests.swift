// Native-only local model lab navigation and privacy/scope controls.
// These tests never download weights or claim actual inference/model quality.
import XCTest

@MainActor
final class LocalModelLabUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing,settings-ui.composition.canonical-and-accessible,apple-local-model-lab.optional-downloads,apple-local-model-lab.isolated-scope,apple-local-model-lab.availability
    func testLabOpensFromDevelopersWithExplicitLocalOnlyScope() {
        let app = openLab()
        XCTAssertTrue(app.descendants(matching: .any)["local-model-lab-local-only"].exists)
        XCTAssertTrue(app.descendants(matching: .any)["local-model-lab-production-scope"].exists)
        XCTAssertFalse(app.webViews.firstMatch.exists)
        XCTAssertFalse(app.tables.firstMatch.exists)
        for id in ["whisper", "kokoro", "privacyFilter"] {
            let card = app.descendants(matching: .any)["local-model-\(id)-card"]
            scrollTo(card, in: app)
            XCTAssertTrue(card.exists, id)
            let download = app.buttons["local-model-\(id)-download"]
            scrollTo(download, in: app)
            XCTAssertTrue(download.exists, "A clean test container must offer the optional \(id) download")
            #if arch(arm64)
            let hardwareSupported = true
            #else
            let hardwareSupported = false
            #endif
            let supported = hardwareSupported && (id != "kokoro" || ProcessInfo.processInfo.operatingSystemVersion.majorVersion < 27)
            XCTAssertEqual(download.isEnabled, supported, "Unsupported runtimes must be blocked before downloading")
            if supported {
                XCTAssertTrue(download.isHittable)
            } else {
                let warning = app.descendants(matching: .any)["local-model-\(id)-unavailable"]
                scrollTo(warning, in: app)
                XCTAssertTrue(warning.exists)
                XCTAssertTrue(warning.isHittable, "The reason must be visible before installing assets")
            }
            if id == "kokoro" {
                let limitations = app.descendants(matching: .any)["local-model-lab-kokoro-input-limits"]
                scrollTo(limitations, in: app)
                XCTAssertTrue(limitations.exists)
                XCTAssertTrue(limitations.isHittable)
            }
            XCTAssertFalse(app.buttons["local-model-\(id)-run"].exists,
                           "Tests must remain unavailable before assets are installed")
        }
        let privacy = app.descendants(matching: .any)["local-model-lab-privacy"]
        scrollTo(privacy, in: app)
        XCTAssertTrue(privacy.exists)
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "Local model lab optional downloads and ephemeral input policy"
        attachment.lifetime = .keepAlways
        add(attachment)
        app.descendants(matching: .any)["settings-developers-back"].firstMatch.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-developers-local-models-row"].firstMatch.waitForExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.isolated-scope
    func testLabSwitchCanBeChangedAndReturnedWithoutCloudOrBillingNavigation() {
        let app = openLab()
        let toggle = app.descendants(matching: .any)["local-model-lab-toggle"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        let button = toggle.buttons.firstMatch
        XCTAssertTrue(button.isHittable)
        let before = button.value as? String
        button.tap()
        XCTAssertNotEqual(button.value as? String, before)
        XCTAssertTrue(app.descendants(matching: .any)["settings-local-models-page"].exists)
        XCTAssertFalse(app.descendants(matching: .any)["settings-billing-page"].exists)
        button.tap()
        XCTAssertEqual(button.value as? String, before)
    }

    private func openLab() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-account-settings-fixture"]
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        XCTAssertTrue(app.scrollViews["settings-menu"].firstMatch.waitForExistence(timeout: 10))
        let developers = app.descendants(matching: .any)["settings-developers-row"].firstMatch
        scrollTo(developers, in: app)
        XCTAssertTrue(developers.exists, "Settings must expose the Developers destination")
        XCTAssertTrue(developers.isHittable, "Developers must be visible in the settings scroll container")
        developers.tap()
        let row = app.descendants(matching: .any)["settings-developers-local-models-row"].firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        XCTAssertTrue(row.isHittable)
        row.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-local-models-page"].waitForExistence(timeout: 5))
        return app
    }
    private func scrollTo(_ element: XCUIElement, in app: XCUIApplication) {
        if element.exists && element.isHittable { return }
        // Match SettingsFullParityUITests: gesture inside the actual settings
        // scroll container, avoiding the app shell and its swipe handlers.
        let labScroll = app.scrollViews["local-model-lab-scroll"].firstMatch
        let menuScroll = app.scrollViews["settings-menu"].firstMatch
        let scrollView = labScroll.exists ? labScroll : (menuScroll.exists ? menuScroll : app.scrollViews.firstMatch)
        XCTAssertTrue(scrollView.exists, "Expected a native settings scroll container")
        for _ in 0..<12 where scrollView.exists {
            scrollView.swipeUp()
            if element.exists && element.isHittable { return }
        }
        // Availability notices can precede the previously inspected download control.
        for _ in 0..<12 where scrollView.exists {
            scrollView.swipeDown()
            if element.exists && element.isHittable { return }
        }
    }
}
