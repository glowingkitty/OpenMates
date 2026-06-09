// Simulator coverage for background chat notification behavior.
// This does not prove real APNs delivery; it verifies the best simulator-backed
// contract available without a paid Apple Developer account: after a real chat
// send, pressing Home still lets the native background completion path schedule
// a privacy-preserving local OS notification when the assistant response lands.
// Credentials are read only from the XCTest process environment.

import XCTest

@MainActor
final class BackgroundChatNotificationUITests: XCTestCase {
    private let markerPrompt = "Background notification Kyoto Osaka test"
    private let notificationTimeout: TimeInterval = 120

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testBackgroundChatCompletionShowsLocalNotification() throws {
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp()

        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        RealAccountUITestSupport.sendWelcomePrompt(app: app, prompt: markerPrompt)

        XCUIDevice.shared.press(.home)

        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let notificationTitle = springboard.staticTexts["OpenMates"]
        let notificationBody = springboard.staticTexts["New message received"]

        XCTAssertTrue(
            notificationTitle.waitForExistence(timeout: notificationTimeout),
            "Expected an OpenMates local notification after background assistant completion"
        )
        XCTAssertTrue(
            notificationBody.waitForExistence(timeout: 5),
            "Expected the generic privacy-preserving notification body"
        )

        let screenshot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = "Background chat local notification"
        attachment.lifetime = .keepAlways
        add(attachment)

        notificationTitle.tap()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 15))
        XCTAssertNotNil(RealAccountUITestSupport.waitForMessageEditor(in: app, timeout: 20))
    }
}
