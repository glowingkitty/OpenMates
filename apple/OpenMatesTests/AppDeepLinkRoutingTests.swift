import XCTest
@testable import OpenMates

@MainActor
final class AppDeepLinkRoutingTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testEncryptedChatShareUsesNativeRecipientWithoutOwnerRouting() throws {
        let handler = DeepLinkHandler(shortLinkResolver: { _, _ in
            XCTFail("A long chat share must not use short-link resolution")
            throw ShareLinkCryptoError.invalidShortURL
        })
        for host in ["openmates.org", "app.openmates.org", "app.dev.openmates.org"] {
            let url = try XCTUnwrap(URL(string: "https://\(host)/share/chat/synthetic_shared#key=synthetic_blob&messageid=synthetic_message"))
            XCTAssertTrue(DeepLinkHandler.shouldInterceptAppURL(url, selectedDomain: ServerProfile.current().displayDomain))
            handler.handle(url: url)
            XCTAssertEqual(handler.pendingSharedChatURL, url)
            XCTAssertNil(handler.pendingSharedBrowserURL)
            XCTAssertNil(handler.pendingChatId)
            XCTAssertNil(handler.pendingShareChatId)
            XCTAssertNil(handler.shortLinkResolutionTask)
            handler.clearPending()
            XCTAssertNil(handler.pendingSharedChatURL)
        }
        for url in ["https://app.dev.openmates.org.evil.example/share/chat/x#key=x",
                    "http://app.dev.openmates.org/share/chat/x#key=x",
                    "https://user:secret@app.dev.openmates.org/share/chat/x#key=x"] {
            XCTAssertFalse(DeepLinkHandler.isNativeChatShareURL(try XCTUnwrap(URL(string: url))))
        }
    }
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
