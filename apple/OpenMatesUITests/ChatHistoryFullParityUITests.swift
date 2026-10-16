// iPhone and iPad UI contracts for the complete synthetic chat-history fixture.
// Covers browser-mapped banner geometry, transcript width, composer clearance,
// RTL mirroring, Dynamic Type, accessibility order, and keyboard dismissal.
// Uses debug-only public fixture content without credentials or private chat data.
// Requires explicit OpenMatesUITests target membership before Xcode execution.

import CryptoKit
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

    // contract-test: direct surface=gui.apple assertions=chats.layout.responsive-history
    func testShortUserBubbleHugsTextAtTrailingEdge() throws {
        let app = launchFixture(environment: ["UI_TEST_USER_BUBBLE_VARIANT": "short"])
        let bubble = element(in: app, identifier: "user-message-content")
        XCTAssertTrue(bubble.waitForExistence(timeout: 12), app.debugDescription)
        let row = element(in: app, identifier: "chat-history-fixture-user")
        XCTAssertTrue(bubble.isHittable)
        XCTAssertLessThan(bubble.frame.width, 200, "A short reply must keep its intrinsic bubble width")
        XCTAssertGreaterThan(bubble.frame.width, 60)
        XCTAssertLessThan(bubble.frame.height, 65)
        XCTAssertEqual(bubble.frame.maxX, row.frame.maxX, accuracy: 2)
        attachScreenshot(name: "Short user bubble intrinsic width")
    }

    // contract-test: direct surface=gui.apple assertions=chats.layout.responsive-history
    func testWrappedUserBubbleStaysWithinTranscriptLane() throws {
        let app = launchFixture(environment: ["UI_TEST_USER_BUBBLE_VARIANT": "wrapped"])
        let bubble = element(in: app, identifier: "user-message-content")
        XCTAssertTrue(bubble.waitForExistence(timeout: 12), app.debugDescription)
        let row = element(in: app, identifier: "chat-history-fixture-user")
        let history = element(in: app, identifier: "chat-history-container")
        XCTAssertTrue(bubble.isHittable)
        XCTAssertGreaterThan(bubble.frame.width, 200)
        XCTAssertGreaterThan(bubble.frame.height, 70, "Long user prose must wrap within the available lane")
        XCTAssertLessThan(bubble.frame.width, history.frame.width)
        XCTAssertEqual(bubble.frame.maxX, row.frame.maxX, accuracy: 2)
        attachScreenshot(name: "Wrapped user paragraph leading alignment")
    }

    // contract-test: direct surface=gui.apple assertions=chats.layout.responsive-history
    func testExplicitUserNewlinesKeepIntrinsicWidthAndLineBreaks() throws {
        let app = launchFixture(environment: ["UI_TEST_USER_BUBBLE_VARIANT": "newlines"])
        let bubble = element(in: app, identifier: "user-message-content")
        XCTAssertTrue(bubble.waitForExistence(timeout: 12), app.debugDescription)
        let row = element(in: app, identifier: "chat-history-fixture-user")
        XCTAssertTrue(bubble.isHittable)
        XCTAssertLessThan(bubble.frame.width, 330, "The longest explicit line determines intrinsic width")
        XCTAssertGreaterThan(bubble.frame.height, 70, "The three explicit lines must remain separate")
        XCTAssertEqual(bubble.frame.maxX, row.frame.maxX, accuracy: 2)
        attachScreenshot(name: "Explicit user newlines leading alignment")
    }

    // contract-test: direct surface=gui.apple assertions=chats.layout.responsive-history,message-input.layout.responsive-parity
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
        assertAssistantUsesTranscriptWidth(in: app)
        XCTAssertFalse(app.tables.firstMatch.exists, "Chat product UI must not use default List/table chrome")
        attachScreenshot(name: "Chat history responsive parity")
    }

    // contract-test: direct surface=gui.apple assertions=chats.layout.responsive-history
    func testHeaderActionsOverflowAndBannerScrollStyleMatchWebContract() throws {
        let app = launchFixture()
        let actions = element(in: app, identifier: "chat-top-actions")
        XCTAssertTrue(actions.waitForExistence(timeout: 12), app.debugDescription)
        XCTAssertEqual(actions.value as? String, "banner-overlay")
        XCTAssertTrue(element(in: app, identifier: "report-issue-button").exists)
        XCTAssertTrue(element(in: app, identifier: "chat-more-button").exists)
        XCTAssertTrue(element(in: app, identifier: "chat-close-button").exists)
        XCTAssertFalse(element(in: app, identifier: "chat-share-button").exists)

        element(in: app, identifier: "chat-more-button").tap()
        let moreMenu = element(in: app, identifier: "chat-more-actions")
        XCTAssertTrue(moreMenu.waitForExistence(timeout: 3))
        XCTAssertTrue(element(in: app, identifier: "chat-more-share-button").exists)
        XCTAssertTrue(element(in: app, identifier: "chat-details-button").exists)
        let reminder = element(in: app, identifier: "chat-reminders-button")
        XCTAssertTrue(reminder.exists)
        XCTAssertFalse(reminder.label.hasPrefix("chat."), "Reminder action must resolve its translation")
        XCTAssertLessThan(moreMenu.frame.width, actions.frame.width - 24, "More actions should size to their labels")
        attachScreenshot(name: "Chat header compact overflow on banner")

        element(in: app, identifier: "chat-more-button").tap()
        let history = element(in: app, identifier: "chat-history-container")
        for _ in 0..<6 where (actions.value as? String) != "standard" {
            history.swipeUp()
        }
        XCTAssertEqual(actions.value as? String, "standard")
        attachScreenshot(name: "Chat header standard style after banner scroll")
    }

    // contract-test: direct surface=gui.apple assertions=chats.layout.responsive-history,message-input.layout.responsive-parity
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
        XCTAssertTrue(app.staticTexts["Synthetic Mate"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["generated by Synthetic Model"].waitForExistence(timeout: 5))
        XCTAssertLessThan(user.frame.midX, assistant.frame.midX, "RTL must mirror user and assistant ownership")
        let userBubble = element(in: app, identifier: "user-message-content")
        XCTAssertTrue(userBubble.exists)
        XCTAssertEqual(userBubble.frame.minX, user.frame.minX, accuracy: 2,
            "Intrinsic user bubbles must stay at the mirrored trailing edge in RTL")
        XCTAssertTrue(element(in: app, identifier: "chat-header-title").exists)
        XCTAssertTrue(element(in: app, identifier: "chat-header-summary").exists)

        scrollToFinalContent(in: app)
        assertComposerClearsFinalContent(in: app)
        attachScreenshot(name: "Chat history RTL accessibility Dynamic Type")
    }

    // contract-test: direct surface=gui.apple assertions=chats.layout.responsive-history,message-input.layout.responsive-parity
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

    // contract-test: direct surface=gui.apple assertions=chats.streaming.progressive-presentation,chats.rendering.assistant-document-convergence,chats.surface.semantic-parity,message-input.actions.visibility
    func testStreamingThinkingAndComposerStopMatchWebContract() throws {
        let app = launchFixture(extraArguments: ["--ui-test-streaming-presentation"])
        let stage = element(in: app, identifier: "streaming-banner")
        let stop = element(in: app, identifier: "stop-processing-button")

        XCTAssertTrue(stage.waitForExistence(timeout: 12), app.debugDescription)
        XCTAssertFalse(stage.label.contains("embed."), "Stage status exposed an untranslated key")
        // Processing must expose Stop in the compact, unfocused follow-up field.
        XCTAssertFalse(app.keyboards.firstMatch.exists)
        XCTAssertTrue(stop.waitForExistence(timeout: 8), app.debugDescription)
        XCTAssertTrue(stop.isHittable)
        XCTAssertGreaterThanOrEqual(stop.frame.width, 44)
        XCTAssertGreaterThanOrEqual(stop.frame.height, 44)
        XCTAssertFalse(element(in: app, identifier: "send-button").exists)
        XCTAssertFalse(element(in: app, identifier: "record-audio-button").exists)

        let history = element(in: app, identifier: "chat-history-container")
        XCTAssertTrue(element(in: app, identifier: "thinking-section").exists)
        XCTAssertTrue(app.buttons["thinking-toggle"].exists)
        let thinking = element(in: app, identifier: "thinking-content")
        for _ in 0..<5 where !thinking.exists {
            history.swipeUp()
        }
        XCTAssertTrue(thinking.waitForExistence(timeout: 5), app.debugDescription)
        XCTAssertLessThanOrEqual(thinking.frame.height, 202, "Streaming thinking content must remain bounded")
        XCTAssertEqual(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "**")).count, 0)
        XCTAssertTrue(app.staticTexts["Bounded thinking detail"].exists)
        let assistant = element(in: app, identifier: "chat-history-fixture-assistant")
        XCTAssertTrue(assistant.exists)
        XCTAssertTrue(assistant.label.hasPrefix("Synthetic assistant history fixture"))
        XCTAssertFalse(assistant.label.contains("Bounded thinking detail"), "A message with visible text keeps its own semantic label")
        let manifestValue = try XCTUnwrap(assistant.value as? String)
        let manifest = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(manifestValue.utf8)) as? [String: Any])
        let normalizedLabel = assistant.label.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
        let labelHash = SHA256.hash(data: Data(normalizedLabel.utf8)).prefix(8)
            .map { String(format: "%02x", $0) }.joined()
        XCTAssertEqual(manifest["role"] as? String, "assistant")
        XCTAssertEqual(manifest["content_hash"] as? String, labelHash, "DEBUG evidence and accessibility must consume the same prepared text")
        XCTAssertEqual(manifest["text_length"] as? Int, normalizedLabel.count)
        XCTAssertEqual(manifest["has_thinking"] as? Bool, true)
        attachScreenshot(name: "Streaming stage thinking and composer stop")
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

    private func assertAssistantUsesTranscriptWidth(in app: XCUIApplication) {
        let history = element(in: app, identifier: "chat-history-container")
        let assistantContent = element(in: app, identifier: "assistant-message-content")
        let senderName = element(in: app, identifier: "message-sender-name")
        XCTAssertTrue(assistantContent.waitForExistence(timeout: 5))
        XCTAssertTrue(senderName.waitForExistence(timeout: 5))
        XCTAssertLessThanOrEqual(
            senderName.frame.minX,
            history.frame.minX + 24,
            "Assistant response was centered instead of leading-aligned"
        )
        XCTAssertGreaterThanOrEqual(
            assistantContent.frame.width,
            history.frame.width - 48,
            "Assistant response did not use the available transcript width"
        )
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
