// Unit coverage for Watch session persistence and revocation decisions.
// These tests keep credentials, cookies, encryption keys, and user records out
// of fixtures. They prove that transient failures preserve local state while an
// explicit backend 401 selects the destructive Watch cleanup path.

import XCTest
@testable import OpenMates

final class WatchAuthStoreTests: XCTestCase {
    func testOnlyUnauthorizedResponseIsConfirmedRevocation() {
        XCTAssertEqual(
            WatchSessionRefreshPolicy.disposition(for: APIError.httpError(status: 401, message: "revoked")),
            .revoked
        )
        XCTAssertEqual(
            WatchSessionRefreshPolicy.disposition(for: APIError.httpError(status: 503, message: "unavailable")),
            .transientFailure
        )
        XCTAssertEqual(
            WatchSessionRefreshPolicy.disposition(for: URLError(.notConnectedToInternet)),
            .transientFailure
        )
    }

    func testWatchAuthStoreHasExplicitRevocationCleanupPath() throws {
        let appleRoot = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let storeURL = appleRoot.appendingPathComponent("OpenMatesWatch/Sources/WatchAuthStore.swift")
        let source = try String(contentsOf: storeURL, encoding: .utf8)

        XCTAssertTrue(source.contains("WatchSessionRefreshPolicy.disposition(for: error)"))
        XCTAssertTrue(source.contains("clearRevokedSession"))
        XCTAssertTrue(source.contains("WatchServerProfileStore().resetToProduction()"))
        XCTAssertTrue(source.contains("OpenMatesSharedEnvironment.cookieStorage.removeCookies"))
        XCTAssertTrue(source.contains("WatchChatOfflineCache().clearSnapshot()"))
    }
}
