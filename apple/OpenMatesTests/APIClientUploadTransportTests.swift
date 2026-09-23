import XCTest
@testable import OpenMates

final class APIClientUploadTransportTests: XCTestCase {
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
}
