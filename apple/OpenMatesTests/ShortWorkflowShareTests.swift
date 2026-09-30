// Synthetic public-link fixtures only. No credentials or recipient state.
// Specification: specifications/features/workflows/specification.yml
import XCTest
@testable import OpenMates

@MainActor
final class ShortWorkflowShareTests: XCTestCase {
    private let token = "a8f3kLmN"
    private let shortKey = String(repeating: "A", count: 22)
    // Generated independently by Node WebCrypto with PBKDF2 SHA256/200000,
    // salt omts-v1-a8f3kLmN and nonce bytes 0...11, matching the web protocol.
    private let webCiphertext = "AAECAwQFBgcICQoLXoveq1_KbaiLstq8NZe9eCWpW_sCsm-6v0Se1GfAjVT05g4bISj1S6DU_8WvOexTo7B3kJWtr-zMkesbJ3kVRwH9gl3QS3m-mNFiRfsAcpS29naCwZPBV_CeMURKac4iNmQVETSayeFrYLfTU6bGDHlevXUUZlcuDQy60bStHhs"

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testDurableAndLegacyLinksKeepKeyOutOfRequest() throws {
        let profile = ServerProfile.current()
        for suffix in ["/s/\(token)#\(shortKey)", "/s/#\(token)-\(shortKey)"] {
            let url = try XCTUnwrap(URL(string: profile.webBaseURL.absoluteString + suffix))
            let link = try XCTUnwrap(ShortShareLink.parse(url, selectedDomain: profile.displayDomain))
            XCTAssertEqual(link.token, token)
            XCTAssertEqual(link.fragmentKey, shortKey)
            let requestURL = link.requestURL(apiBaseURL: profile.apiBaseURL)
            XCTAssertEqual(requestURL.path, "/v1/share/short-url/\(token)")
            XCTAssertNil(requestURL.fragment)
            XCTAssertNil(requestURL.query)
            XCTAssertFalse(requestURL.absoluteString.contains(shortKey))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testMalformedHostsPathsAndKeysAreRejectedBeforeFetch() {
        let host = ServerProfile.current().displayDomain
        let rejected = [
            "http://\(host)/s/\(token)#\(shortKey)",
            "https://other.example/s/\(token)#\(shortKey)",
            "https://user@\(host)/s/\(token)#\(shortKey)",
            "https://\(host):443/s/\(token)#\(shortKey)",
            "https://\(host)/s/\(token)/extra#\(shortKey)",
            "https://\(host)/s/tiny#\(shortKey)",
            "https://\(host)/s/\(token)?key=\(shortKey)",
            "https://\(host)/s/\(token)#key=\(shortKey)",
            "https://\(host)/s/\(token)#abc",
        ]
        for text in rejected {
            XCTAssertNil(ShortShareLink.parse(URL(string: text)!, selectedDomain: host))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.content.encrypted-retained
    func testWebCryptoCiphertextDecryptsWithFragmentOnlyKey() async throws {
        let url = try await ShareLinkCrypto.decryptShortURL(webCiphertext, token: token, shortKey: shortKey)
        XCTAssertEqual(url.absoluteString,
            "https://app.dev.openmates.org/share/workflow-template/wt_fixture#key=" + String(repeating: "A", count: 43))
        do {
            _ = try await ShareLinkCrypto.decryptShortURL(webCiphertext, token: token,
                shortKey: String(repeating: "B", count: 22))
            XCTFail("The wrong fragment must not decrypt")
        } catch {}
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testResolvedTemplateRoutesThroughStrictLongLinkParser() async throws {
        let profile = ServerProfile.current()
        let target = profile.webBaseURL.appendingPathComponent("share/workflow-template/wt_fixture")
        let longURL = try ShareLinkCrypto.urlWithFragment(target,
            fragment: "key=" + String(repeating: "A", count: 43))
        let handler = DeepLinkHandler(shortLinkResolver: { link, capturedProfile in
            XCTAssertEqual(link.token, self.token)
            XCTAssertEqual(capturedProfile, profile)
            return longURL
        })
        handler.handle(url: try XCTUnwrap(URL(string: profile.webBaseURL.absoluteString + "/s/\(token)#\(shortKey)")))
        await handler.shortLinkResolutionTask?.value
        XCTAssertEqual(handler.pendingWorkflowTemplate?.templateID, "wt_fixture")
        XCTAssertFalse(handler.pendingShortLinkError)
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testSupersededResolutionCannotReplaceNewerTemplate() async throws {
        let profile = ServerProfile.current()
        let entered = expectation(description: "Public resolution suspended")
        var resume: CheckedContinuation<URL, Never>?
        let handler = DeepLinkHandler(shortLinkResolver: { _, _ in
            await withCheckedContinuation { continuation in
                resume = continuation
                entered.fulfill()
            }
        })
        let fragment = "key=" + String(repeating: "A", count: 43)
        let stale = try ShareLinkCrypto.urlWithFragment(
            profile.webBaseURL.appendingPathComponent("share/workflow-template/wt_stale"), fragment: fragment)
        let current = try ShareLinkCrypto.urlWithFragment(
            profile.webBaseURL.appendingPathComponent("share/workflow-template/wt_current"), fragment: fragment)
        handler.handle(url: try XCTUnwrap(URL(string: profile.webBaseURL.absoluteString + "/s/\(token)#\(shortKey)")))
        let firstTask = handler.shortLinkResolutionTask
        await fulfillment(of: [entered], timeout: 2)
        handler.handle(url: current)
        resume?.resume(returning: stale)
        await firstTask?.value
        XCTAssertEqual(handler.pendingWorkflowTemplate?.templateID, "wt_current")
        XCTAssertFalse(handler.pendingShortLinkError)
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testDecryptedCrossHostTargetIsRejected() async throws {
        let profile = ServerProfile.current()
        let target = URL(string: "https://other.example/share/workflow-template/wt_fixture#key=" + String(repeating: "A", count: 43))!
        let handler = DeepLinkHandler(shortLinkResolver: { _, _ in target })
        handler.handle(url: try XCTUnwrap(URL(string: profile.webBaseURL.absoluteString + "/s/\(token)#\(shortKey)")))
        await handler.shortLinkResolutionTask?.value
        XCTAssertNil(handler.pendingWorkflowTemplate)
        XCTAssertTrue(handler.pendingShortLinkError)
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testFailedNewShortLinkClearsTemplateWaitingForLogin() async throws {
        let profile = ServerProfile.current()
        let handler = DeepLinkHandler(shortLinkResolver: { _, _ in
            throw ShareLinkCryptoError.invalidShortURL
        })
        let previous = try ShareLinkCrypto.urlWithFragment(
            profile.webBaseURL.appendingPathComponent("share/workflow-template/wt_previous"),
            fragment: "key=" + String(repeating: "A", count: 43))
        handler.handle(url: previous)
        XCTAssertEqual(handler.pendingWorkflowTemplate?.templateID, "wt_previous")
        handler.handle(url: try XCTUnwrap(URL(string: profile.webBaseURL.absoluteString + "/s/\(token)#\(shortKey)")))
        await handler.shortLinkResolutionTask?.value
        XCTAssertNil(handler.pendingWorkflowTemplate,
                     "Completing login must not reopen an invitation superseded by a failed link")
        XCTAssertTrue(handler.pendingShortLinkError)
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testInAppLinkPolicyHandlesSelectedHostSharesOnly() throws {
        let profile = ServerProfile.current()
        let short = try XCTUnwrap(URL(string: profile.webBaseURL.absoluteString + "/s/\(token)#\(shortKey)"))
        let template = try ShareLinkCrypto.urlWithFragment(
            profile.webBaseURL.appendingPathComponent("share/workflow-template/wt_fixture"),
            fragment: "key=" + String(repeating: "A", count: 43))
        XCTAssertTrue(DeepLinkHandler.shouldHandleInApp(short, selectedDomain: profile.displayDomain))
        XCTAssertTrue(DeepLinkHandler.shouldHandleInApp(template, selectedDomain: profile.displayDomain))
        XCTAssertFalse(DeepLinkHandler.shouldHandleInApp(
            profile.webBaseURL.appendingPathComponent("legal/privacy"), selectedDomain: profile.displayDomain))
        XCTAssertFalse(DeepLinkHandler.shouldHandleInApp(short, selectedDomain: "other.example"))
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testResolvedChatAndEmbedSharesKeepOriginalShortURLForBrowser() async throws {
        let profile = ServerProfile.current()
        let original = try XCTUnwrap(URL(string: profile.webBaseURL.absoluteString + "/s/\(token)#\(shortKey)"))
        for target in [
            profile.webBaseURL.appendingPathComponent("share/chat/public_chat"),
            profile.webBaseURL.appendingPathComponent("share/embed/public_embed"),
            try ShareLinkCrypto.urlWithFragment(profile.webBaseURL, fragment: "share-chat-id=public_chat&key=public"),
        ] {
            let handler = DeepLinkHandler(shortLinkResolver: { _, _ in target })
            handler.handle(url: original)
            await handler.shortLinkResolutionTask?.value
            XCTAssertEqual(handler.pendingSharedBrowserURL, original)
            XCTAssertNil(handler.pendingWorkflowTemplate)
            XCTAssertFalse(handler.pendingShortLinkError)
            handler.clearPending()
            XCTAssertNil(handler.pendingSharedBrowserURL)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testNonShareDecryptedURLCannotOpenBrowser() async throws {
        let profile = ServerProfile.current()
        let handler = DeepLinkHandler(shortLinkResolver: { _, _ in
            profile.webBaseURL.appendingPathComponent("settings")
        })
        handler.handle(url: try XCTUnwrap(URL(string: profile.webBaseURL.absoluteString + "/s/\(token)#\(shortKey)")))
        await handler.shortLinkResolutionTask?.value
        XCTAssertNil(handler.pendingSharedBrowserURL)
        XCTAssertTrue(handler.pendingShortLinkError)
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testUntrustedUniversalLinkCannotRouteIntoCurrentAccount() {
        let handler = DeepLinkHandler()
        handler.handle(url: URL(string: "https://other.example/#chat-id=untrusted")!)
        XCTAssertNil(handler.pendingChatId)
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries
    func testKnownOtherProfileShareOpensBrowserWithoutCurrentAccountAPI() throws {
        let profile = ServerProfile.current()
        let otherHost = profile.displayDomain == "app.dev.openmates.org" ? "openmates.org" : "app.dev.openmates.org"
        let short = try XCTUnwrap(URL(string: "https://\(otherHost)/s/\(token)#\(shortKey)"))
        let template = try XCTUnwrap(URL(string: "https://\(otherHost)/share/workflow-template/wt_fixture#key=" + String(repeating: "A", count: 43)))
        let handler = DeepLinkHandler(shortLinkResolver: { _, _ in
            XCTFail("Other-profile public shares must not use the selected account API")
            throw ShareLinkCryptoError.invalidShortURL
        })
        for url in [short, template] {
            XCTAssertTrue(DeepLinkHandler.shouldInterceptShareURL(url, selectedDomain: profile.displayDomain))
            handler.handle(url: url)
            XCTAssertEqual(handler.pendingSharedBrowserURL, url)
            XCTAssertNil(handler.pendingWorkflowTemplate)
            XCTAssertNil(handler.shortLinkResolutionTask)
            XCTAssertFalse(handler.pendingShortLinkError)
        }
        let untrusted = URL(string: "https://other.example/s/\(token)#\(shortKey)")!
        XCTAssertFalse(DeepLinkHandler.shouldInterceptShareURL(untrusted, selectedDomain: profile.displayDomain))
    }
}
