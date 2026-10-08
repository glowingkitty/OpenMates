// Simulator coverage for background chat notification behavior.
// The host helper injects generic server-shaped payloads only after this test
// requests a named scenario. This injection helper does not prove provider
// delivery, real device-token registration, or encrypted extension processing.
// Compatible Simulators can register real APNs tokens and test those paths
// separately. Credentials and chat identifiers are never logged.

import Foundation
import XCTest

@MainActor
final class BackgroundChatNotificationUITests: XCTestCase {
    private let notificationTitle = "OpenMates"
    private let notificationBody = "New message received"
    private let markerPrompt = "Reply with one short sentence: Hello from Osaka."
    private let notificationTimeout: TimeInterval = 30

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // Uses an actual DEV account, inference completion and APNs delivery. There
    // is deliberately no host injection helper in this scenario.
    // contract-test: direct surface=gui.apple assertions=apple-notifications.payload.privacy-safe,apple-notifications.action.routing-coherent,apple-notifications.delivery.idempotent-visible
    func testLiveDevCompletionDeliversAfterBackgroundAndOpensSentChat() throws {
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp(extraArguments: ["--ui-test-fresh-new-chat"])
        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        RealAccountUITestSupport.openNewChatIfNeeded(app: app)
        guard let editor = RealAccountUITestSupport.waitForMessageEditor(in: app, timeout: 20) else {
            XCTFail("The live DEV chat composer did not open")
            return
        }
        XCTAssertEqual(editor.value as? String, "", "Preserve any unrelated existing draft")
        guard RealAccountUITestSupport.focusForTextEntry(editor, in: app, identifier: "message-editor") else { return }
        let responseMarker = "WATCH6DC7-\(UUID().uuidString.prefix(8)) completed"
        let prompt = "apple-watch-notification-6dc7: Reply with exactly \(responseMarker)."
        app.typeText(prompt)
        XCTAssertEqual(editor.value as? String, prompt)
        let send = app.buttons["send-button"]
        XCTAssertTrue(send.waitForExistence(timeout: 5))
        send.tap()
        XCUIDevice.shared.press(.home)
        let board = springBoard()
        let delivered = board.staticTexts.matching(
            NSPredicate(format: "label CONTAINS %@", responseMarker)
        ).firstMatch
        XCTAssertTrue(delivered.waitForExistence(timeout: 120),
                      "No decrypted completion preview appeared after backgrounding the DEV app; generic fallback is insufficient")
        let notificationPreview = delivered.label
        XCTAssertTrue(notificationPreview.contains(responseMarker), "The system preview must contain this response start")
        XCTAssertNotEqual(notificationPreview, notificationBody, "Generic fallback does not prove encrypted preview delivery")
        for internalMarker in ["```", "app_skill_use", "embed_id", "embed_ref", "json_embed"] {
            XCTAssertFalse(notificationPreview.contains(internalMarker),
                           "System notification exposed an internal message marker")
        }
        attachScreenshot(named: "Actual DEV completion notification after background")
        try openDeliveredNotification(delivered, on: board)
        XCTAssertTrue(RealAccountUITestSupport.accessibilityElement(
            in: app, identifier: "message-user", labelContaining: prompt
        ).waitForExistence(timeout: 30), "The notification must open this sent chat")
        XCTAssertTrue(RealAccountUITestSupport.accessibilityElement(
            in: app, identifier: "message-assistant", labelContaining: responseMarker
        ).waitForExistence(timeout: 30))
    }

    // Opt-in actual DEV inference, completion and APNs path. Expected display
    // text comes from the operator's approved real skill scenario, never an
    // injected payload or a fabricated provider result. Missing configuration is
    // a skip and must not be recorded as proof of skill/inline-embed delivery.
    // contract-test: direct surface=gui.apple assertions=apple-notifications.preview.readable,apple-notifications.payload.privacy-safe,apple-notifications.action.routing-coherent
    func testLiveDevSkillPreviewPreservesHumanPrefixResponseAndInlineImages() throws {
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        func configuration(_ key: String) throws -> String {
            guard let value = RealAccountTestCredentials.configurationValue(for: key), !value.isEmpty else {
                throw XCTSkip("Approved real skill preview scenario is not configured")
            }
            return value
        }
        let prompt = try configuration("OPENMATES_NOTIFICATION_PREVIEW_PROMPT")
        let expectedPrefix = try configuration("OPENMATES_NOTIFICATION_PREVIEW_EXPECTED_PREFIX")
        let responseStart = try configuration("OPENMATES_NOTIFICATION_PREVIEW_EXPECTED_RESPONSE_START")
        let imageMarker = try configuration("OPENMATES_NOTIFICATION_PREVIEW_EXPECTED_IMAGE_MARKER")
        XCTAssertNotNil(expectedPrefix.range(of: #"^.+ \| .+ & [1-9][0-9]* other app skills$"#, options: .regularExpression),
                        "The declared scenario must include a first human app/skill prefix and additional-skill count")
        XCTAssertNotNil(imageMarker.range(of: #"^\[[1-9][0-9]* Images\]$"#, options: .regularExpression),
                        "The declared scenario must include actual inline image output")
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp(extraArguments: ["--ui-test-fresh-new-chat"])
        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        RealAccountUITestSupport.openNewChatIfNeeded(app: app)
        guard let editor = RealAccountUITestSupport.waitForMessageEditor(in: app, timeout: 20) else {
            XCTFail("The live DEV chat composer did not open")
            return
        }
        XCTAssertEqual(editor.value as? String, "", "Preserve any unrelated existing draft")
        guard RealAccountUITestSupport.focusForTextEntry(editor, in: app, identifier: "message-editor") else { return }
        app.typeText(prompt)
        XCTAssertEqual(editor.value as? String, prompt)
        let send = app.buttons["send-button"]
        XCTAssertTrue(send.waitForExistence(timeout: 5))
        send.tap()
        XCUIDevice.shared.press(.home)
        let board = springBoard()
        let delivered = board.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", responseStart)).firstMatch
        XCTAssertTrue(delivered.waitForExistence(timeout: 120), "Actual encrypted skill completion preview was not delivered")
        let preview = delivered.label
        XCTAssertTrue(preview.hasPrefix(expectedPrefix + "\n\n"), "Human skill prefix and paragraph separation are missing")
        XCTAssertTrue(preview.contains(responseStart), "Readable response start is missing")
        XCTAssertTrue(preview.contains(imageMarker), "Actual inline image output must use its human count marker")
        for internalMarker in ["```", "app_skill_use", "embed_id", "embed_ref", "json_embed"] {
            XCTAssertFalse(preview.contains(internalMarker), "System notification exposed an internal message marker")
        }
        XCTAssertNotEqual(preview, notificationBody, "Generic fallback does not prove encrypted skill preview delivery")
        attachScreenshot(named: "Actual DEV encrypted skill prefix response and inline images")
        try openDeliveredNotification(delivered, on: board)
        XCTAssertTrue(RealAccountUITestSupport.accessibilityElement(
            in: app, identifier: "message-user", labelContaining: prompt
        ).waitForExistence(timeout: 30), "Translated Open chat action must select this actual sent chat")
        XCTAssertTrue(RealAccountUITestSupport.accessibilityElement(
            in: app, identifier: "message-assistant", labelContaining: responseStart
        ).waitForExistence(timeout: 30))
    }

    private func openDeliveredNotification(_ notification: XCUIElement, on board: XCUIApplication) throws {
        notification.press(forDuration: 1)
        let expectedAction = RealAccountTestCredentials.configurationValue(for: "OPENMATES_NOTIFICATION_OPEN_CHAT_LABEL") ?? "Open chat"
        XCTAssertNotEqual(expectedAction, "chat.open_chat", "The expected notification action must be translated")
        let openChat = board.buttons[expectedAction]
        XCTAssertTrue(openChat.waitForExistence(timeout: 5), "System notification did not expose the translated Open chat action")
        XCTAssertFalse(board.buttons["chat.open_chat"].exists, "System notification exposed an untranslated action key")
        attachScreenshot(named: "Actual DEV translated Open chat action")
        openChat.tap()
    }

    // contract-test: direct surface=gui.apple assertions=apple-notifications.payload.privacy-safe,apple-notifications.action.routing-coherent,apple-notifications.delivery.idempotent-visible
    func testSimulatorNotificationInteractions() throws {
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp()

        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        RealAccountUITestSupport.sendWelcomePrompt(app: app, prompt: markerPrompt)
        RealAccountUITestSupport.assertAssistantResponds(app: app, timeout: 90)
        let chatId = try currentChatId(in: app)

        // The system owns foreground presentation. The app must remain usable and
        // must not render a second, app-owned copy of the generic alert text.
        try requestPush(scenario: "foreground_dedup", chatId: chatId)
        XCTAssertNotNil(RealAccountUITestSupport.waitForMessageEditor(in: app, timeout: 10))
        XCTAssertFalse(app.staticTexts[notificationBody].exists, "Foreground push was duplicated in app UI")

        XCUIDevice.shared.press(.home)
        try requestPush(scenario: "warm_tap", chatId: chatId)
        try assertGenericSpringBoardNotification()
        springBoard().staticTexts[notificationTitle].tap()
        XCTAssertTrue(chatView(in: app, chatId: chatId).waitForExistence(timeout: notificationTimeout))

        app.terminate()
        try requestPush(scenario: "cold_tap", chatId: chatId)
        try assertGenericSpringBoardNotification()
        springBoard().staticTexts[notificationTitle].tap()
        XCTAssertTrue(chatView(in: app, chatId: chatId).waitForExistence(timeout: notificationTimeout))

        try attemptInlineReplyIfSupported(app: app, chatId: chatId)
        attachScreenshot(named: "Simulator generic notification interaction")
    }

    private func requestPush(scenario: String, chatId: String) throws {
        guard let requestPath = RealAccountTestCredentials.configurationValue(for: "OPENMATES_SIMULATED_PUSH_REQUEST_PATH"),
              let responsePath = RealAccountTestCredentials.configurationValue(for: "OPENMATES_SIMULATED_PUSH_RESPONSE_PATH") else {
            throw XCTSkip("Simulator push helper paths are unavailable")
        }
        let requestId = UUID().uuidString
        let request: [String: String] = [
            "request_id": requestId,
            "scenario": scenario,
            "chat_id": chatId,
        ]
        let requestURL = URL(fileURLWithPath: requestPath)
        try JSONSerialization.data(withJSONObject: request).write(to: requestURL, options: .atomic)

        let deadline = Date().addingTimeInterval(notificationTimeout)
        let responseURL = URL(fileURLWithPath: responsePath)
        repeat {
            if let data = try? Data(contentsOf: responseURL),
               let response = try? JSONSerialization.jsonObject(with: data) as? [String: String],
               response["request_id"] == requestId {
                XCTAssertEqual(response["status"], "injected", "Simulator push injection failed")
                return
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        } while Date() < deadline
        XCTFail("Timed out waiting for simulator push injection")
    }

    private func attemptInlineReplyIfSupported(app: XCUIApplication, chatId: String) throws {
        let capability = RealAccountTestCredentials.configurationValue(for: "OPENMATES_SIMULATOR_INLINE_REPLY") ?? "auto"
        guard capability != "unsupported" else { return }

        // Reply to a different chat after process termination so routing and
        // history loading cannot borrow the currently open transcript.
        RealAccountUITestSupport.openNewChatIfNeeded(app: app)
        app.terminate()
        try requestPush(scenario: "inline_reply", chatId: chatId)
        try assertGenericSpringBoardNotification()

        let springboard = springBoard()
        springboard.staticTexts[notificationTitle].press(forDuration: 1)
        let replyButton = springboard.buttons.matching(
            NSPredicate(format: "label IN %@", ["Click here to respond", "Click to respond", "Reply", "Respond"])
        ).firstMatch
        guard replyButton.waitForExistence(timeout: 3) else {
            if capability == "supported" {
                XCTFail("Simulator was declared inline-reply capable but did not expose Reply")
            }
            return
        }
        replyButton.tap()
        let replyField = springboard.textFields.firstMatch
        XCTAssertTrue(replyField.waitForExistence(timeout: 3))
        let reply = "Which city did I mention? Reply with only the city name."
        replyField.typeText(reply)
        springboard.buttons["Send"].tap()
        app.activate()
        // Inline send does not switch the foreground workspace. Open the target
        // through its notification to inspect the persisted result afterward.
        XCUIDevice.shared.press(.home)
        try requestPush(scenario: "reply_result_tap", chatId: chatId)
        try assertGenericSpringBoardNotification()
        springboard.staticTexts[notificationTitle].tap()
        XCTAssertTrue(
            RealAccountUITestSupport.accessibilityElement(
                in: app,
                identifier: "message-user",
                labelContaining: reply
            ).waitForExistence(timeout: notificationTimeout)
        )
        XCTAssertTrue(chatView(in: app, chatId: chatId).waitForExistence(timeout: notificationTimeout),
                      "Reply must be persisted in its target conversation")
        let assistants = app.otherElements.matching(identifier: "message-assistant")
        let answered = NSPredicate { _, _ in
            assistants.count >= 2 && assistants.element(boundBy: assistants.count - 1).label.contains("Osaka")
        }
        expectation(for: answered, evaluatedWith: nil)
        waitForExpectations(timeout: 90)
        let streaming = app.descendants(matching: .any).matching(identifier: "chat-streaming-banner").firstMatch
        XCTAssertTrue(streaming.waitForNonExistence(timeout: 90))
    }

    private func assertGenericSpringBoardNotification() throws {
        let springboard = springBoard()
        XCTAssertTrue(
            springboard.staticTexts[notificationTitle].waitForExistence(timeout: notificationTimeout),
            "Expected a generic OpenMates notification from the simulated payload"
        )
        XCTAssertTrue(
            springboard.staticTexts[notificationBody].waitForExistence(timeout: 5),
            "Expected the privacy-safe generic notification body"
        )
    }

    private func currentChatId(in app: XCUIApplication) throws -> String {
        let chatView = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", "chat-view-"))
            .firstMatch
        guard chatView.waitForExistence(timeout: notificationTimeout) else {
            throw XCTSkip("A persisted chat view was not available for notification routing")
        }
        return String(chatView.identifier.dropFirst("chat-view-".count))
    }

    private func chatView(in app: XCUIApplication, chatId: String) -> XCUIElement {
        app.descendants(matching: .any)["chat-view-\(chatId)"]
    }

    private func springBoard() -> XCUIApplication {
        XCUIApplication(bundleIdentifier: "com.apple.springboard")
    }

    private func attachScreenshot(named name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
