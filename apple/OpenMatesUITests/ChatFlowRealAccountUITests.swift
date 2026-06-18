// Live UI coverage for the native chat flow.
// Mirrors the core web chat-flow.spec.ts path for a real account and covers the
// signed-out anonymous free-usage path from the welcome composer. Real-account
// credentials are read only from the test process environment and are never
// logged or committed.

import Foundation
import XCTest

@MainActor
final class ChatFlowRealAccountUITests: XCTestCase {
    private let markerPrompt = "Kyoto and Osaka quick tip test"
    private let anonymousPrompt = "Anonymous native smoke test: answer with one short sentence."
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

    func testSignedOutAnonymousWelcomePromptCreatesChatAndReceivesAssistantResponse() throws {
        try requireAnonymousFreeUsageActive()

        let app = RealAccountUITestSupport.launchApp(
            preferPasswordLogin: false,
            disableAuthCache: true,
            extraArguments: ["--ui-test-start-new-chat"]
        )

        XCTAssertTrue(app.buttons["login-signup-button"].waitForExistence(timeout: 15))
        RealAccountUITestSupport.sendWelcomePrompt(app: app, prompt: anonymousPrompt)
        RealAccountUITestSupport.assertAssistantResponds(app: app, timeout: assistantResponseTimeout)
    }

    private func requireAnonymousFreeUsageActive() throws {
        let url = URL(string: "https://api.dev.openmates.org/v1/anonymous/free-usage/status")!
        let semaphore = DispatchSemaphore(value: 0)
        var probeResult: Result<AnonymousFreeUsageProbe, Error>?

        URLSession.shared.dataTask(with: url) { data, _, error in
            defer { semaphore.signal() }
            if let error {
                probeResult = .failure(error)
                return
            }
            guard let data else {
                probeResult = .failure(URLError(.badServerResponse))
                return
            }
            probeResult = Result { try JSONDecoder().decode(AnonymousFreeUsageProbe.self, from: data) }
        }.resume()

        guard semaphore.wait(timeout: .now() + 10) == .success else {
            throw XCTSkip("Anonymous free usage status probe timed out")
        }

        let status = try probeResult?.get() ?? AnonymousFreeUsageProbe(active: false, reason: "missing_status")
        guard status.active else {
            throw XCTSkip("Anonymous free usage inactive on dev: \(status.reason ?? "unknown")")
        }
    }
}

private struct AnonymousFreeUsageProbe: Decodable {
    let active: Bool
    let reason: String?
}
