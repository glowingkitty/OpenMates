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

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send,auth.session.isolation
    @MainActor
    func testRecordingUploadAwaitsRecoveryBeforeRetryingWithRenewedCookie() async throws {
        let originalProfile = ServerConfiguration.current
        let profile = ServerProfile.custom(domain: "audio-recovery-fixture.example")
        ServerConfiguration.current = profile.endpointConfiguration
        let firstRequest = expectation(description: "First upload is rejected")
        let recoveryStarted = expectation(description: "Recovery starts")
        let fixture = RecordingUploadURLProtocol.Fixture(firstRequest: firstRequest)
        RecordingUploadURLProtocol.setFixture(fixture)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [RecordingUploadURLProtocol.self]
        let storage = try XCTUnwrap(configuration.httpCookieStorage)
        let transport = URLSession(configuration: configuration)
        defer {
            transport.invalidateAndCancel()
            RecordingUploadURLProtocol.setFixture(nil)
            ServerConfiguration.current = originalProfile
        }
        func cookie(_ value: String) throws -> HTTPCookie {
            try XCTUnwrap(HTTPCookie(properties: [.domain: try XCTUnwrap(profile.apiBaseURL.host),
                .path: "/", .name: "auth_refresh_token", .value: value, .secure: "TRUE"]))
        }
        storage.setCookie(try cookie("fixture-expired"))
        let renewed = try cookie("fixture-renewed")
        var validation: CheckedContinuation<SessionResponse, Error>?
        let api = APIClient(session: transport, uploadSession: transport, cookieStorage: storage)
        let auth = AuthManager(api: api, sessionValidator: { _, _ in
            recoveryStarted.fulfill()
            let response = try await withCheckedThrowingContinuation { validation = $0 }
            storage.setCookie(renewed)
            return response
        }, profileCacheWriter: { _ in }, sessionMasterKeyAvailable: { _ in true }, sessionScopeActivator: { _ in })
        auth.currentUser = try JSONDecoder().decode(UserProfile.self,
            from: Data(#"{"id":"audio-fixture-account","username":"Fixture"}"#.utf8))
        auth.state = .authenticated
        let upload = Task {
            try await api.uploadFile(data: Data([1, 2, 3]), filename: "fixture.m4a", contentType: "audio/mp4", chatId: "fixture-chat")
        }
        await fulfillment(of: [firstRequest, recoveryStarted], timeout: 2)
        XCTAssertEqual(fixture.requests.count, 1, "The upload must not race the suspended refresh")
        guard let validation else { upload.cancel(); return XCTFail("Expected suspended session recovery") }
        validation.resume(returning: try JSONDecoder().decode(SessionResponse.self,
            from: Data(#"{"success":true,"user":{"id":"audio-fixture-account","username":"Fixture"},"wsToken":"fixture-token"}"#.utf8)))
        let data = try await upload.value
        XCTAssertEqual(data, Data(#"{"ok":true}"#.utf8))
        XCTAssertEqual(fixture.requests.count, 2)
        XCTAssertEqual(fixture.requests.map { $0.value(forHTTPHeaderField: "Cookie") },
            ["auth_refresh_token=fixture-expired", "auth_refresh_token=fixture-renewed"])
        XCTAssertTrue(fixture.requests.allSatisfy { $0.httpMethod == "POST" && $0.url?.path == "/v1/upload/file" })
        XCTAssertTrue(fixture.requests.allSatisfy { $0.value(forHTTPHeaderField: "Content-Type")?.hasPrefix("multipart/form-data; boundary=") == true })
        withExtendedLifetime(auth) {}
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    @MainActor
    func testRecordingFailureDiagnosticsOnlyContainStatusOrCategory() {
        XCTAssertEqual(AudioRecordingUploadService.failureCategory(APIError.httpError(status: 415, message: "private server detail")), "http_415")
        XCTAssertEqual(AudioRecordingUploadService.failureCategory(URLError(.notConnectedToInternet)), "url_-1009")
        XCTAssertEqual(AudioRecordingUploadService.failureCategory(DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "private body"))), "response_decode")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    @MainActor
    func testRecordingUploadDoesNotRetryUnsupportedMediaResponse() async throws {
        let originalProfile = ServerConfiguration.current
        ServerConfiguration.current = ServerProfile.custom(domain: "audio-status-fixture.example").endpointConfiguration
        let firstRequest = expectation(description: "Upload receives HTTP 415")
        let fixture = RecordingUploadURLProtocol.Fixture(firstRequest: firstRequest, firstStatus: 415)
        RecordingUploadURLProtocol.setFixture(fixture)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [RecordingUploadURLProtocol.self]
        let transport = URLSession(configuration: configuration)
        defer {
            transport.invalidateAndCancel(); RecordingUploadURLProtocol.setFixture(nil)
            ServerConfiguration.current = originalProfile
        }
        let api = APIClient(uploadSession: transport, cookieStorage: try XCTUnwrap(configuration.httpCookieStorage))
        do {
            _ = try await api.uploadFile(data: Data([1]), filename: "fixture.m4a", contentType: "audio/mp4", chatId: "fixture-chat")
            XCTFail("Expected the server rejection to remain an upload failure")
        } catch APIError.httpError(let status, _) {
            XCTAssertEqual(status, 415)
        }
        await fulfillment(of: [firstRequest], timeout: 2)
        XCTAssertEqual(fixture.requests.count, 1)
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
        let _: Data = try await api.request(.post, path: AudioRecordingUploadService.batchTranscriptionPath,
            body: ["requests": []] as [String: Any])
        await fulfillment(of: [requestStarted], timeout: 2)
        let request = try XCTUnwrap(fixture.requests.first)
        XCTAssertEqual(fixture.requests.count, 1)
        XCTAssertEqual(request.url?.absoluteString, "https://api.dev.openmates.org/v1/apps/audio/skills/transcribe")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Origin"), "https://app.dev.openmates.org")
        XCTAssertEqual(request.httpMethod, "POST")
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
