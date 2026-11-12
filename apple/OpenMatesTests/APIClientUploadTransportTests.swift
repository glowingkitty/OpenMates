import XCTest
import ImageIO
@testable import OpenMates

private final class RecordingUploadURLProtocol: URLProtocol, @unchecked Sendable {
    final class Fixture: @unchecked Sendable {
        private let lock = NSLock()
        private var recorded: [URLRequest] = []
        let firstRequest: XCTestExpectation
        let firstStatus: Int
        init(firstRequest: XCTestExpectation, firstStatus: Int = 401) {
            self.firstRequest = firstRequest; self.firstStatus = firstStatus
        }
        var requests: [URLRequest] { lock.lock(); defer { lock.unlock() }; return recorded }
        func record(_ request: URLRequest) -> Int {
            lock.lock(); recorded.append(request); let count = recorded.count; lock.unlock()
            return count
        }
    }
    private static let lock = NSLock()
    private nonisolated(unsafe) static var fixture: Fixture?
    static func setFixture(_ value: Fixture?) { lock.lock(); fixture = value; lock.unlock() }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lock.lock(); let fixture = Self.fixture; Self.lock.unlock()
        guard let fixture, let url = request.url else {
            client?.urlProtocol(self, didFailWithError: URLError(.cancelled)); return
        }
        let count = fixture.record(request)
        let response = HTTPURLResponse(url: url, statusCode: count == 1 ? fixture.firstStatus : 200,
            httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data((count == 1 ? #"{"detail":"fixture expired"}"# : #"{"ok":true}"#).utf8))
        client?.urlProtocolDidFinishLoading(self)
        if count == 1 { fixture.firstRequest.fulfill() }
    }
    override func stopLoading() {}
}

final class APIClientUploadTransportTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete
    func testFinalCoreRequestsPreserveEscapedPathSegmentsAndQueryExactlyOnce() async throws {
        let api = APIClient()
        let baseURL = try XCTUnwrap(URL(string: "https://fixture.invalid/gateway/"))
        let webURL = try XCTUnwrap(URL(string: "https://app.fixture.invalid"))
        let cases = [
            ("workflow-run:fixture", "workflow-run%3Afixture"),
            ("workflow-schedule:trigger:123", "workflow-schedule%3Atrigger%3A123"),
            ("literal%3Avalue", "literal%253Avalue"),
            ("path/segment", "path%2Fsegment"),
            ("two words", "two%20words"),
            ("café猫", "caf%C3%A9%E7%8C%AB"),
            ("query?key=value&#fragment", "query%3Fkey%3Dvalue%26%23fragment"),
        ]
        for (id, encodedID) in cases {
            let path = UserTasksPaths.task(id) + "/dependencies?cursor=literal%253A%2F%20%E7%8C%AB&team_id=team%2Fa"
            let request = try await api.buildRequest(.get, path: path, headers: ["X-Fixture": "preserved"],
                baseURL: baseURL, webAppURL: webURL)
            let url = try XCTUnwrap(request.url)
            let components = try XCTUnwrap(URLComponents(url: url, resolvingAgainstBaseURL: false))
            XCTAssertEqual(components.percentEncodedPath, "/gateway/v1/user-tasks/" + encodedID + "/dependencies", id)
            XCTAssertEqual(components.percentEncodedQuery, "cursor=literal%253A%2F%20%E7%8C%AB&team_id=team%2Fa", id)
            XCTAssertEqual(components.queryItems?.first?.value, "literal%3A/ 猫", id)
            XCTAssertEqual(components.queryItems?.last?.value, "team/a", id)
            XCTAssertEqual(url.host, "fixture.invalid")
            XCTAssertNil(components.fragment)
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Origin"), webURL.absoluteString)
            XCTAssertEqual(request.value(forHTTPHeaderField: "X-Fixture"), "preserved")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testHostedDevelopmentUploadsUseSharedSatelliteWithDevelopmentOrigin() throws {
        XCTAssertEqual(ServerProfile.development.webBaseURL.absoluteString, "https://app.dev.openmates.org")
        XCTAssertEqual(ServerProfile.development.apiBaseURL.absoluteString, "https://api.dev.openmates.org")
        XCTAssertEqual(ServerProfile.production.webBaseURL.absoluteString, "https://openmates.org")
        for profile in [ServerProfile.development, .production] {
            XCTAssertEqual(profile.uploadBaseURL, URL(string: "https://upload.openmates.org"))
            let request = APIClient.makeUploadRequest(
                uploadURL: profile.uploadBaseURL.appendingPathComponent("v1/upload/file"),
                authenticationURL: profile.apiBaseURL, webAppURL: profile.webBaseURL,
                boundary: "hosted-audio", body: Data())
            XCTAssertEqual(request.url?.host, "upload.openmates.org")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Origin"), profile.webBaseURL.absoluteString)
        }
        let restored = try XCTUnwrap(ServerProfile.fromPayload(id: "development",
            webBaseURLString: ServerProfile.development.webBaseURL.absoluteString,
            apiBaseURLString: ServerProfile.development.apiBaseURL.absoluteString, uploadBaseURLString: nil))
        XCTAssertEqual(restored.uploadBaseURL, ServerProfile.development.uploadBaseURL)
        let selfHosted = ServerProfile.custom(domain: "self-hosted-fixture.example")
        XCTAssertEqual(selfHosted.uploadBaseURL, selfHosted.apiBaseURL)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    @MainActor
    func testRecordingFailureDiagnosticsOnlyContainStatusOrCategory() {
        XCTAssertEqual(AudioRecordingUploadService.failureCategory(APIError.httpError(status: 415, message: "private server detail")), "http_415")
        XCTAssertEqual(AudioRecordingUploadService.failureCategory(URLError(.notConnectedToInternet)), "url_-1009")
        XCTAssertEqual(AudioRecordingUploadService.failureCategory(DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "private body"))), "response_decode")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send,client-core.apple.strangler-order
    @MainActor
    func testAppUploadsGoThroughTheCoreAndNeverTheURLSessionTransport() async throws {
        let originalProfile = ServerConfiguration.current
        ServerConfiguration.current = ServerProfile.custom(domain: "audio-status-fixture.example").endpointConfiguration
        let unused = expectation(description: "No URLSession upload")
        unused.isInverted = true
        let fixture = RecordingUploadURLProtocol.Fixture(firstRequest: unused, firstStatus: 415)
        RecordingUploadURLProtocol.setFixture(fixture)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [RecordingUploadURLProtocol.self]
        let transport = URLSession(configuration: configuration)
        defer {
            transport.invalidateAndCancel(); RecordingUploadURLProtocol.setFixture(nil)
            ServerConfiguration.current = originalProfile
        }
        let api = APIClient(uploadSession: transport, cookieStorage: try XCTUnwrap(configuration.httpCookieStorage))
        // The unit-test host launches no core: the upload fails typed instead
        // of falling back to the Swift transport.
        do {
            _ = try await api.uploadFile(data: Data([1]), filename: "fixture.m4a", contentType: "audio/mp4", chatId: "fixture-chat")
            XCTFail("an upload without a core succeeded")
        } catch let error as CoreSessionAdoptionError {
            XCTAssertEqual(error, .coreUnavailable)
        }
        await fulfillment(of: [unused], timeout: 0.5)
        XCTAssertEqual(fixture.requests.count, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send,client-core.viewmodel.capability-contract
    @MainActor
    func testACoreUploadRemovesItsTemporaryFileAlsoWhenTheCoreRefuses() async throws {
        let container = FileManager.default.temporaryDirectory.path
        let name = "upload-core-\(UUID().uuidString)"
        addTeardownBlock { try? FileManager.default.removeItem(atPath: (container as NSString).appendingPathComponent(name)) }
        let core = try CoreSession(
            config: CoreConfig(apiUrl: "https://never-contact.example.invalid", appUrl: "https://app.example.invalid",
                cacheContainer: container, cacheDirectoryName: name),
            credentials: InMemoryCredentialStore())
        try await core.start()
        func leftovers() -> Set<String> {
            Set((try? FileManager.default.contentsOfDirectory(atPath: APIClient.coreUploadDirectory.path)) ?? [])
        }
        let before = leftovers()
        do {
            _ = try await APIClient().uploadThroughCore(
                url: try XCTUnwrap(URL(string: "https://never-contact.example.invalid/v1/upload/file")),
                data: Data("private file bytes".utf8), filename: "notes.txt", contentType: "text/plain",
                fields: [HttpFieldRecord(name: "chat_id", value: "fixture-chat")], core: core)
            XCTFail("an upload without a session succeeded")
        } catch let error as CoreError {
            XCTAssertEqual(error, .Authentication)
        }
        XCTAssertEqual(leftovers(), before, "the temporary upload file outlived the call")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    @MainActor
    func testRecordingBatchFallbackUsesVersionedCoreAPIAndDevelopmentOrigin() async throws {
        let originalProfile = ServerConfiguration.current
        ServerConfiguration.current = ServerProfile.development.endpointConfiguration
        let requestStarted = expectation(description: "Versioned transcription POST")
        let fixture = RecordingUploadURLProtocol.Fixture(firstRequest: requestStarted, firstStatus: 200)
        RecordingUploadURLProtocol.setFixture(fixture)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [RecordingUploadURLProtocol.self]
        let transport = URLSession(configuration: configuration)
        defer {
            transport.invalidateAndCancel(); RecordingUploadURLProtocol.setFixture(nil)
            ServerConfiguration.current = originalProfile
        }
        let api = APIClient(session: transport, cookieStorage: try XCTUnwrap(configuration.httpCookieStorage))
        let profileJSON = Data(#"{"id":"audio-batch-fixture-account","username":"Fixture"}"#.utf8)
        let auth = AuthManager(api: api, reads: AuthCoreReads(
                profile: { UserProfileRecord(json: profileJSON, fresh: true) },
                socketGrant: { LegacySocketGrantRecord(sessionId: AuthManager.nativeSessionId, wsToken: "fixture-token") }),
            profileCacheWriter: { _ in }, sessionScopeActivator: { _ in })
        await auth.apply(.admitted(username: "Fixture", expiresAt: nil))
        XCTAssertTrue(auth.hasNetworkAuthority)
        let _: Data = try await api.request(.post, path: AudioRecordingUploadService.batchTranscriptionPath,
            body: ["requests": []] as [String: Any])
        await fulfillment(of: [requestStarted], timeout: 2)
        let request = try XCTUnwrap(fixture.requests.first)
        XCTAssertEqual(fixture.requests.count, 1)
        XCTAssertEqual(request.url?.absoluteString, "https://api.dev.openmates.org/v1/apps/audio/skills/transcribe")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Origin"), "https://app.dev.openmates.org")
        XCTAssertEqual(request.httpMethod, "POST")
        withExtendedLifetime(auth) {}
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testProjectUploadPinsAuthorizedCookiesAcrossSharedJarAccountReplacement() throws {
        let uploadURL = try XCTUnwrap(URL(string: "https://upload.project-cookie.test/v1/upload/file"))
        let apiURL = try XCTUnwrap(URL(string: "https://api.project-cookie.test"))
        func cookie(_ value: String) throws -> HTTPCookie {
            try XCTUnwrap(HTTPCookie(properties: [.domain: ".project-cookie.test", .path: "/",
                .name: "auth_refresh_token", .value: value, .secure: "TRUE"]))
        }
        let authorized = try cookie("authorized-account")
        let replacement = try cookie("replacement-account")
        let storage = OpenMatesSharedEnvironment.cookieStorage
        storage.setCookie(authorized)
        defer { storage.deleteCookie(authorized); storage.deleteCookie(replacement) }
        let request = APIClient.makeUploadRequest(uploadURL: uploadURL, authenticationURL: apiURL,
            webAppURL: apiURL, boundary: "project", body: Data("private-project-file".utf8), pinCookies: true)
        storage.setCookie(replacement)
        XCTAssertFalse(request.httpShouldHandleCookies)
        XCTAssertEqual(request.value(forHTTPHeaderField: "Cookie"), "auth_refresh_token=authorized-account")
        let retry = APIClient.makeUploadRequest(uploadURL: uploadURL, authenticationURL: apiURL,
            webAppURL: apiURL, boundary: "project", body: Data(), pinCookies: true)
        XCTAssertEqual(retry.value(forHTTPHeaderField: "Cookie"), "auth_refresh_token=replacement-account")
        var scopedRequest = URLRequest(url: apiURL.appendingPathComponent("v1/projects"))
        APIClient.pinAuthorizedCookies(in: &scopedRequest)
        storage.setCookie(authorized)
        XCTAssertFalse(scopedRequest.httpShouldHandleCookies)
        XCTAssertEqual(scopedRequest.value(forHTTPHeaderField: "Cookie"), "auth_refresh_token=replacement-account")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testProjectUploadCannotRetryAfterAccountScopeOrServerChanges() {
        let scope = UUID()
        func matches(account: String = "owner", currentScope: UUID? = nil,
                     profile: ServerProfile = .development) -> Bool {
            APIClient.isUploadContextCurrent(expectedAccountID: "owner", currentAccountID: account,
                expectedScope: scope, currentScope: currentScope ?? scope,
                serverProfile: .development, currentProfile: profile)
        }
        XCTAssertTrue(matches())
        XCTAssertFalse(matches(account: "next-account"))
        XCTAssertFalse(matches(currentScope: UUID()), "Even a return to the same account invalidates old file bytes")
        XCTAssertFalse(matches(profile: .production))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testProjectImportMultipartOmitsChatIdentityAndPreservesFileBytes() throws {
        let data = Data("Project file contents".utf8)
        let body = try APIClient.makeUploadBody(data: data, filename: "notes.txt",
            contentType: "text/plain", chatID: nil, boundary: "project-boundary")
        let form = try XCTUnwrap(String(data: body, encoding: .utf8))
        XCTAssertTrue(form.contains("name=\"file\"; filename=\"notes.txt\"\r\n"))
        XCTAssertTrue(form.contains("\r\n\r\nProject file contents\r\n--project-boundary--\r\n"))
        XCTAssertFalse(form.contains("chat_id"))
        let chatBody = try APIClient.makeUploadBody(data: data, filename: "notes.txt",
            contentType: "text/plain", chatID: "owning-chat", boundary: "chat-boundary")
        XCTAssertTrue(String(decoding: chatBody, as: UTF8.self).contains("name=\"chat_id\"\r\n\r\nowning-chat\r\n"))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testImportFilenameCannotInjectAnotherMultipartField() throws {
        XCTAssertThrowsError(try APIClient.makeUploadBody(data: Data(),
            filename: "file\r\nContent-Disposition: form-data; name=\"chat_id\"",
            contentType: "text/plain", chatID: nil, boundary: "fixture"))
        let body = try APIClient.makeUploadBody(data: Data(), filename: "a\"b.txt",
            contentType: "text/plain", chatID: nil, boundary: "fixture")
        XCTAssertTrue(String(decoding: body, as: UTF8.self).contains("filename=\"a\\\"b.txt\""))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    @MainActor
    func testLivePhotoUploadFixtureIsAValidDecodablePNG() throws {
        let data = try XCTUnwrap(NewChatWelcomeView.livePhotoUploadFixtureData())
        let source = try XCTUnwrap(CGImageSourceCreateWithData(data as CFData, nil))

        XCTAssertEqual(CGImageSourceGetCount(source), 1)
        let image = try XCTUnwrap(CGImageSourceCreateImageAtIndex(source, 0, nil))
        #if os(iOS)
        XCTAssertGreaterThanOrEqual(image.width, 256)
        XCTAssertEqual(image.height, image.width)
        #endif
        XCTAssertEqual(CGImageSourceGetType(source) as String?, "public.png")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testUploadConfigurationExtendsOnlyUploadTimeoutAndSharesCookieStorage() {
        let standard = APIClient.makeStandardSessionConfiguration()
        let upload = APIClient.makeUploadSessionConfiguration()

        XCTAssertEqual(standard.timeoutIntervalForRequest, 30)
        XCTAssertEqual(standard.timeoutIntervalForResource, 60)
        XCTAssertEqual(upload.timeoutIntervalForRequest, 10 * 60)
        XCTAssertEqual(upload.timeoutIntervalForResource, 10 * 60)

        XCTAssertEqual(upload.httpCookieAcceptPolicy, .always)
        XCTAssertTrue(upload.httpShouldSetCookies)
        XCTAssertTrue(upload.httpCookieStorage === OpenMatesSharedEnvironment.cookieStorage)
        XCTAssertTrue(upload.httpCookieStorage === standard.httpCookieStorage)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send,message-input.privacy-context
    func testUploadRequestCarriesOriginNativeHeadersAndMultipartBody() throws {
        let uploadURL = try XCTUnwrap(URL(string: "https://uploads.example.test/v1/upload/file"))
        let webAppURL = try XCTUnwrap(URL(string: "https://app.example.test"))
        let body = Data("multipart-fixture".utf8)
        let request = APIClient.makeUploadRequest(
            uploadURL: uploadURL,
            authenticationURL: webAppURL,
            webAppURL: webAppURL,
            boundary: "fixture-boundary",
            body: body
        )

        XCTAssertEqual(request.url, uploadURL)
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "Content-Type"),
            "multipart/form-data; boundary=fixture-boundary"
        )
        XCTAssertEqual(request.value(forHTTPHeaderField: "Origin"), webAppURL.absoluteString)
        for (name, value) in APIClient.nativeClientHeaders {
            XCTAssertEqual(request.value(forHTTPHeaderField: name), value)
        }
        XCTAssertEqual(request.httpBody, body)
    }

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testUploadRequestLeavesUploadScopedCookieForURLSessionToResolveAtSendTime() throws {
        let uploadURL = try XCTUnwrap(URL(string: "https://uploads.example.test/v1/upload/file"))
        let webAppURL = try XCTUnwrap(URL(string: "https://app.example.test"))
        let cookie = try XCTUnwrap(HTTPCookie(properties: [
            .domain: ".example.test",
            .path: "/",
            .name: "auth_refresh_token",
            .value: "test-session",
            .secure: "TRUE"
        ]))
        OpenMatesSharedEnvironment.cookieStorage.setCookie(cookie)
        defer { OpenMatesSharedEnvironment.cookieStorage.deleteCookie(cookie) }

        let request = APIClient.makeUploadRequest(
            uploadURL: uploadURL,
            authenticationURL: webAppURL,
            webAppURL: webAppURL,
            boundary: "fixture-boundary",
            body: Data()
        )

        XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
    }

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testUploadRequestForwardsHostOnlyAPIRefreshCookie() throws {
        let uploadURL = try XCTUnwrap(URL(string: "https://upload.example.test/v1/upload/file"))
        let apiURL = try XCTUnwrap(URL(string: "https://api.example.test"))
        let webAppURL = try XCTUnwrap(URL(string: "https://app.example.test"))
        let authCookie = try XCTUnwrap(HTTPCookie(properties: [
            .domain: "api.example.test",
            .path: "/",
            .name: "auth_refresh_token",
            .value: "host-only-session",
            .secure: "TRUE"
        ]))
        let unrelatedCookie = try XCTUnwrap(HTTPCookie(properties: [
            .domain: "api.example.test",
            .path: "/",
            .name: "unrelated",
            .value: "must-not-forward",
            .secure: "TRUE"
        ]))
        OpenMatesSharedEnvironment.cookieStorage.setCookie(authCookie)
        OpenMatesSharedEnvironment.cookieStorage.setCookie(unrelatedCookie)
        defer {
            OpenMatesSharedEnvironment.cookieStorage.deleteCookie(authCookie)
            OpenMatesSharedEnvironment.cookieStorage.deleteCookie(unrelatedCookie)
        }

        let request = APIClient.makeUploadRequest(
            uploadURL: uploadURL,
            authenticationURL: apiURL,
            webAppURL: webAppURL,
            boundary: "fixture-boundary",
            body: Data()
        )

        XCTAssertEqual(request.value(forHTTPHeaderField: "Cookie"), "auth_refresh_token=host-only-session")
    }

    // contract-test: direct surface=gui.apple assertions=message-input.embeds.gated-send
    func testUploadRequestPrefersCurrentAPIRefreshCookieOverStaleUploadCookie() throws {
        let uploadURL = try XCTUnwrap(URL(string: "https://upload.example.test/v1/upload/file"))
        let apiURL = try XCTUnwrap(URL(string: "https://api.example.test"))
        let webAppURL = try XCTUnwrap(URL(string: "https://app.example.test"))
        let staleUploadCookie = try XCTUnwrap(HTTPCookie(properties: [
            .domain: "upload.example.test",
            .path: "/",
            .name: "auth_refresh_token",
            .value: "stale-upload-session",
            .secure: "TRUE"
        ]))
        let currentAPICookie = try XCTUnwrap(HTTPCookie(properties: [
            .domain: "api.example.test",
            .path: "/",
            .name: "auth_refresh_token",
            .value: "current-api-session",
            .secure: "TRUE"
        ]))
        OpenMatesSharedEnvironment.cookieStorage.setCookie(staleUploadCookie)
        OpenMatesSharedEnvironment.cookieStorage.setCookie(currentAPICookie)
        defer {
            OpenMatesSharedEnvironment.cookieStorage.deleteCookie(staleUploadCookie)
            OpenMatesSharedEnvironment.cookieStorage.deleteCookie(currentAPICookie)
        }

        let request = APIClient.makeUploadRequest(
            uploadURL: uploadURL,
            authenticationURL: apiURL,
            webAppURL: webAppURL,
            boundary: "fixture-boundary",
            body: Data()
        )

        XCTAssertEqual(request.value(forHTTPHeaderField: "Cookie"), "auth_refresh_token=current-api-session")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testUploadRetriesOnlyAnAuthenticationRace() {
        XCTAssertTrue(APIClient.shouldRetryUpload(after: APIError.httpError(status: 401, message: "expired")))
        XCTAssertFalse(APIClient.shouldRetryUpload(after: APIError.httpError(status: 500, message: "failed")))
        XCTAssertFalse(APIClient.shouldRetryUpload(after: APIError.invalidResponse))
    }
}
