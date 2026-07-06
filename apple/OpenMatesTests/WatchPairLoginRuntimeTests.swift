// Unit coverage for the shared pair-login runtime used by iOS, macOS, and Watch.
// These tests avoid network requests, credentials, QR payload screenshots, and
// reusable auth material. They lock down deterministic formatting, bundle
// decryption, and local key storage so Watch auth can stay platform-specific.
// Network-backed pair-login behavior is verified separately on real devices.

import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
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

    func testDecryptLoginBundleReturnsBundleAndMasterKey() async throws {
        let token = "ABC123"
        let pin = "9Z8Y7X"
        let masterKeyData = Data((0..<32).map(UInt8.init))
        let bundleJSON = Data(
            """
            {
              "lookup_hash": "lookup-hash-test",
              "hashed_email": "hashed-email-test",
              "user_email_salt": "salt-test",
              "master_key_exported": "\(masterKeyData.base64EncodedString())"
            }
            """.utf8
        )
        let pairKey = await CryptoManager.shared.derivePairLoginKey(pin: pin, token: token)
        let encrypted = try await CryptoManager.shared.encrypt(bundleJSON, using: pairKey)
        let response = PairCompleteResponse(
            success: true,
            encryptedBundle: encrypted.ciphertext.base64EncodedString(),
            iv: encrypted.nonce.base64EncodedString(),
            autoLogoutMinutes: nil,
            authorizerDeviceName: "Test Device",
            message: nil
        )

        let (bundle, masterKey) = try await PairLoginRuntime.decryptLoginBundle(
            from: response,
            token: token,
            pin: pin
        )

        XCTAssertEqual(bundle.lookupHash, "lookup-hash-test")
        XCTAssertEqual(bundle.hashedEmail, "hashed-email-test")
        XCTAssertEqual(bundle.userEmailSalt, "salt-test")
        XCTAssertEqual(rawData(from: masterKey), masterKeyData)
    }

    func testMasterKeyPersistsLocallyThroughKeychain() async throws {
        let userId = "watch-pair-login-runtime-tests-\(UUID().uuidString)"
        let masterKeyData = Data((32..<64).map(UInt8.init))
        let masterKey = SymmetricKey(data: masterKeyData)

        try? await CryptoManager.shared.deleteMasterKey(for: userId)
        try await CryptoManager.shared.saveMasterKey(masterKey, for: userId)
        let loaded = try await CryptoManager.shared.loadMasterKey(for: userId)
        try await CryptoManager.shared.deleteMasterKey(for: userId)

        XCTAssertEqual(loaded.map { rawData(from: $0) }, masterKeyData)
        XCTAssertNil(try await CryptoManager.shared.loadMasterKey(for: userId))
    }

    private func rawData(from key: SymmetricKey) -> Data {
        key.withUnsafeBytes { Data($0) }
    }
}
