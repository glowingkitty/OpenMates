// UI tests for deterministic native chat opening.
// Launches the debug-only seeded chat preview and verifies ChatView opens the
// latest bounded window without rendering the full synthetic history.
// No credentials, private chat IDs, or network-backed user data are used here.
// The live-dev seeded chat test can extend this target once the seed endpoint exists.

import XCTest

final class ChatOpeningScalabilityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testSeededLargeChatOpensWithinBoundedWork() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"

        let start = Date()
        app.launch()

        let initialWindow = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "initial-window-count=50"))
            .firstMatch
        XCTAssertTrue(initialWindow.waitForExistence(timeout: 12))
        XCTAssertTrue(initialWindow.label.contains("initial-window-count=50"))
        XCTAssertTrue(initialWindow.label.contains("total-message-count=250"))

        let latestMessage = app.staticTexts["Latest assistant response visible after bounded open"]
        XCTAssertTrue(latestMessage.waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["Seeded user message 1"].exists)
        XCTAssertLessThan(Date().timeIntervalSince(start), 20)

        let screenshot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = "Seeded large chat opened at latest bounded window"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
