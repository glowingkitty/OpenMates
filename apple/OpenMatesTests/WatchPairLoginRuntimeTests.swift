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

    func testServerProfileDerivesProductionDevelopmentAndCustomEndpoints() {
        let production = ServerProfile.production
        XCTAssertEqual(production.id, "production")
        XCTAssertEqual(production.displayDomain, "openmates.org")
        XCTAssertEqual(production.webBaseURL.absoluteString, "https://openmates.org")
        XCTAssertEqual(production.apiBaseURL.absoluteString, "https://api.openmates.org")
        XCTAssertEqual(production.webSocketBaseURL.absoluteString, "wss://api.openmates.org/v1/ws")

        let development = ServerProfile.development
        XCTAssertEqual(development.id, "development")
        XCTAssertEqual(development.displayDomain, "app.dev.openmates.org")
        XCTAssertEqual(development.webBaseURL.absoluteString, "https://app.dev.openmates.org")
        XCTAssertEqual(development.apiBaseURL.absoluteString, "https://api.dev.openmates.org")
        XCTAssertEqual(development.webSocketBaseURL.absoluteString, "wss://api.dev.openmates.org/v1/ws")

        let custom = ServerProfile.custom(domain: "https://app.selfhosted.example/path")
        XCTAssertEqual(custom.id, "custom:app.selfhosted.example")
        XCTAssertEqual(custom.displayDomain, "app.selfhosted.example")
        XCTAssertEqual(custom.webBaseURL.absoluteString, "https://app.selfhosted.example")
        XCTAssertEqual(custom.apiBaseURL.absoluteString, "https://api.selfhosted.example")
        XCTAssertEqual(custom.webSocketBaseURL.absoluteString, "wss://api.selfhosted.example/v1/ws")
    }

    func testPairCompleteFailureNormalizesBackendMessages() {
        XCTAssertEqual(PairLoginRuntime.failureKind(for: "too_many_attempts"), .tooManyAttempts)
        XCTAssertEqual(PairLoginRuntime.failureKind(for: "invalid_pin:2"), .invalidPIN(attemptsRemaining: "2"))
        XCTAssertEqual(PairLoginRuntime.failureKind(for: "expired"), .expired)
        XCTAssertEqual(PairLoginRuntime.failureKind(for: nil), .generic)
    }

    func testWatchConnectivityLoginRequestPayloadContainsNoSecrets() {
        let request = WatchPairLoginRequest(
            token: "abc123",
            pairURLString: "https://app.dev.openmates.org/#pair=ABC123",
            deviceName: "OpenMates Apple Watch app",
            serverProfile: .development,
            createdAt: 1_777_777_777
        )

        let message = WatchPairLoginConnectivityPayload.requestMessage(request)
        let parsed = WatchPairLoginConnectivityPayload.parseRequest(message)

        XCTAssertEqual(parsed, WatchPairLoginRequest(
            token: "ABC123",
            pairURLString: "https://app.dev.openmates.org/#pair=ABC123",
            deviceName: "OpenMates Apple Watch app",
            serverProfile: .development,
            createdAt: 1_777_777_777
        ))
        XCTAssertEqual(message["server_profile_id"] as? String, "development")
        XCTAssertEqual(message["server_web_base_url"] as? String, "https://app.dev.openmates.org")
        XCTAssertEqual(message["server_api_base_url"] as? String, "https://api.dev.openmates.org")
        XCTAssertFalse(WatchPairLoginConnectivityPayload.containsForbiddenSecretKeys(message))
        XCTAssertNil(message["master_key_exported"])
        XCTAssertNil(message["ws_token"])
        XCTAssertNil(message["cookie"])
    }

    func testWatchConnectivityLoginRequestSupportsCustomServerProfile() {
        let customProfile = ServerProfile.custom(domain: "https://app.selfhosted.example")
        let request = WatchPairLoginRequest(
            token: "xyz789",
            pairURLString: "https://app.selfhosted.example/#pair=XYZ789",
            deviceName: "OpenMates Apple Watch app",
            serverProfile: customProfile,
            createdAt: 1_777_777_778
        )

        let message = WatchPairLoginConnectivityPayload.requestMessage(request)
        let parsed = WatchPairLoginConnectivityPayload.parseRequest(message)

        XCTAssertEqual(parsed?.serverProfile, customProfile)
        XCTAssertEqual(message["server_profile_id"] as? String, "custom:app.selfhosted.example")
        XCTAssertEqual(message["server_web_base_url"] as? String, "https://app.selfhosted.example")
        XCTAssertEqual(message["server_api_base_url"] as? String, "https://api.selfhosted.example")
        XCTAssertFalse(WatchPairLoginConnectivityPayload.containsForbiddenSecretKeys(message))
    }

    func testWatchConnectivityLoginRequestDetectsServerMismatchBeforeAuthorization() {
        let request = WatchPairLoginRequest(
            token: "abc123",
            pairURLString: "https://openmates.org/#pair=ABC123",
            deviceName: "OpenMates Apple Watch app",
            serverProfile: .production,
            createdAt: 1_777_777_779
        )

        XCTAssertTrue(WatchPairLoginConnectivityPayload.requestMatchesCurrentServer(request, currentProfile: .production))
        XCTAssertFalse(WatchPairLoginConnectivityPayload.requestMatchesCurrentServer(request, currentProfile: .development))
    }

    func testWatchConnectivityApprovalPayloadContainsOnlyPinAndToken() {
        let approval = WatchPairLoginApproval(token: "abc123", pin: "A3F8Q6")

        let message = WatchPairLoginConnectivityPayload.approvalMessage(approval)
        let parsed = WatchPairLoginConnectivityPayload.parseApproval(message)

        XCTAssertEqual(parsed, WatchPairLoginApproval(token: "ABC123", pin: "A3F8Q6"))
        XCTAssertFalse(WatchPairLoginConnectivityPayload.containsForbiddenSecretKeys(message))
        XCTAssertNil(message["encrypted_bundle"])
        XCTAssertNil(message["session_token"])
        XCTAssertNil(message["master_key"])
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
        let deleted = try await CryptoManager.shared.loadMasterKey(for: userId)

        XCTAssertEqual(loaded.map { rawData(from: $0) }, masterKeyData)
        XCTAssertNil(deleted)
    }

    private func rawData(from key: SymmetricKey) -> Data {
        key.withUnsafeBytes { Data($0) }
    }
}
