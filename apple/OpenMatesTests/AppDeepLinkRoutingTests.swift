import XCTest
@testable import OpenMates

@MainActor
final class AppDeepLinkRoutingTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMessageLinkPrefillsDraftWithoutSendingAndSettingsRemainNative() throws {
        let host = ServerProfile.current().displayDomain
        let handler = DeepLinkHandler()
        let message = try XCTUnwrap(URL(string: "https://\(host)/#message=Compare%20API%20costs%20%26%20subscriptions"))
        XCTAssertTrue(DeepLinkHandler.shouldInterceptAppURL(message, selectedDomain: host))
        handler.handle(url: message)
        XCTAssertEqual(handler.pendingMessageText, "Compare API costs & subscriptions")
        XCTAssertFalse(handler.pendingNewChat)
        handler.clearPending()
        handler.handle(url: try XCTUnwrap(URL(string: "https://\(host)/#settings/privacy")))
        XCTAssertEqual(handler.pendingSettingsPath, "privacy")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMarketingDocsAndForeignProfilesRetainWebsiteRouting() throws {
        for path in ["/news", "/docs/getting-started", "/privacy"] {
            let url = try XCTUnwrap(URL(string: "https://app.dev.openmates.org\(path)"))
            XCTAssertFalse(DeepLinkHandler.shouldInterceptAppURL(url, selectedDomain: "app.dev.openmates.org"))
        }
        XCTAssertFalse(DeepLinkHandler.shouldInterceptAppURL(
            try XCTUnwrap(URL(string: "https://app.openmates.org/#chat-id=synthetic")), selectedDomain: "app.dev.openmates.org"))
        XCTAssertFalse(DeepLinkHandler.shouldInterceptAppURL(
            try XCTUnwrap(URL(string: "https://app.dev.openmates.org.evil.example/#message=hello")), selectedDomain: "app.dev.openmates.org"))
    }
}
