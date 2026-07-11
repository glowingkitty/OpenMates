// iPhone and iPad UI contracts for the complete synthetic chat-history fixture.
// Covers browser-mapped banner geometry, transcript width, composer clearance,
// RTL mirroring, Dynamic Type, accessibility order, and keyboard dismissal.
// Uses debug-only public fixture content without credentials or private chat data.
// Requires explicit OpenMatesUITests target membership before Xcode execution.

import XCTest

#if os(iOS)
@MainActor
final class ChatHistoryFullParityUITests: XCTestCase {
    private let transcriptMaximumWidth: CGFloat = 1_000
    private let geometryTolerance: CGFloat = 8

    override func setUpWithError() throws {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
    }

    override func tearDownWithError() throws {
        XCUIDevice.shared.orientation = .portrait
    }

    func testBannerTranscriptAndComposerMatchResponsiveWebContract() throws {
        let app = launchFixture()
        let metrics = element(in: app, identifier: "chat-history-layout-metrics")
        XCTAssertTrue(metrics.waitForExistence(timeout: 12), app.debugDescription)

        let label = metrics.label
        let viewportWidth = try metric("viewport-width", in: label)
        let transcriptWidth = try metric("transcript-width", in: label)
        let bannerWidth = try metric("banner-width", in: label)
        let bannerHeight = try metric("banner-height", in: label)
        let expectedMinimumHeight: CGFloat = viewportWidth <= 730 ? 230 : 240

        XCTAssertLessThanOrEqual(transcriptWidth, transcriptMaximumWidth + geometryTolerance)
        XCTAssertEqual(bannerWidth, viewportWidth, accuracy: geometryTolerance)
        XCTAssertGreaterThanOrEqual(bannerHeight, expectedMinimumHeight - geometryTolerance)
        XCTAssertEqual(try stringMetric("layout-direction", in: label), "ltr")
        XCTAssertEqual(try stringMetric("accessibility-order", in: label), "banner,user,assistant,composer")
        XCTAssertGreaterThanOrEqual(try metric("composer-safe-area-clearance", in: label), 0)

        assertVisibleHistoryOrder(in: app)
        XCTAssertFalse(app.tables.firstMatch.exists, "Chat product UI must not use default List/table chrome")
        attachScreenshot(name: "Chat history responsive parity")
    }

    func testRTLAndAccessibilityDynamicTypePreserveSemanticOrderAndClearance() throws {
        let app = launchFixture(
            extraArguments: ["-AppleLanguages", "(ar)", "-AppleLocale", "ar"],
            environment: [
                "UIPreferredContentSizeCategoryName": "UICTContentSizeCategoryAccessibilityXL",
                "UI_TEST_LAYOUT_DIRECTION": "rtl"
            ]
        )
        let metrics = element(in: app, identifier: "chat-history-layout-metrics")
        XCTAssertTrue(metrics.waitForExistence(timeout: 12), app.debugDescription)
        XCTAssertEqual(try stringMetric("layout-direction", in: metrics.label), "rtl")
        XCTAssertEqual(try stringMetric("accessibility-order", in: metrics.label), "banner,user,assistant,composer")

        let user = element(in: app, identifier: "chat-history-fixture-user")
        let assistant = element(in: app, identifier: "chat-history-fixture-assistant")
        XCTAssertTrue(user.waitForExistence(timeout: 5))
        XCTAssertTrue(assistant.waitForExistence(timeout: 5))
        XCTAssertLessThan(user.frame.midX, assistant.frame.midX, "RTL must mirror user and assistant ownership")
        XCTAssertTrue(element(in: app, identifier: "chat-header-title").exists)
        XCTAssertTrue(element(in: app, identifier: "chat-header-summary").exists)

        scrollToFinalContent(in: app)
        assertComposerClearsFinalContent(in: app)
        attachScreenshot(name: "Chat history RTL accessibility Dynamic Type")
    }

    func testKeyboardFocusKeepsComposerVisibleAndHistoryTapDismissesKeyboard() throws {
        let app = launchFixture()
        scrollToFinalContent(in: app)
        let editor = element(in: app, identifier: "message-editor")
        XCTAssertTrue(editor.waitForExistence(timeout: 8))
        editor.tap()
        editor.typeText("x")

        let keyboard = app.keyboards.firstMatch
        XCTAssertTrue(keyboard.waitForExistence(timeout: 5))
        let composer = element(in: app, identifier: "message-field")
        XCTAssertLessThanOrEqual(composer.frame.maxY, keyboard.frame.minY - 2)
        XCTAssertTrue(composer.isHittable)

        element(in: app, identifier: "chat-history-container").tap()
        XCTAssertFalse(keyboard.waitForExistence(timeout: 3))
        assertComposerClearsFinalContent(in: app)
    }

    private func launchFixture(
        extraArguments: [String] = [],
        environment: [String: String] = [:]
    ) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview",
            "chat-opening",
            "--ui-test-chat-history-full-parity"
        ] + extraArguments
        app.launchEnvironment = [
            "DEV_PREVIEW": "chat-opening",
            "UI_TEST_CHAT_HISTORY_FULL_PARITY": "1"
        ].merging(environment) { _, replacement in replacement }
        app.launch()
        return app
    }

    private func assertVisibleHistoryOrder(in app: XCUIApplication) {
        let banner = element(in: app, identifier: "chat-header-banner")
        let user = element(in: app, identifier: "chat-history-fixture-user")
        let assistant = element(in: app, identifier: "chat-history-fixture-assistant")
        XCTAssertTrue(banner.waitForExistence(timeout: 8))
        XCTAssertTrue(user.waitForExistence(timeout: 8))
        XCTAssertTrue(assistant.waitForExistence(timeout: 8))
        XCTAssertLessThan(banner.frame.minY, user.frame.minY)
        XCTAssertLessThan(user.frame.minY, assistant.frame.minY)
    }

    private func scrollToFinalContent(in app: XCUIApplication) {
        let history = element(in: app, identifier: "chat-history-container")
        let finalContent = element(in: app, identifier: "chat-history-final-content")
        XCTAssertTrue(history.waitForExistence(timeout: 8))
        for _ in 0..<8 where !isVisible(finalContent, in: app) {
            history.swipeUp()
        }
        XCTAssertTrue(finalContent.waitForExistence(timeout: 5))
        XCTAssertTrue(isVisible(finalContent, in: app))
    }

    private func assertComposerClearsFinalContent(in app: XCUIApplication) {
        let finalContent = element(in: app, identifier: "chat-history-final-content")
        let composer = element(in: app, identifier: "message-field")
        XCTAssertTrue(composer.waitForExistence(timeout: 5))
        XCTAssertLessThanOrEqual(finalContent.frame.maxY, composer.frame.minY - 2)
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }

    private func isVisible(_ element: XCUIElement, in app: XCUIApplication) -> Bool {
        element.exists && !element.frame.isEmpty && app.windows.firstMatch.frame.intersects(element.frame)
    }

    private func metric(_ key: String, in label: String) throws -> CGFloat {
        let value = try XCTUnwrap(rawMetric(key, in: label), "Missing metric \(key): \(label)")
        return CGFloat(try XCTUnwrap(Double(value), "Invalid metric \(key): \(label)"))
    }

    private func stringMetric(_ key: String, in label: String) throws -> String {
        try XCTUnwrap(rawMetric(key, in: label), "Missing metric \(key): \(label)")
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
