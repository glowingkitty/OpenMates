// Responsive shell parity coverage for compact and regular native app chrome.
// Launches the real unauthenticated shell with debug-only metrics enabled so the
// test proves drawer versus side-by-side behavior without credentials, private
// chats, network setup, or fragile screenshot pixel comparisons.

import XCTest

final class ChatShellResponsiveParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testShellSidebarToggleMatchesViewportMode() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-shell-metrics"]
        app.launchEnvironment["UI_TEST_SHELL_METRICS"] = "1"
        app.launch()

        let metrics = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "shell-width="))
            .firstMatch
        XCTAssertTrue(metrics.waitForExistence(timeout: 12))

        let initialLabel = metrics.label
        let initialMode = try stringMetric("shell-mode", in: initialLabel)
        XCTAssertFalse(try boolMetric("chat-panel-open", in: initialLabel))
        XCTAssertTrue(try boolMetric("active-chat-visible", in: initialLabel))

        XCTAssertTrue(app.buttons["sidebar-toggle"].waitForExistence(timeout: 5))
        app.buttons["sidebar-toggle"].tap()

        let openMetrics = try waitForMetric("chat-panel-open", equals: true, in: metrics)
        XCTAssertEqual(try stringMetric("shell-mode", in: openMetrics), initialMode)
        XCTAssertTrue(try boolMetric("chat-panel-visible", in: openMetrics))
        XCTAssertTrue(try boolMetric("active-chat-visible", in: openMetrics))

        if initialMode == "compact" {
            XCTAssertEqual(try stringMetric("panel-mode", in: openMetrics), "drawer")
        } else {
            XCTAssertEqual(try stringMetric("panel-mode", in: openMetrics), "side-by-side")
            XCTAssertGreaterThan(try intMetric("active-main-width", in: openMetrics), 0)
        }

        let screenshot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = "Shell responsive parity \(initialMode)"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    func testHomeScreenQuickActionMenuExposesChatActions() throws {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 12))

        XCUIDevice.shared.press(.home)

        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let appIcon = springboard.icons["OpenMates"]
        XCTAssertTrue(appIcon.waitForExistence(timeout: 12), "Expected OpenMates app icon on the simulator home screen")

        appIcon.press(forDuration: 1.2)

        for title in ["Ask", "Ask About Photo", "Search", "Incognito Ask"] {
            XCTAssertTrue(
                quickActionTitleExists(title, in: springboard, timeout: 5),
                "Expected home screen quick action titled \(title)"
            )
        }

        let screenshot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = "Home screen quick actions"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func waitForMetric(_ key: String, equals expected: Bool, in element: XCUIElement) throws -> String {
        let deadline = Date().addingTimeInterval(5)
        while Date() < deadline {
            if (try? boolMetric(key, in: element.label)) == expected {
                return element.label
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        XCTFail("Timed out waiting for \(key)=\(expected). Last metrics: \(element.label)")
        return element.label
    }

    private func intMetric(_ key: String, in label: String) throws -> Int {
        let value = try XCTUnwrap(metric(key, in: label), "Missing integer metric \(key) in: \(label)")
        return try XCTUnwrap(Int(value), "Invalid integer metric \(key) in: \(label)")
    }

    private func boolMetric(_ key: String, in label: String) throws -> Bool {
        let value = try XCTUnwrap(metric(key, in: label), "Missing boolean metric \(key) in: \(label)")
        return try XCTUnwrap(Bool(value), "Invalid boolean metric \(key) in: \(label)")
    }

    private func stringMetric(_ key: String, in label: String) throws -> String {
        try XCTUnwrap(metric(key, in: label), "Missing string metric \(key) in: \(label)")
    }

    private func quickActionTitleExists(_ title: String, in springboard: XCUIApplication, timeout: TimeInterval) -> Bool {
        if springboard.buttons[title].waitForExistence(timeout: timeout) { return true }
        return springboard.staticTexts[title].waitForExistence(timeout: 1)
    }

    private func metric(_ key: String, in label: String) -> String? {
        label
            .split(separator: ";")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { $0.hasPrefix("\(key)=") }?
            .dropFirst(key.count + 1)
            .description
    }
}
