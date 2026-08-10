// macOS UI contracts for the synthetic chat-history parity fixture.
// Covers narrow and wide transcript geometry, keyboard and pointer operation,
// composer clearance, accessibility order, and absence of default native chrome.
// Uses debug-only public fixture content without credentials or private chat data.
// Requires explicit OpenMatesUITests target membership before Xcode execution.

import XCTest

#if os(macOS)
@MainActor
final class ChatHistoryMacParityUITests: XCTestCase {
    private let transcriptMaximumWidth: CGFloat = 1_000
    private let geometryTolerance: CGFloat = 8

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testWideAndNarrowWindowsPreserveTranscriptWidthAndComposerClearance() throws {
        let app = launchFixture()
        let window = app.windows.firstMatch
        XCTAssertTrue(window.waitForExistence(timeout: 12), app.debugDescription)

        assertLayoutContract(in: app, expectedMode: "wide")
        attachScreenshot(name: "macOS chat history wide")

        resize(window: window, widthScale: 0.58)
        assertLayoutContract(in: app, expectedMode: "narrow")
        attachScreenshot(name: "macOS chat history narrow")
    }

    func testKeyboardPointerAndFocusOrderRemainOperable() throws {
        let app = launchFixture()
        let history = element(in: app, identifier: "chat-history-container")
        let editor = element(in: app, identifier: "message-editor")
        XCTAssertTrue(history.waitForExistence(timeout: 12))
        XCTAssertTrue(editor.waitForExistence(timeout: 8))

        history.scroll(byDeltaX: 0, deltaY: -800)
        XCTAssertTrue(element(in: app, identifier: "chat-history-final-content").waitForExistence(timeout: 5))
        editor.click()
        editor.typeText("Synthetic keyboard focus")
        XCTAssertTrue(element(in: app, identifier: "message-field").isHittable)

        app.typeKey(.tab, modifierFlags: [])
        XCTAssertTrue(app.buttons["message-input-fullscreen-button"].waitForExistence(timeout: 5))
        history.click()
        XCTAssertTrue(history.isHittable)
        XCTAssertFalse(app.tables.firstMatch.exists, "Chat product UI must not use default List/table chrome")
    }

    private func launchFixture() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview",
            "chat-opening",
            "--ui-test-chat-history-full-parity"
        ]
        app.launchEnvironment = [
            "DEV_PREVIEW": "chat-opening",
            "UI_TEST_CHAT_HISTORY_FULL_PARITY": "1"
        ]
        app.launch()
        return app
    }

    private func assertLayoutContract(in app: XCUIApplication, expectedMode: String) {
        let metrics = element(in: app, identifier: "chat-history-layout-metrics")
        XCTAssertTrue(metrics.waitForExistence(timeout: 8), app.debugDescription)
        let label = metrics.label
        XCTAssertEqual(stringMetric("window-mode", in: label), expectedMode)
        XCTAssertLessThanOrEqual(metric("transcript-width", in: label), transcriptMaximumWidth + geometryTolerance)
        XCTAssertGreaterThanOrEqual(metric("composer-safe-area-clearance", in: label), 0)
        XCTAssertEqual(stringMetric("accessibility-order", in: label), "banner,user,assistant,composer")
        XCTAssertTrue(element(in: app, identifier: "chat-header-banner").exists)
        XCTAssertTrue(element(in: app, identifier: "chat-history-fixture-user").exists)
        XCTAssertTrue(element(in: app, identifier: "chat-history-fixture-assistant").exists)
    }

    private func resize(window: XCUIElement, widthScale: CGFloat) {
        let start = window.coordinate(withNormalizedOffset: CGVector(dx: 0.99, dy: 0.5))
        let end = window.coordinate(withNormalizedOffset: CGVector(dx: widthScale, dy: 0.5))
        start.press(forDuration: 0.2, thenDragTo: end)
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }

    private func metric(_ key: String, in label: String) -> CGFloat {
        guard let value = rawMetric(key, in: label), let number = Double(value) else {
            XCTFail("Missing numeric metric \(key): \(label)")
            return 0
        }
        return CGFloat(number)
    }

    private func stringMetric(_ key: String, in label: String) -> String {
        guard let value = rawMetric(key, in: label) else {
            XCTFail("Missing metric \(key): \(label)")
            return ""
        }
        return value
    }

    private func rawMetric(_ key: String, in label: String) -> String? {
        label.split(separator: ";")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { $0.hasPrefix("\(key)=") }?
            .dropFirst(key.count + 1)
            .description
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
#endif
