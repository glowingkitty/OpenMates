import XCTest
import ImageIO
@testable import OpenMates

final class APIClientUploadTransportTests: XCTestCase {
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
