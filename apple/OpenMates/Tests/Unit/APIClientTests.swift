// APIClient unit tests — validates request construction, error handling, and auth headers.

import XCTest
@testable import OpenMates

final class APIClientTests: XCTestCase {

    func testBaseURLIsValid() async {
        let baseURL = await APIClient.shared.baseURL
        XCTAssertFalse(baseURL.absoluteString.isEmpty)
        XCTAssertTrue(baseURL.absoluteString.hasPrefix("http"))
    }

    func testWebAppURLIsValid() async {
        let webURL = await APIClient.shared.webAppURL
        XCTAssertFalse(webURL.absoluteString.isEmpty)
        XCTAssertTrue(webURL.absoluteString.hasPrefix("http"))
    }

    func testNativeClientHeadersIdentifyAppleClientWithoutOrigin() {
        let headers = APIClient.nativeClientHeaders

        XCTAssertTrue(headers["User-Agent"]?.hasPrefix("OpenMates-Apple/") == true)
        #if os(iOS)
        XCTAssertEqual(headers["X-OpenMates-Client"], "ios")
        #elseif os(macOS)
        XCTAssertEqual(headers["X-OpenMates-Client"], "macos")
        #endif
        XCTAssertFalse(headers["X-OpenMates-Bundle-ID"]?.isEmpty ?? true)
        XCTAssertNil(headers["Origin"])
    }

    func testUnauthenticatedRequestReturns401() async {
        do {
            let _: [String: AnyCodable] = try await APIClient.shared.request(
                .get, path: "/v1/auth/session"
            )
        } catch {
            let nsError = error as NSError
            XCTAssertTrue(
                nsError.code == 401 || nsError.localizedDescription.contains("401") ||
                nsError.localizedDescription.contains("Unauthorized"),
                "Expected 401 for unauthenticated request, got: \(error)"
            )
        }
    }
}
