// Simulator coverage for background chat notification behavior.
// The host helper injects generic server-shaped payloads only after this test
// requests a named scenario. APNs provider delivery, device-token registration,
// notification-extension keychain access, and unread-store observability remain
// external to Simulator coverage. Credentials and chat identifiers are never logged.

import Foundation
import XCTest

@MainActor
final class BackgroundChatNotificationUITests: XCTestCase {
    private let notificationTitle = "OpenMates"
    private let notificationBody = "New message received"
    private let markerPrompt = "Simulator notification interaction coverage"
    private let notificationTimeout: TimeInterval = 30

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: direct surface=gui.apple assertions=apple-notifications.payload.privacy-safe,apple-notifications.action.routing-coherent,apple-notifications.delivery.idempotent-visible
    func testSimulatorNotificationInteractions() throws {
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp()

        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        RealAccountUITestSupport.sendWelcomePrompt(app: app, prompt: markerPrompt)
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
        guard let requestPath = ProcessInfo.processInfo.environment["OPENMATES_SIMULATED_PUSH_REQUEST_PATH"],
              let responsePath = ProcessInfo.processInfo.environment["OPENMATES_SIMULATED_PUSH_RESPONSE_PATH"] else {
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
        let capability = ProcessInfo.processInfo.environment["OPENMATES_SIMULATOR_INLINE_REPLY"] ?? "auto"
        guard capability != "unsupported" else { return }

        XCUIDevice.shared.press(.home)
        try requestPush(scenario: "inline_reply", chatId: chatId)
        try assertGenericSpringBoardNotification()

        let springboard = springBoard()
        springboard.staticTexts[notificationTitle].press(forDuration: 1)
        let replyButton = springboard.buttons["Reply"]
        guard replyButton.waitForExistence(timeout: 3) else {
            if capability == "supported" {
                XCTFail("Simulator was declared inline-reply capable but did not expose Reply")
            }
            return
        }
        replyButton.tap()
        let replyField = springboard.textFields.firstMatch
        XCTAssertTrue(replyField.waitForExistence(timeout: 3))
        replyField.typeText("Simulator inline reply")
        springboard.buttons["Send"].tap()
        app.activate()
        XCTAssertTrue(
            RealAccountUITestSupport.accessibilityElement(
                in: app,
                identifier: "message-user",
                labelContaining: "Simulator inline reply"
            ).waitForExistence(timeout: notificationTimeout)
        )
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
