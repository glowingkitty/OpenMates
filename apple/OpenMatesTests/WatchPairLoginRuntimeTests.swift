// Unit coverage for the shared pair-login runtime used by iOS, macOS, and Watch.
// These tests avoid network requests, credentials, QR payload screenshots, and
// Keychain writes. They lock down deterministic formatting and PIN handling so
// the Watch auth UI can stay small and platform-specific.
// Network-backed pair-login behavior is verified separately on real devices.

import XCTest
@testable import OpenMates

final class WatchPairLoginRuntimeTests: XCTestCase {
    func testNormalizedPINUppercasesFiltersAndTruncatesToSixCharacters() {
        XCTAssertEqual(PairLoginRuntime.normalizedPIN(" ab-cd 12 xyz "), "ABCD12")
        XCTAssertEqual(PairLoginRuntime.normalizedPIN("åb😀c d"), "ÅBCD")
    }

    func testBuildPairURLUsesHashPairTokenForWebAppHost() throws {
        let url = try XCTUnwrap(URL(string: "https://app.dev.openmates.org/some/path"))

        XCTAssertEqual(
            PairLoginRuntime.buildPairURL(webAppURL: url, token: "abc123"),
            "https://app.dev.openmates.org/#pair=ABC123"
        )
    }

    func testPairCompleteFailureNormalizesBackendMessages() {
        XCTAssertEqual(PairLoginRuntime.failureKind(for: "too_many_attempts"), .tooManyAttempts)
        XCTAssertEqual(PairLoginRuntime.failureKind(for: "invalid_pin:2"), .invalidPIN(attemptsRemaining: "2"))
        XCTAssertEqual(PairLoginRuntime.failureKind(for: "expired"), .expired)
        XCTAssertEqual(PairLoginRuntime.failureKind(for: nil), .generic)
    }
}
