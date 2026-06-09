// Real-account UI coverage for the native chat flow.
// Mirrors the core web chat-flow.spec.ts path: password + OTP login, create a
// new chat from the welcome composer, send the Kyoto/Osaka marker prompt, and
// verify that an assistant response starts and resolves in the real app.
// Credentials are read only from the test process environment and are never
// logged or committed.

import XCTest

@MainActor
final class ChatFlowRealAccountUITests: XCTestCase {
    private let markerPrompt = "Kyoto and Osaka quick tip test"
    private let assistantResponseTimeout: TimeInterval = 90

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testPasswordOtpLoginCreatesChatAndReceivesAssistantResponse() throws {
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp()

        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        RealAccountUITestSupport.sendWelcomePrompt(app: app, prompt: markerPrompt)
        RealAccountUITestSupport.assertAssistantResponds(app: app, timeout: assistantResponseTimeout)
    }
}
