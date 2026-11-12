// Swift transports that keep their own cookie handling after the Rust core
// took over app REST: the Watch session transport and the upload host. App
// REST through the core: APIClient+CoreTransport.swift.
import XCTest
@testable import OpenMates

@MainActor final class NativeSessionTransportTests: XCTestCase {
    private var session: URLSession!
    private var cookieStorage: HTTPCookieStorage!
    private var api: APIClient!
    private var originalServerConfiguration: ServerEndpointConfiguration!
    private var auth: AuthManager?
    private let profile = ServerProfile.custom(domain: "native-session-transport.example")

    override func setUp() async throws {
        originalServerConfiguration = ServerConfiguration.current
        ServerConfiguration.current = ServerEndpointConfiguration(
            selectedDomain: "native-session-transport.example", customDomains: ["native-session-transport.example"])
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [NativeSessionURLProtocol.self]
        cookieStorage = try XCTUnwrap(configuration.httpCookieStorage)
        configuration.httpShouldSetCookies = true
        session = URLSession(configuration: configuration)
        api = APIClient(session: session, uploadSession: session, cookieStorage: cookieStorage)
        cookieStorage.setCookie(try cookie("retained-refresh"))
    }

    override func tearDown() async throws {
        session.invalidateAndCancel()
        NativeSessionURLProtocol.setHandler(nil)
        auth = nil
        ServerConfiguration.current = originalServerConfiguration
        api = nil
        session = nil
        cookieStorage = nil
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send,storage.privacy.ciphertext-boundary
    func testEmbedReferenceAvailabilityBoundsAndExactMetadataBijection() throws {
        let ids = (0..<45).map { "fixture-\($0)" }
        let batches = try APIClient.embedReferenceAvailabilityBatches(ids)
        XCTAssertEqual(batches.map(\.count), [20, 20, 5])
        XCTAssertEqual(batches.flatMap { $0 }, ids)
        let longIDs = (0..<20).map { "\($0)-" + String(repeating: "x", count: 480) }
        let byteBatches = try APIClient.embedReferenceAvailabilityBatches(longIDs)
        XCTAssertGreaterThan(byteBatches.count, 1)
        for batch in byteBatches { XCTAssertLessThanOrEqual(try APIClient.embedReferenceAvailabilityBody(batch).count, 4096) }
        let unicodeIDs = (0..<20).map { "\($0)-" + String(repeating: "é", count: 200) }
        for batch in try APIClient.embedReferenceAvailabilityBatches(unicodeIDs) {
            let body = try APIClient.embedReferenceAvailabilityBody(batch)
            XCTAssertTrue(body.allSatisfy { $0 < 128 })
            XCTAssertLessThanOrEqual(body.count, 4096)
            let decoded = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: [String]])
            XCTAssertEqual(decoded["embed_ids"], batch)
        }
        XCTAssertThrowsError(try APIClient.embedReferenceAvailabilityBatches(["same", "same"]))
        XCTAssertThrowsError(try APIClient.embedReferenceAvailabilityBatches([String(repeating: "x", count: 513)]))
        let valid = Data(#"{"results":[{"embed_id":"b","state":"unusable"},{"embed_id":"a","state":"ready"}]}"#.utf8)
        XCTAssertEqual(try APIClient.decodeEmbedReferenceAvailability(valid, requestedIDs: ["a", "b"]),
            ["a": .ready, "b": .unusable])
        for invalid in [
            #"{"results":[]}"#,
            #"{"results":[{"embed_id":"a","state":"ready"},{"embed_id":"a","state":"ready"}]}"#,
            #"{"results":[{"embed_id":"a","state":"ready"},{"embed_id":"other","state":"ready"}]}"#,
            #"{"results":[{"embed_id":"a","state":"unknown"},{"embed_id":"b","state":"missing"}]}"#,
            #"{"results":[{"embed_id":"a","state":"ready","encrypted_content":"forbidden"},{"embed_id":"b","state":"missing"}]}"#
        ] { XCTAssertThrowsError(try APIClient.decodeEmbedReferenceAvailability(Data(invalid.utf8), requestedIDs: ["a", "b"])) }
        XCTAssertThrowsError(try APIClient.decodeEmbedReferenceAvailability(Data(repeating: 32, count: 8193), requestedIDs: ["a"]))
        let teamPath = try APIClient.embedReferenceAvailabilityPath(chatID: "fixture-chat", teamID: "team+a&b")
        let teamURL = try XCTUnwrap(URLComponents(string: "https://example.invalid" + teamPath))
        XCTAssertEqual(teamURL.path, "/v1/embeds/chats/fixture-chat/references/availability")
        XCTAssertEqual(teamURL.queryItems, [URLQueryItem(name: "team_id", value: "team+a&b")])
        XCTAssertThrowsError(try APIClient.embedReferenceAvailabilityPath(chatID: "fixture/other", teamID: nil))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send,auth.session.isolation
    func testEmbedReferenceAvailabilityUsesPinnedPersonalRequestAndRejectsDelayedAccountChange() async throws {
        try authenticate()
        let scope = OfflineStore.shared.scopeGeneration
        let team = TeamWorkspaceContext.shared.snapshot
        let origin = profile.webBaseURL.absoluteString
        NativeSessionURLProtocol.setHandler { request in
            XCTAssertEqual(request.url?.path, "/v1/embeds/chats/fixture-chat/references/availability")
            XCTAssertEqual(request.httpMethod, "POST")
            return .init(status: 200, body: Data(#"{"results":[{"embed_id":"fixture-embed","state":"ready"}]}"#.utf8))
        }
        let ready = try await api.embedReferenceAvailability(chatID: "fixture-chat", embedIDs: ["fixture-embed"],
            serverProfile: profile, expectedAccountID: "account-A", expectedScope: scope,
            expectedTeamContext: APIRequestTeamContext(epoch: team.epoch, teamID: team.teamID))
        XCTAssertEqual(ready, ["fixture-embed": .ready])
        let gate = NativeSessionResponseGate()
        NativeSessionURLProtocol.setHandler { request in
            XCTAssertEqual(request.url?.path, "/v1/embeds/chats/fixture-chat/references/availability")
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Origin"), origin)
            return .init(status: 200, body: Data(#"{"results":[{"embed_id":"fixture-embed","state":"ready"}]}"#.utf8), gate: gate)
        }
        let operation = Task {
            try await api.embedReferenceAvailability(chatID: "fixture-chat", embedIDs: ["fixture-embed"],
                serverProfile: profile, expectedAccountID: "account-A", expectedScope: scope,
                expectedTeamContext: APIRequestTeamContext(epoch: team.epoch, teamID: team.teamID))
        }
        await gate.waitUntilHeld()
        auth?.currentUser = nil
        auth?.state = .unauthenticated
        gate.release()
        do { _ = try await operation.value; XCTFail("An old account receipt must be rejected") }
        catch { XCTAssertTrue(error is CancellationError) }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.audio-reply,apple-watch.pairing.private-session
    func testWatchAudioTranscriptionUsesVersionedServiceWithVerifiedCookieAndOrigin() async throws {
        let context = WatchChatRequestContext(accountID: "account-A", profile: profile,
            accountGeneration: WatchChatAccountLifecycle.generation, deadline: { _ in 100 }, now: { 1 })
        let origin = profile.webBaseURL.absoluteString
        NativeSessionURLProtocol.setHandler { request in
            XCTAssertEqual(request.url?.path, "/v1/apps/audio/skills/transcribe")
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Origin"), origin)
            XCTAssertFalse(request.httpShouldHandleCookies)
            XCTAssertTrue(request.value(forHTTPHeaderField: "Cookie")?.contains("retained-refresh") == true)
            return .init(status: 200, body: Data(#"{"data":{"results":[{"results":[]}]}}"#.utf8), cookie: nil)
        }
        let upload = WatchUploadedAudio(embedId: "fixture-audio", filename: "fixture.m4a", contentType: "audio/mp4",
            contentHash: nil, files: ["original": .init(s3Key: "fixture-original", sizeBytes: 3, width: nil, height: nil, format: "m4a")],
            s3BaseUrl: "https://files.example.invalid", aesKey: "fixture-key", aesNonce: "fixture-nonce", vaultWrappedAesKey: "fixture-wrapped")
        let result = try await api.transcribeAudioRecording(upload, chatId: "fixture-chat", context: context)
        XCTAssertNil(result)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,auth.session.isolation
    func testVerifiedWatchRequestPublishesRenewalUnderItsOwnFence() async throws {
        NativeSessionURLProtocol.setHandler { request in
            XCTAssertEqual(request.httpMethod, "PATCH")
            XCTAssertFalse(request.httpShouldHandleCookies)
            XCTAssertTrue(request.value(forHTTPHeaderField: "Cookie")?.contains("retained-refresh") == true)
            XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "application/json")
            return .init(status: 200, body: Data("{}".utf8), cookie: "watch-renewal")
        }
        let _: Data = try await api.requestForVerifiedWatchSession(.patch, path: "/v1/tasks/fixture",
            serverProfile: profile, body: ["status": "done"]) { }
        XCTAssertEqual(refreshCookie, "watch-renewal")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation
    func testVerifiedWatchResponseCannotPublishAfterSelectionAuthorityExpires() async throws {
        let authority = AuthorityFence()
        NativeSessionURLProtocol.setHandler { _ in
            .init(status: 200, body: Data("{}".utf8), cookie: "stale-watch-renewal")
        }
        do {
            let _: Data = try await api.requestForVerifiedWatchSession(.get, path: "/v1/workflows/fixture",
                serverProfile: profile) {
                guard authority.isCurrent() else { throw CancellationError() }
            }
            XCTFail("Stale Watch response was admitted")
        } catch is CancellationError {}
        XCTAssertEqual(authority.checks, 2)
        XCTAssertEqual(refreshCookie, "retained-refresh")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,apple-watch.pairing.private-session
    func testWatchSessionServiceAcceptsCachedOwnerRenewalForNextChatRequest() async throws {
        let context = watchContext()
        let payload = response(account: "account-A", token: "watch-socket")
        NativeSessionURLProtocol.setHandler { request in
            XCTAssertFalse(request.httpShouldHandleCookies)
            return .init(status: 200, body: payload, cookie: "watch-session-renewal")
        }
        let result = try await WatchSessionTransport.loadSession(api: api,
            body: SessionRequest(sessionId: "fixture-watch-session", deviceInfo: nil), context: context)
        XCTAssertEqual(result.user?.id, "account-A")
        XCTAssertEqual(result.wsToken, "watch-socket")
        XCTAssertEqual(refreshCookie, "watch-session-renewal")
        NativeSessionURLProtocol.setHandler { request in
            XCTAssertTrue(request.value(forHTTPHeaderField: "Cookie")?.contains("watch-session-renewal") == true)
            return .init(status: 200, body: Data(#"{"chats":[]}"#.utf8))
        }
        let chats = try await api.fetchRecentChats(limit: 20, offset: 0, context: context)
        XCTAssertTrue(chats.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation,apple-watch.pairing.private-session
    func testWatchSessionServiceRejectsDifferentResponseOwnerBeforeCookiePublication() async throws {
        let context = watchContext()
        let payload = response(account: "account-B", token: "wrong-owner-socket")
        NativeSessionURLProtocol.setHandler { _ in
            .init(status: 200, body: payload, cookie: "wrong-owner-refresh")
        }
        do {
            _ = try await WatchSessionTransport.loadSession(api: api,
                body: SessionRequest(sessionId: "fixture-watch-session", deviceInfo: nil), context: context)
            XCTFail("Different session owner was admitted")
        } catch is CancellationError {}
        XCTAssertEqual(refreshCookie, "retained-refresh")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation,apple-watch.pairing.private-session
    func testHeldWatchSessionServiceResponseCannotPublishAfterAccountLifecycleChange() async throws {
        let context = watchContext()
        let gate = NativeSessionResponseGate()
        let payload = response(account: "account-A", token: "stale-watch-socket")
        NativeSessionURLProtocol.setHandler { _ in
            .init(status: 200, body: payload, cookie: "stale-watch-session", gate: gate)
        }
        let operation = Task {
            try await WatchSessionTransport.loadSession(api: api,
                body: SessionRequest(sessionId: "fixture-watch-session", deviceInfo: nil), context: context)
        }
        await gate.waitUntilHeld()
        WatchChatAccountLifecycle.invalidate()
        cookieStorage.setCookie(try cookie("replacement-watch-session"))
        gate.release()
        do { _ = try await operation.value; XCTFail("Stale Watch session was admitted") }
        catch is CancellationError {}
        XCTAssertEqual(refreshCookie, "replacement-watch-session")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open,apple-watch.pairing.private-session
    func testHeldWatchChatServiceResponseCannotPublishCookieOrDataAfterDeadline() async throws {
        let clock = WatchFixtureClock()
        let context = WatchChatRequestContext(accountID: "account-A", profile: profile,
            accountGeneration: WatchChatAccountLifecycle.generation, deadline: { _ in 21 }, now: { clock.now })
        let gate = NativeSessionResponseGate()
        NativeSessionURLProtocol.setHandler { request in
            XCTAssertFalse(request.httpShouldHandleCookies)
            return .init(status: 200, body: Data(#"{"chats":[]}"#.utf8), cookie: "expired-watch-renewal", gate: gate)
        }
        let operation = Task { try await api.fetchRecentChats(limit: 20, offset: 0, context: context) }
        await gate.waitUntilHeld()
        clock.now = 21
        gate.release()
        do { _ = try await operation.value; XCTFail("Expired Watch chat data was admitted") }
        catch is CancellationError {}
        XCTAssertEqual(refreshCookie, "retained-refresh")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open,auth.session.isolation
    func testWatchMessageServiceRetainsOriginScopeBeforeAPIActorDispatch() async throws {
        let context = watchContext()
        WatchChatAccountLifecycle.invalidate()
        NativeSessionURLProtocol.setHandler { _ in
            XCTFail("Stale originating scope must never dispatch")
            return .init(status: 200, body: Data("[]".utf8))
        }
        do {
            _ = try await api.fetchMessages(chatId: "fixture-chat", context: context)
            XCTFail("Origin scope was recaptured after the API actor hop")
        } catch is CancellationError {}
        XCTAssertEqual(refreshCookie, "retained-refresh")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.audio-reply,auth.session.isolation
    func testHeldWatchAudioUploadServiceCannotPublishAfterLifecycleChange() async throws {
        let context = watchContext()
        let gate = NativeSessionResponseGate()
        let uploadHost = profile.uploadBaseURL.host
        NativeSessionURLProtocol.setHandler { request in
            XCTAssertEqual(request.url?.host, uploadHost)
            XCTAssertFalse(request.httpShouldHandleCookies)
            XCTAssertTrue(request.value(forHTTPHeaderField: "Cookie")?.contains("retained-refresh") == true)
            XCTAssertTrue(request.value(forHTTPHeaderField: "Content-Type")?.hasPrefix("multipart/form-data") == true)
            return .init(status: 200, body: Data("{}".utf8), cookie: "stale-audio-renewal", gate: gate)
        }
        let operation = Task {
            try await api.uploadAudioRecording(data: Data("fixture-audio".utf8), filename: "fixture.m4a",
                chatId: "fixture-chat", context: context)
        }
        await gate.waitUntilHeld()
        WatchChatAccountLifecycle.invalidate()
        gate.release()
        do { _ = try await operation.value; XCTFail("Stale upload response was admitted") }
        catch is CancellationError {}
        XCTAssertEqual(refreshCookie, "retained-refresh")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,auth.session.isolation
    func testHostOnlyUploadRenewalReconcilesAPIAndUploadAliasesForNextRequests() async throws {
        try await exerciseUploadRenewal(profile: .production, responseDomain: nil)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,auth.session.isolation
    func testParentDomainUploadRenewalPreservesAttributesAndRetiresHostOnlyAliases() async throws {
        try await exerciseUploadRenewal(profile: .production, responseDomain: ".openmates.org")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,auth.session.isolation
    func testSameHostUploadRenewalReconcilesOverlappingParentAlias() async throws {
        try await exerciseUploadRenewal(profile: profile, responseDomain: nil)
    }

    private func exerciseUploadRenewal(profile transportProfile: ServerProfile, responseDomain: String?) async throws {
        try seedUploadAliases(profile: transportProfile)
        NativeSessionURLProtocol.setHandler { request in
            XCTAssertEqual(request.url?.host, transportProfile.uploadBaseURL.host)
            XCTAssertFalse(request.httpShouldHandleCookies)
            Self.assertOnlyRefresh("authority-A", in: request)
            return .init(status: 200, body: Data(), cookie: "successor-B", maxAge: 1800, cookieDomain: responseDomain)
        }
        _ = try await api.uploadFileForVerifiedWatchSession(data: Data("fixture".utf8), filename: "fixture.m4a",
            contentType: "audio/mp4", chatId: "fixture-chat", serverProfile: transportProfile, validate: {})
        let apiCookie = try XCTUnwrap(cookieStorage.cookies(for: transportProfile.apiBaseURL)?
            .first { $0.name == "auth_refresh_token" })
        let uploadCookie = try XCTUnwrap(cookieStorage.cookies(for: transportProfile.uploadBaseURL)?
            .first { $0.name == "auth_refresh_token" })
        XCTAssertEqual(apiCookie.value, "successor-B")
        XCTAssertEqual(uploadCookie.value, "successor-B")
        XCTAssertTrue(apiCookie.isSecure)
        XCTAssertTrue(apiCookie.isHTTPOnly)
        XCTAssertEqual(apiCookie.path, uploadCookie.path)
        XCTAssertEqual(apiCookie.expiresDate!.timeIntervalSince1970, uploadCookie.expiresDate!.timeIntervalSince1970, accuracy: 1)
        XCTAssertEqual(apiCookie.properties?[HTTPCookiePropertyKey(rawValue: "SameSite")] as? String,
                       uploadCookie.properties?[HTTPCookiePropertyKey(rawValue: "SameSite")] as? String)
        if responseDomain == nil { XCTAssertEqual(apiCookie.domain, transportProfile.apiBaseURL.host) }
        else { XCTAssertEqual(apiCookie.domain, responseDomain) }
        try await assertNextAPIAndUploadUse("successor-B", profile: transportProfile)
        XCTAssertEqual(cookieStorage.cookies(for: URL(string: "https://unrelated-cookie.example")!)?
            .first { $0.name == "auth_refresh_token" }?.value, "unrelated-session")
        XCTAssertTrue(cookieStorage.cookies(for: transportProfile.apiBaseURL)?.contains { $0.name == "fixture_preference" } == true)
    }

    private func seedUploadAliases(profile transportProfile: ServerProfile) throws {
        ServerConfiguration.current = transportProfile.endpointConfiguration
        let parent = transportProfile.id == "production" ? ".openmates.org" : ".native-session-transport.example"
        // Install parent after API host alias to prove deterministic API authority
        // instead of relying on the jar's unspecified enumeration order.
        cookieStorage.setCookie(try scopedCookie("authority-A", domain: transportProfile.apiBaseURL.host!))
        cookieStorage.setCookie(try scopedCookie("stale-upload-X", domain: transportProfile.uploadBaseURL.host!))
        // Same-host profiles share one cell; reinstate that profile's API owner.
        if transportProfile.apiBaseURL.host == transportProfile.uploadBaseURL.host {
            cookieStorage.setCookie(try scopedCookie("authority-A", domain: transportProfile.apiBaseURL.host!))
        }
        cookieStorage.setCookie(try scopedCookie("stale-parent-X", domain: parent))
        cookieStorage.setCookie(try scopedCookie("keep-preference", domain: parent, name: "fixture_preference"))
        cookieStorage.setCookie(try scopedCookie("unrelated-session", domain: "unrelated-cookie.example"))
    }

    private func assertNextAPIAndUploadUse(_ value: String, profile transportProfile: ServerProfile) async throws {
        NativeSessionURLProtocol.setHandler { request in
            Self.assertOnlyRefresh(value, in: request)
            return .init(status: 200, body: Data())
        }
        let _: Data = try await api.requestForVerifiedWatchSession(.get, path: "/v1/chats",
            serverProfile: transportProfile, validate: {})
        _ = try await api.uploadFileForVerifiedWatchSession(data: Data("fixture".utf8), filename: "fixture.m4a",
            contentType: "audio/mp4", chatId: "fixture-chat", serverProfile: transportProfile, validate: {})
    }

    nonisolated private static func assertOnlyRefresh(_ value: String, in request: URLRequest) {
        let headers = (request.value(forHTTPHeaderField: "Cookie") ?? "").split(separator: ";")
            .map { $0.trimmingCharacters(in: .whitespaces) }.filter { $0.hasPrefix("auth_refresh_token=") }
        XCTAssertEqual(headers, ["auth_refresh_token=\(value)"])
    }

    private func scopedCookie(_ value: String, domain: String, name: String = "auth_refresh_token") throws -> HTTPCookie {
        try XCTUnwrap(HTTPCookie(properties: [.name: name, .value: value, .domain: domain,
            .path: "/", .secure: "TRUE", .expires: Date().addingTimeInterval(3600)]))
    }

    private func watchContext() -> WatchChatRequestContext {
        WatchChatRequestContext(accountID: "account-A", profile: profile,
            accountGeneration: WatchChatAccountLifecycle.generation, deadline: { _ in nil })
    }

    @MainActor private final class WatchFixtureClock { var now = 20 }

    private func authenticate() throws {
        let manager = AuthManager(profileCacheWriter: { _ in })
        manager.currentUser = try JSONDecoder().decode(UserProfile.self,
            from: Data(#"{"id":"account-A","username":"Fixture"}"#.utf8))
        manager.state = .authenticated
        auth = manager
    }

    // Both reads occur inside APIClient's MainActor fence: admit request
    // capture, then expire authority before response publication.
    @MainActor private final class AuthorityFence {
        private(set) var checks = 0
        func isCurrent() -> Bool { checks += 1; return checks == 1 }
    }

    private var refreshCookie: String? {
        cookieStorage.cookies(for: profile.apiBaseURL)?.first { $0.name == "auth_refresh_token" }?.value
    }
    private func cookie(_ value: String) throws -> HTTPCookie {
        try XCTUnwrap(HTTPCookie(properties: [.name: "auth_refresh_token", .value: value,
            .domain: profile.apiBaseURL.host!, .path: "/", .secure: "TRUE",
            .expires: Date().addingTimeInterval(3600)]))
    }
    private func response(account: String, token: String) -> Data {
        try! JSONSerialization.data(withJSONObject: ["success": true,
            "user": ["id": account, "username": "Fixture"], "wsToken": token])
    }
}

private final class NativeSessionURLProtocol: URLProtocol, @unchecked Sendable {
    struct Response: Sendable {
        let status: Int
        let body: Data
        var cookie: String? = nil
        var maxAge: Int = 3600
        var gate: NativeSessionResponseGate? = nil
        var cookieDomain: String? = nil
    }
    typealias Handler = @Sendable (URLRequest) -> Response
    private static let lock = NSLock()
    nonisolated(unsafe) private static var handler: Handler?
    static func setHandler(_ handler: Handler?) { lock.withLock { self.handler = handler } }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let handler = Self.lock.withLock({ Self.handler }) else { return }
        let response = handler(request)
        let deliver: @Sendable () -> Void = { [weak self] in
            self?.respond(status: response.status, body: response.body, cookie: response.cookie,
                          maxAge: response.maxAge, cookieDomain: response.cookieDomain)
        }
        if let gate = response.gate { gate.hold(deliver) }
        else { deliver() }
    }
    override func stopLoading() {}
    private func respond(status: Int, body: Data, cookie: String? = nil, maxAge: Int = 3600, cookieDomain: String? = nil) {
        var headers = ["Content-Type": "application/json"]
        if let cookie {
            let domain = cookieDomain.map { "; Domain=\($0)" } ?? ""
            headers["Set-Cookie"] = "auth_refresh_token=\(cookie); Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=\(maxAge)\(domain)"
        }
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: headers)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body)
        client?.urlProtocolDidFinishLoading(self)
    }
}

// Hold response headers deterministically; no clocks, sleeps, credentials or real
// network IO are involved in ordering the production transport's cookie writes.
private final class NativeSessionResponseGate: @unchecked Sendable {
    private let lock = NSLock()
    private var response: (@Sendable () -> Void)?
    private var waiter: CheckedContinuation<Void, Never>?
    func hold(_ response: @escaping @Sendable () -> Void) {
        let waiting = lock.withLock {
            self.response = response
            let waiting = waiter
            waiter = nil
            return waiting
        }
        waiting?.resume()
    }
    func waitUntilHeld() async {
        await withCheckedContinuation { continuation in
            let held = lock.withLock {
                if response != nil { return true }
                waiter = continuation
                return false
            }
            if held { continuation.resume() }
        }
    }
    func release() {
        let pending = lock.withLock {
            let pending = response
            response = nil
            return pending
        }
        pending?()
    }
}
