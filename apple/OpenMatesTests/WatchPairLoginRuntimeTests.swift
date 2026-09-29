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
    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.private-session
    func testPairStepUpMethodSelectionKeepsPasskeyOnlyAccountsEligible() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let passkeyOnly = try decoder.decode(PairV2StepUpMethods.self,
            from: Data(#"{"has_passkey":true,"has_password":false,"has_2fa":false}"#.utf8))
        XCTAssertTrue(passkeyOnly.supports(.passkey))
        XCTAssertFalse(passkeyOnly.supports(.password))
        XCTAssertFalse(passkeyOnly.supports(.otp))

        let passwordAndOTP = try decoder.decode(PairV2StepUpMethods.self,
            from: Data(#"{"has_passkey":false,"has_password":true,"has_2fa":true}"#.utf8))
        XCTAssertFalse(passwordAndOTP.supports(.passkey))
        XCTAssertTrue(passwordAndOTP.supports(.password))
        XCTAssertTrue(passwordAndOTP.supports(.otp))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testNormalizedPINUppercasesFiltersAndTruncatesToSixCharacters() {
        XCTAssertEqual(PairLoginRuntime.normalizedPIN(" ab-cd 12 xyz "), "ABCD12")
        XCTAssertEqual(PairLoginRuntime.normalizedPIN("åb😀c d"), "ÅBCD")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testBuildPairURLUsesHashPairTokenForWebAppHost() throws {
        let url = try XCTUnwrap(URL(string: "https://app.dev.openmates.org/some/path"))

        XCTAssertEqual(
            PairLoginRuntime.buildPairURL(webAppURL: url, token: "abc123"),
            "https://app.dev.openmates.org/#pair=ABC123"
        )
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
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

    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testSelfHostedURLValidationAcceptsHTTPSAndRejectsInsecureURLs() throws {
        XCTAssertEqual(
            try ServerProfile.validatedSelfHostedURL("app.dev.openmates.org"),
            ServerProfile.custom(domain: "app.dev.openmates.org")
        )
        XCTAssertEqual(
            try ServerProfile.validatedSelfHostedURL("https://app.selfhosted.example"),
            ServerProfile.custom(domain: "app.selfhosted.example")
        )
        XCTAssertThrowsError(try ServerProfile.validatedSelfHostedURL("http://app.selfhosted.example"))
        XCTAssertThrowsError(try ServerProfile.validatedSelfHostedURL("https://app.selfhosted.example:8443"))
        XCTAssertThrowsError(try ServerProfile.validatedSelfHostedURL("https://app.selfhosted.example/login"))
        XCTAssertThrowsError(try ServerProfile.validatedSelfHostedURL(""))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.private-session
    func testPairCompleteFailureNormalizesBackendMessages() {
        XCTAssertEqual(PairLoginRuntime.failureKind(for: "too_many_attempts"), .tooManyAttempts)
        XCTAssertEqual(PairLoginRuntime.failureKind(for: "invalid_pin:2"), .invalidPIN(attemptsRemaining: "2"))
        XCTAssertEqual(PairLoginRuntime.failureKind(for: "expired"), .expired)
        XCTAssertEqual(PairLoginRuntime.failureKind(for: nil), .generic)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.private-session
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

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.private-session
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

    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.private-session
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

        let manuallyEnteredDevelopment = WatchPairLoginRequest(
            token: "def456",
            pairURLString: "https://app.dev.openmates.org/#pair=DEF456",
            deviceName: "OpenMates Apple Watch app",
            serverProfile: .custom(domain: "app.dev.openmates.org"),
            createdAt: 1_777_777_780
        )
        XCTAssertTrue(WatchPairLoginConnectivityPayload.requestMatchesCurrentServer(
            manuallyEnteredDevelopment,
            currentProfile: .development
        ))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testWatchPairAttemptDefaultsToOneImmutableProductionAttempt() throws {
        var state = WatchPairAttemptState()

        let generation = state.begin(serverProfile: .production)
        let duplicateGeneration = state.ensureCurrentAttempt(serverProfile: .production)
        let initiation = PairLoginInitiation(
            token: "abc123",
            pairURLString: "https://openmates.org/#pair=ABC123"
        )

        XCTAssertEqual(generation, 1)
        XCTAssertEqual(duplicateGeneration, generation)
        XCTAssertTrue(state.accept(initiation, generation: generation, serverProfile: .production))
        XCTAssertEqual(state.serverProfile, .production)
        XCTAssertEqual(state.token, "ABC123")
        XCTAssertEqual(state.pairURLString, "https://openmates.org/#pair=ABC123")
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testWatchPairAttemptRejectsStaleCallbacksAfterSelfHostedReplacement() {
        var state = WatchPairAttemptState()
        let productionGeneration = state.begin(serverProfile: .production)
        let development = ServerProfile.custom(domain: "app.dev.openmates.org")
        let developmentGeneration = state.begin(serverProfile: development)

        XCTAssertFalse(state.accept(
            PairLoginInitiation(token: "old111", pairURLString: "https://openmates.org/#pair=OLD111"),
            generation: productionGeneration,
            serverProfile: .production
        ))
        XCTAssertTrue(state.accept(
            PairLoginInitiation(token: "new222", pairURLString: "https://app.dev.openmates.org/#pair=NEW222"),
            generation: developmentGeneration,
            serverProfile: development
        ))
        XCTAssertEqual(state.serverProfile, development)
        XCTAssertEqual(state.token, "NEW222")
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.private-session
    func testWatchServerProfileStorePersistsOnlyExplicitSuccessfulLogin() throws {
        let suiteName = "WatchPairLoginRuntimeTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let store = WatchServerProfileStore(defaults: defaults)
        let development = ServerProfile.custom(domain: "app.dev.openmates.org")

        XCTAssertEqual(store.currentProfile(), .production)
        XCTAssertEqual(store.currentProfile(), .production, "Selecting a server must not persist it before login succeeds")

        store.saveSuccessfulProfile(development)
        XCTAssertEqual(store.currentProfile(), development)

        store.resetToProduction()
        XCTAssertEqual(store.currentProfile(), .production)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.private-session
    func testIPhoneApprovalEligibilityRequiresAuthenticationAndExactServer() {
        let request = WatchPairLoginRequest(
            token: "abc123",
            pairURLString: "https://openmates.org/#pair=ABC123",
            deviceName: "OpenMates Apple Watch app",
            serverProfile: .production,
            createdAt: 1_777_777_779
        )

        XCTAssertTrue(WatchPairLoginConnectivityPayload.shouldOfferApproval(
            for: request,
            currentProfile: .production,
            isAuthenticated: true,
            now: request.createdAt
        ))
        XCTAssertFalse(WatchPairLoginConnectivityPayload.shouldOfferApproval(
            for: request,
            currentProfile: .development,
            isAuthenticated: true,
            now: request.createdAt
        ))
        XCTAssertFalse(WatchPairLoginConnectivityPayload.shouldOfferApproval(
            for: request,
            currentProfile: .production,
            isAuthenticated: false,
            now: request.createdAt
        ))
        XCTAssertFalse(WatchPairLoginConnectivityPayload.shouldOfferApproval(
            for: request,
            currentProfile: .production,
            isAuthenticated: true,
            now: request.createdAt + 301
        ))
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.private-session
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

    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testWatchLoginAcknowledgmentsAreTokenScopedAndContainNoSecrets() {
        for kind in [
            WatchPairLoginAcknowledgment.Kind.offered,
            .approvalStarted,
            .denied,
            .approvalFailed,
        ] {
            let acknowledgment = WatchPairLoginAcknowledgment(token: "abc123", kind: kind)
            let message = WatchPairLoginConnectivityPayload.acknowledgmentMessage(acknowledgment)
            XCTAssertEqual(
                WatchPairLoginConnectivityPayload.parseAcknowledgment(message),
                WatchPairLoginAcknowledgment(token: "ABC123", kind: kind)
            )
            XCTAssertEqual(message["token"] as? String, "ABC123")
            XCTAssertFalse(WatchPairLoginConnectivityPayload.containsForbiddenSecretKeys(message))
            XCTAssertNil(message["pin"])
            XCTAssertNil(message["pair_url"])
        }
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.private-session
    func testWatchLoginAcknowledgmentRejectsMalformedOrUnrecognizedEvents() {
        let valid = WatchPairLoginConnectivityPayload.acknowledgmentMessage(
            WatchPairLoginAcknowledgment(token: "ABC123", kind: .offered)
        )
        var missingToken = valid
        missingToken.removeValue(forKey: "token")
        XCTAssertNil(WatchPairLoginConnectivityPayload.parseAcknowledgment(missingToken))

        var unknownKind = valid
        unknownKind["acknowledgment"] = "approved"
        XCTAssertNil(WatchPairLoginConnectivityPayload.parseAcknowledgment(unknownKind))
        XCTAssertNil(WatchPairLoginConnectivityPayload.parseAcknowledgment(
            WatchPairLoginConnectivityPayload.approvalMessage(
                WatchPairLoginApproval(token: "ABC123", pin: "A3F8Q6")
            )
        ))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testWatchSendLoginRequestDoesNotInstallOffActorReplyHandler() throws {
        let appleRoot = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let runtimeURL = appleRoot.appendingPathComponent(
            "OpenMates/Sources/Features/Auth/ViewModels/PairLoginRuntime.swift"
        )
        let source = try String(contentsOf: runtimeURL, encoding: .utf8)
        let methodStart = try XCTUnwrap(source.range(of: "func sendLoginRequest(_ request: WatchPairLoginRequest) -> Bool"))
        let methodEnd = try XCTUnwrap(
            source.range(of: "private nonisolated func dispatchToMain", range: methodStart.upperBound..<source.endIndex)
        )
        let methodSource = source[methodStart.lowerBound..<methodEnd.lowerBound]

        XCTAssertTrue(methodSource.contains("replyHandler: nil"))
        XCTAssertTrue(methodSource.contains("errorHandler: nil"))
        XCTAssertFalse(methodSource.contains("replyHandler: {"))
        XCTAssertFalse(methodSource.contains("errorHandler: {"))

        let delegateStart = try XCTUnwrap(
            source.range(of: "nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any])", range: methodEnd.upperBound..<source.endIndex)
        )
        let watchSectionEnd = try XCTUnwrap(source.range(of: "#endif", range: delegateStart.upperBound..<source.endIndex))
        let delegateSource = source[delegateStart.lowerBound..<watchSectionEnd.lowerBound]
        XCTAssertTrue(delegateSource.contains("WatchPairLoginConnectivityPayload.parseApproval(message)"))
        XCTAssertTrue(delegateSource.contains("bridge.approvalHandler?(approval)"))
        XCTAssertTrue(delegateSource.contains("WatchPairLoginConnectivityPayload.parseAcknowledgment(message)"))
        XCTAssertTrue(delegateSource.contains("bridge.acknowledgmentHandler?(acknowledgment)"))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.private-session
    func testPairV2ContextAndAEADRejectTamperedContextOrCiphertext() throws {
        let context = try PairV2Context(
            token: "ABC123", sessionID: "test-session",
            receiverTokenHash: String(repeating: "a", count: 64),
            authorizerUserID: "test-user", autoLogoutMinutes: 30
        )
        XCTAssertEqual(context.string,
            "[\"openmates-pair\",2,\"ABC123\",\"test-session\",\"" + String(repeating: "a", count: 64) + "\",\"test-user\",30]")
        let slashContext = try PairV2Context(
            token: "ABC123", sessionID: "test/session",
            receiverTokenHash: String(repeating: "a", count: 64),
            authorizerUserID: "test-user", autoLogoutMinutes: 30
        )
        XCTAssertTrue(slashContext.string.contains("\"test/session\""))
        XCTAssertThrowsError(try PairV2Crypto.decode("AB"))
        let sessionKey = PairV2Crypto.encode(Data((0..<64).map(UInt8.init)))
        let plaintext = Data(#"{"protocol_version":2,"user_id":"test-user"}"#.utf8)
        let sealed = try PairV2Crypto.seal(plaintext, sessionKey: sessionKey, context: context)
        XCTAssertEqual(try PairV2Crypto.open(
            ciphertext: sealed.ciphertext, iv: sealed.iv,
            sessionKey: sessionKey, context: context
        ), plaintext)
        // Fixed WebCrypto fixture generated with @repo/pairing-crypto's HKDF,
        // AES-GCM layout, and context AAD (synthetic test material only).
        XCTAssertEqual(try PairV2Crypto.open(
            ciphertext: "0o_xVxo6DVOCSns-o9es-LmKyGPYrNnI8412JjkQsGSUOgKX0YEYJslzyidYhQAYMFUxEfY6DQR41Eby",
            iv: "AAECAwQFBgcICQoL",
            sessionKey: sessionKey, context: context
        ), plaintext)
        let wrongContext = try PairV2Context(
            token: context.token, sessionID: context.sessionID,
            receiverTokenHash: context.receiverTokenHash,
            authorizerUserID: context.authorizerUserID, autoLogoutMinutes: 60
        )
        XCTAssertThrowsError(try PairV2Crypto.open(
            ciphertext: sealed.ciphertext, iv: sealed.iv,
            sessionKey: sessionKey, context: wrongContext
        ))
        let wrongSessionKey = PairV2Crypto.encode(Data(repeating: 0x5a, count: 64))
        XCTAssertThrowsError(try PairV2Crypto.open(
            ciphertext: sealed.ciphertext, iv: sealed.iv,
            sessionKey: wrongSessionKey, context: context
        ))
        var tampered = try PairV2Crypto.decode(sealed.ciphertext)
        tampered[0] ^= 1
        XCTAssertThrowsError(try PairV2Crypto.open(
            ciphertext: PairV2Crypto.encode(tampered), iv: sealed.iv,
            sessionKey: sessionKey, context: context
        ))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.private-session
    func testPairV2BundleRequiresEncryptedAccountBindingAndCanonicalPIN() throws {
        XCTAssertTrue(PairLoginRuntime.isValidPIN("ABCD36"))
        XCTAssertFalse(PairLoginRuntime.isValidPIN("ÅBCD36"))
        XCTAssertFalse(PairLoginRuntime.isValidPIN("ABCD37"))
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let missingBinding = Data(#"{"protocol_version":2,"master_key_exported":"x","grant_secret":"y","user_email_salt":"z","hashed_email":"h","user_id":"u"}"#.utf8)
        XCTAssertThrowsError(try decoder.decode(PairV2Bundle.self, from: missingBinding))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.private-session
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
