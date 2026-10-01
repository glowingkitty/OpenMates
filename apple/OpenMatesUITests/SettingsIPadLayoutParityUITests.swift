// iPad settings layout parity for guest Memories, Privacy, and Interface.
// Uses public settings state without credentials or private account data.
// Checks rendered bounds and hittability, including the Language child return.

import XCTest

@MainActor
final class SettingsIPadLayoutParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: direct surface=gui.apple assertions=settings-ui.navigation.contextual-availability,settings-ui.navigation.parent-return,settings-ui.parity.web-apple-shell
    func testIPadGuestSettingsDestinationsKeepControlsVisibleAndUsable() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-memory-fixture"]
        app.launch()

        let settingsButton = app.buttons["settings-button"]
        XCTAssertTrue(settingsButton.waitForExistence(timeout: 15))
        XCTAssertTrue(settingsButton.isHittable)
        settingsButton.tap()
        XCTAssertTrue(waitForElement("settings-menu", in: app, timeout: 10))
        XCTAssertFalse(app.descendants(matching: .any)["settings-apps-row"].exists)
        XCTAssertFalse(app.descendants(matching: .any)["learning-mode-toggle-wrapper"].exists)

        for destination in [
            (row: "settings-memories-row", page: "settings-memories-page"),
            (row: "settings-privacy-row", page: "settings-privacy-page"),
            (row: "settings-interface-row", page: "settings-interface-page"),
        ] {
            XCTAssertTrue(waitForElement(destination.row, in: app, timeout: 5))
            guard let row = visibleElement(destination.row, in: app) else {
                XCTFail("Expected visible row \(destination.row)")
                return
            }
            assertElementInsideWindow(row, in: app)
            XCTAssertTrue(row.isHittable)
            row.tap()
            XCTAssertTrue(waitForElement(destination.page, in: app, timeout: 8))
            XCTAssertFalse(app.tables.firstMatch.exists, "iPad settings must not render default List/table chrome")

            if destination.page == "settings-interface-page" {
                XCTAssertTrue(waitForElement("settings-interface-language-row", in: app, timeout: 5))
                let languageRow = app.descendants(matching: .any)["settings-interface-language-row"].firstMatch
                assertElementInsideWindow(languageRow, in: app)
                XCTAssertTrue(languageRow.isHittable)
                languageRow.tap()
                XCTAssertTrue(waitForElement("settings-language-page", in: app, timeout: 5))
                let languageBack = app.buttons["settings-language-back"]
                assertElementInsideWindow(languageBack, in: app)
                XCTAssertTrue(languageBack.isHittable)
                languageBack.tap()
                XCTAssertTrue(waitForElement("settings-interface-language-row", in: app, timeout: 5))
            }

            attachScreenshot(name: "iPad \(destination.page) layout")
            let back = app.buttons["settings-destination-back"]
            assertElementInsideWindow(back, in: app)
            XCTAssertTrue(back.isHittable)
            back.tap()
            XCTAssertTrue(waitForElement("settings-menu", in: app, timeout: 5))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible,settings-ui.parity.web-apple-shell
    func testIPadSettingsShellProducesLightAndDarkReviewArtifacts() {
        for appearance in ["Light", "Dark"] {
            let app = XCUIApplication()
            app.launchArguments = [
                "--ui-test-disable-auth-cache",
                "-AppleInterfaceStyle",
                appearance,
            ]
            app.launch()

            XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
            app.buttons["settings-button"].tap()
            XCTAssertTrue(waitForElement("settings-menu", in: app, timeout: 10))
            let aiRow = app.descendants(matching: .any)["settings-ai-row"].firstMatch
            XCTAssertTrue(waitForElement("settings-ai-row", in: app, timeout: 5))
            assertElementInsideWindow(aiRow, in: app)
            XCTAssertTrue(aiRow.isHittable)
            XCTAssertFalse(app.descendants(matching: .any)["settings-apps-row"].exists)
            let banner = app.descendants(matching: .any)["settings-banner-shell"].firstMatch
            XCTAssertTrue(banner.waitForExistence(timeout: 5))
            assertElementInsideWindow(banner, in: app)
            XCTAssertFalse(app.tables.firstMatch.exists)
            attachScreenshot(name: "iPad Settings shell \(appearance.lowercased())")

            app.terminate()
        }
    }

    private func waitForElement(_ identifier: String, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let element = app.descendants(matching: .any)[identifier].firstMatch
        if element.waitForExistence(timeout: timeout), visibleElement(identifier, in: app) != nil { return true }

        let scrollView = app.scrollViews.firstMatch
        for _ in 0..<6 where scrollView.exists {
            scrollView.swipeUp()
            if element.waitForExistence(timeout: 1), visibleElement(identifier, in: app) != nil { return true }
        }
        for _ in 0..<6 where scrollView.exists {
            scrollView.swipeDown()
            if element.waitForExistence(timeout: 1), visibleElement(identifier, in: app) != nil { return true }
        }
        return visibleElement(identifier, in: app) != nil
    }

    private func visibleElement(_ identifier: String, in app: XCUIApplication) -> XCUIElement? {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .allElementsBoundByIndex
            .first { isElementInsideWindow($0, in: app) && $0.isHittable }
    }

    private func assertElementInsideWindow(_ element: XCUIElement, in app: XCUIApplication) {
        XCTAssertTrue(element.exists, "Expected element to exist before checking its frame")
        XCTAssertTrue(
            isElementInsideWindow(element, in: app),
            "Expected element frame \(element.frame) to fit within window frame \(app.windows.firstMatch.frame.insetBy(dx: -1, dy: -1))"
        )
    }

    private func isElementInsideWindow(_ element: XCUIElement, in app: XCUIApplication) -> Bool {
        guard element.exists else { return false }
        let windowFrame = app.windows.firstMatch.frame.insetBy(dx: -1, dy: -1)
        return !element.frame.isEmpty && windowFrame.contains(element.frame)
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
