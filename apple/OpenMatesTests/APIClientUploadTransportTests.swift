import XCTest
import ImageIO
@testable import OpenMates

final class APIClientUploadTransportTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    @MainActor
    func testLivePhotoUploadFixtureIsAValidDecodablePNG() throws {
        let data = try XCTUnwrap(Data(base64Encoded: NewChatWelcomeView.livePhotoUploadFixtureBase64))
        let source = try XCTUnwrap(CGImageSourceCreateWithData(data as CFData, nil))

        XCTAssertEqual(CGImageSourceGetCount(source), 1)
        XCTAssertNotNil(CGImageSourceCreateImageAtIndex(source, 0, nil))
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
