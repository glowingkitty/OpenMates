// UI tests for deterministic native chat opening.
// Launches the debug-only seeded chat preview and verifies ChatView opens the
// latest bounded window without rendering the full synthetic history.
// No credentials, private chat IDs, or network-backed user data are used here.
// The live-dev seeded chat test can extend this target once the seed endpoint exists.

import XCTest

final class ChatOpeningScalabilityUITests: XCTestCase {
    private let boundedLaunchLimit: TimeInterval = 20
    private let interactionLimit: TimeInterval = 5

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
        XCTAssertLessThan(Date().timeIntervalSince(start), boundedLaunchLimit)

        let screenshot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = "Seeded large chat opened at latest bounded window"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    @MainActor
    func testSeededLargeChatCapturesFrameMetricsAndInputReactionTime() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-performance-metrics"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launchEnvironment["UI_TEST_PERFORMANCE_METRICS"] = "1"
        app.launchEnvironment["UI_TEST_CHAT_MESSAGE_COUNT"] = "1000"

        let launchStart = Date()
        app.launch()

        let latestMessage = app.staticTexts["Latest assistant response visible after bounded open"]
        XCTAssertTrue(latestMessage.waitForExistence(timeout: 16))
        let latestVisibleSeconds = Date().timeIntervalSince(launchStart)
        XCTAssertLessThan(latestVisibleSeconds, boundedLaunchLimit)

        let metrics = app.descendants(matching: .any)["chat-opening-performance-metrics"]
        XCTAssertTrue(metrics.waitForExistence(timeout: 5))
        let metricsBeforeInput = metrics.label
        XCTAssertTrue(metricsBeforeInput.contains("total-messages=1000"))

        let editor = try waitForMessageEditor(in: app, timeout: 5)
        let inputStart = Date()
        editor.tap()
        app.typeText("p")
        let sendButton = app.buttons["send-button"]
        XCTAssertTrue(sendButton.waitForExistence(timeout: interactionLimit))
        XCTAssertTrue(waitUntil(timeout: interactionLimit) { sendButton.isEnabled && sendButton.isHittable })
        let inputReactionSeconds = Date().timeIntervalSince(inputStart)
        XCTAssertLessThan(inputReactionSeconds, interactionLimit)

        attachText(
            "latest-visible-seconds=\(formatSeconds(latestVisibleSeconds)); input-reaction-seconds=\(formatSeconds(inputReactionSeconds)); \(metricsBeforeInput)",
            name: "Chat opening performance metrics"
        )
    }

    @MainActor
    func testLargeShellFixtureCapturesSidebarReactionTime() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-shell-metrics",
            "--ui-test-shell-performance-fixture"
        ]
        app.launchEnvironment["UI_TEST_SHELL_METRICS"] = "1"
        app.launchEnvironment["UI_TEST_SHELL_PERFORMANCE_FIXTURE"] = "1"
        app.launchEnvironment["UI_TEST_SHELL_CHAT_COUNT"] = "600"
        app.launch()

        let metrics = app.descendants(matching: .any)["shell-responsive-metrics"]
        XCTAssertTrue(metrics.waitForExistence(timeout: 15))
        XCTAssertTrue(metrics.label.contains("shell-performance=true"))
        XCTAssertTrue(metrics.label.contains("seeded-chat-count=600"))

        let sidebarToggle = app.buttons["sidebar-toggle"]
        XCTAssertTrue(sidebarToggle.waitForExistence(timeout: 10))
        let sidebarStart = Date()
        sidebarToggle.tap()
        XCTAssertTrue(waitUntil(timeout: interactionLimit) { metrics.label.contains("chat-panel-open=true") })
        let sidebarReactionSeconds = Date().timeIntervalSince(sidebarStart)
        XCTAssertLessThan(sidebarReactionSeconds, interactionLimit)

        attachText(
            "sidebar-reaction-seconds=\(formatSeconds(sidebarReactionSeconds)); \(metrics.label)",
            name: "Large shell sidebar performance metrics"
        )
    }

    @MainActor
    private func waitForMessageEditor(in app: XCUIApplication, timeout: TimeInterval) throws -> XCUIElement {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            let textField = app.textFields["message-editor"]
            if textField.exists { return textField }
            let textView = app.textViews["message-editor"]
            if textView.exists { return textView }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        } while Date() < deadline
        XCTFail("Expected message editor to appear")
        return app.textViews["message-editor"]
    }

    @MainActor
    private func waitUntil(timeout: TimeInterval, condition: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if condition() { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        } while Date() < deadline
        return condition()
    }

    @MainActor
    private func attachText(_ text: String, name: String) {
        let attachment = XCTAttachment(string: text)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func formatSeconds(_ value: TimeInterval) -> String {
        String(format: "%.3f", value)
    }
}
