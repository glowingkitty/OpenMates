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
        XCTAssertTrue(delegateSource.contains("bridge.receiveApproval(approval)"))
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


#if os(iOS)
// Supporting proof: real PhoneWatchLoginBridge, synthetic transport/time/account.
@MainActor
final class WatchPhonePairApprovalTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback,apple-watch.pairing.private-session
    func testUnreachableAndAsynchronousErrorRetryWithoutReauthorizing() async throws {
        let h = try Harness()
        h.offer()
        let flight = Task { try await h.bridge.approvePendingRequest(authManager: h.auth) }
        await settle { h.bridge.hasPendingApproval }
        XCTAssertEqual(h.authorizations, 1)
        XCTAssertEqual(h.sends, 0)
        XCTAssertNotNil(h.bridge.pendingRequest)
        h.reachable = true
        await settle { h.sends > 0 }
        XCTAssertFalse(h.bridge.pinReceiptReceived)
        XCTAssertTrue(h.bridge.hasPendingApproval)
        h.delivers = true
        await settle { h.bridge.pinReceiptReceived }
        XCTAssertEqual(h.authorizations, 1)
        XCTAssertNotNil(h.bridge.pendingRequest, "PIN receipt alone must not dismiss pairing")
        h.status = "completed"
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertTrue(h.bridge.hasPendingApproval, "Server completion precedes durable acknowledgement")
        h.status = "acknowledged"
        try await flight.value
        XCTAssertEqual(h.bridge.completedRequestToken, "ABC123")
        XCTAssertNil(h.bridge.pendingRequest)
        XCTAssertFalse(h.bridge.hasPendingApproval)
        XCTAssertEqual(h.remoteCancellations, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback,apple-watch.pairing.private-session
    func testLostPINReplyAfterWatchAuthenticationCompletesViaBoundedReceiptReplay() async throws {
        let h = try Harness()
        h.reachable = true
        h.dropsFirstReceipt = true
        h.offer()
        let flight = Task { try await h.bridge.approvePendingRequest(authManager: h.auth) }
        await settle { h.receipts.count == 1 }
        XCTAssertEqual(h.status, "acknowledged")
        XCTAssertTrue(h.bridge.hasPendingApproval, "Server acknowledgement alone cannot replace PIN receipt")
        XCTAssertFalse(h.bridge.pinReceiptReceived)
        XCTAssertEqual(h.authorizations, 1)
        XCTAssertEqual(h.sends, 2)
        // The second send matched the same production receiver receipt cache;
        // it reapplied neither the PIN nor PAKE. Release that cached receipt.
        h.receipts[0]("ABC123")
        try await flight.value
        XCTAssertEqual(h.bridge.completedRequestToken, "ABC123")
        XCTAssertEqual(h.authorizations, 1)
        XCTAssertNil(h.bridge.pendingRequest)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback,apple-watch.pairing.private-session
    func testConcurrentAcceptWaitsForOneApprovalAndOneCompletion() async throws {
        let h = try Harness()
        h.offer()
        let first = Task { try await h.bridge.approvePendingRequest(authManager: h.auth) }
        await settle { h.bridge.hasPendingApproval }
        let second = Task { try await h.bridge.approvePendingRequest(authManager: h.auth) }
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertEqual(h.authorizations, 1)
        h.reachable = true
        h.delivers = true
        h.status = "acknowledged"
        try await first.value
        try await second.value
        XCTAssertEqual(h.authorizations, 1)
        XCTAssertEqual(h.bridge.completedRequestToken, "ABC123")
        XCTAssertEqual(h.remoteCancellations, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback,apple-watch.pairing.private-session
    func testWrongAndLateReceiptCannotClearReplacementApproval() async throws {
        let h = try Harness()
        h.reachable = true
        h.holdsReply = true
        h.offer()
        let oldFlight = Task { try await h.bridge.approvePendingRequest(authManager: h.auth) }
        await settle { h.receipts.count == 1 }
        let oldReply = h.receipts[0]
        oldReply("DEF456")
        XCTAssertFalse(h.bridge.pinReceiptReceived)
        await settle { h.receipts.count >= 2 }
        let delayed = h.receipts[1]
        h.offer(token: "DEF456")
        let newFlight = Task { try await h.bridge.approvePendingRequest(authManager: h.auth) }
        await settle { h.authorizations == 2 && h.receipts.count >= 3 }
        delayed("ABC123")
        XCTAssertFalse(h.bridge.pinReceiptReceived)
        XCTAssertEqual(h.bridge.pendingRequest?.token, "DEF456")
        h.receipts.last?("DEF456")
        XCTAssertTrue(h.bridge.pinReceiptReceived)
        h.receipts.last?("DEF456")
        XCTAssertTrue(h.bridge.pinReceiptReceived, "Duplicate receipt is idempotent")
        h.status = "acknowledged"
        try await newFlight.value
        do { try await oldFlight.value; XCTFail("Replaced request must fail") } catch {}
        XCTAssertEqual(h.bridge.completedRequestToken, "DEF456")
        XCTAssertEqual(h.authorizations, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback,apple-watch.pairing.private-session
    func testBackendExpiryLogoutCancelAndProfileFenceWipeApproval() async throws {
        for fence in ["expiry", "logout", "cancel", "profile", "account"] {
            let h = try Harness()
            h.offer()
            let flight = Task { try await h.bridge.approvePendingRequest(authManager: h.auth) }
            await settle { h.bridge.hasPendingApproval }
            switch fence {
            case "expiry": h.now = h.expiresAt
            case "logout": h.auth.state = .unauthenticated
            case "cancel": h.bridge.denyPendingRequest()
            case "profile": h.profile = .production
            default: h.auth.currentUser = try Harness.user("other-fixture-user")
            }
            await settle { !h.bridge.hasPendingApproval && h.bridge.pendingRequest == nil }
            h.reachable = true
            h.delivers = true
            do { try await flight.value; XCTFail("Fenced request must fail: \(fence)") } catch {}
            XCTAssertEqual(h.sends, 0, fence)
            XCTAssertNil(h.bridge.completedRequestToken, fence)
            await settle { h.remoteCancellations >= 1 }
            XCTAssertEqual(h.authorizations, 1, fence)
            await settle { h.relayCancelled }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback,apple-watch.pairing.private-session
    func testTransientAuthorizerPollErrorKeepsApprovalUntilMatchingReceiptAndAck() async throws {
        let h = try Harness()
        h.reachable = true
        h.delivers = true
        h.pollFails = true
        h.offer()
        let flight = Task { try await h.bridge.approvePendingRequest(authManager: h.auth) }
        await settle { h.bridge.pinReceiptReceived && h.polls >= 2 }
        XCTAssertTrue(h.bridge.hasPendingApproval)
        XCTAssertNotNil(h.bridge.pendingRequest)
        h.pollFails = false
        h.status = "acknowledged"
        try await flight.value
        XCTAssertEqual(h.authorizations, 1)
        XCTAssertEqual(h.sends, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.private-session
    func testReceiverRejectsMalformedPINAndStaleAttemptAndReceiptContainsNoPIN() {
        let approval = WatchPairLoginApproval(token: "ABC123", pin: "ABC346")
        for status in [PairLoginStatus.waiting, .ready] {
            XCTAssertTrue(WatchPairLoginConnectivityPayload.canReceiveApproval(approval, token: "ABC123", status: status))
        }
        XCTAssertFalse(WatchPairLoginConnectivityPayload.canReceiveApproval(approval, token: "DEF456", status: .ready))
        XCTAssertFalse(WatchPairLoginConnectivityPayload.canReceiveApproval(
            WatchPairLoginApproval(token: "ABC123", pin: "123456"), token: "ABC123", status: .ready))
        for status in [PairLoginStatus.failed, .expired, .generating] {
            XCTAssertFalse(WatchPairLoginConnectivityPayload.canReceiveApproval(approval, token: "ABC123", status: status))
        }
        let receipt = WatchPairLoginConnectivityPayload.approvalReceiptMessage(token: "ABC123")
        XCTAssertEqual(WatchPairLoginConnectivityPayload.parseApprovalReceipt(receipt), "ABC123")
        XCTAssertNil(receipt["pin"])
        XCTAssertFalse(WatchPairLoginConnectivityPayload.containsForbiddenSecretKeys(receipt))
        var corrupt = receipt
        corrupt["pin"] = "ABC346"
        XCTAssertNil(WatchPairLoginConnectivityPayload.parseApprovalReceipt(corrupt))
    }

    private func settle(_ predicate: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async {
        for _ in 0..<500 {
            if predicate() { return }
            try? await Task.sleep(for: .milliseconds(2))
        }
        XCTAssertTrue(predicate(), "Expected bridge transition", file: file, line: line)
    }

    @MainActor private final class Harness {
        let auth = AuthManager()
        private(set) var bridge: PhoneWatchLoginBridge!
        var now = 10_000
        var expiresAt = 10_030
        var profile = ServerProfile.development
        var reachable = false
        var delivers = false
        var holdsReply = false
        var dropsFirstReceipt = false
        var receiverReceipt = WatchPairApprovalReceiptCache()
        var pollFails = false
        var status = "approved"
        var authorizations = 0
        var sends = 0
        var polls = 0
        var remoteCancellations = 0
        var relayCancelled = false
        var receipts: [@MainActor (String?) -> Void] = []

        static func user(_ id: String) throws -> UserProfile {
            let data = try JSONSerialization.data(withJSONObject: ["id": id, "username": "pair-fixture"])
            return try JSONDecoder().decode(UserProfile.self, from: data)
        }

        init() throws {
            auth.currentUser = try Self.user("pair-fixture-user")
            auth.state = .authenticated
            var dependencies = PhoneWatchPairDependencies()
            dependencies.usesConnectivity = false
            dependencies.offersNotification = false
            dependencies.profile = { [weak self] in self?.profile ?? .development }
            dependencies.now = { [weak self] in self?.now ?? 0 }
            dependencies.reachable = { [weak self] in self?.reachable ?? false }
            dependencies.authorize = { [weak self] _, _ in
                guard let self else { throw CancellationError() }
                self.authorizations += 1
                let relay = Task { [weak self] in
                    do { try await Task.sleep(for: .seconds(60)) } catch {}
                    self?.relayCancelled = Task.isCancelled
                }
                return PairV2Authorization(pin: "ABC346", expiresAt: self.expiresAt, relayTask: relay)
            }
            dependencies.poll = { [weak self] _ in
                guard let self else { throw CancellationError() }
                self.polls += 1
                if self.pollFails { throw URLError(.networkConnectionLost) }
                return PairV2AuthorizerPoll(status: self.status, expiresAt: self.expiresAt,
                                           receiverRequest: nil, receiverFinish: nil)
            }
            dependencies.cancel = { [weak self] _ in self?.remoteCancellations += 1 }
            dependencies.send = { [weak self] approval, completion in
                guard let self else { completion(nil); return }
                self.sends += 1
                if self.dropsFirstReceipt {
                    if self.sends == 1 {
                        guard self.receiverReceipt.remember(approval, profile: .development,
                            expiresAt: self.expiresAt, now: self.now) else { completion(nil); return }
                        self.status = "acknowledged"
                        completion(nil)
                    } else if self.receiverReceipt.matches(approval, profile: .development, now: self.now) {
                        self.receipts.append(completion)
                    } else { completion(nil) }
                } else if self.holdsReply { self.receipts.append(completion) }
                else { completion(self.delivers ? approval.token : nil) }
            }
            dependencies.pause = { try await Task.sleep(for: .milliseconds(10)) }
            bridge = PhoneWatchLoginBridge(dependencies: dependencies)
            bridge.start(isAuthenticated: { [weak self] in self?.auth.state == .authenticated })
        }

        func offer(token: String = "ABC123") {
            bridge.receive(WatchPairLoginRequest(token: token,
                pairURLString: "https://app.dev.openmates.org/#pair=\(token)", deviceName: "Fixture Watch",
                serverProfile: .development, createdAt: now))
        }
    }
}
#endif


// Supporting policy proof used by the Watch bridge after releasing its view.
@MainActor
final class WatchPairApprovalReceiptCacheTests: XCTestCase {
    private let original = WatchPairLoginApproval(token: "ABC123", pin: "ABC346")

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback,apple-watch.pairing.private-session
    func testAcceptedReceiptReplaysOnlyIdenticalTokenPINAndServer() {
        var cache = WatchPairApprovalReceiptCache()
        XCTAssertFalse(cache.matches(original, profile: .development, now: 10))
        XCTAssertTrue(cache.remember(original, profile: .development, expiresAt: 100, now: 10))
        XCTAssertTrue(cache.matches(original, profile: .development, now: 99))
        XCTAssertFalse(cache.matches(WatchPairLoginApproval(token: "DEF456", pin: original.pin), profile: .development, now: 20))
        XCTAssertFalse(cache.matches(WatchPairLoginApproval(token: original.token, pin: "DEF346"), profile: .development, now: 20))
        XCTAssertFalse(cache.matches(original, profile: .production, now: 20))
        XCTAssertFalse(cache.remember(WatchPairLoginApproval(token: original.token, pin: "DEF346"),
                                     profile: .development, expiresAt: 100, now: 20))
        XCTAssertTrue(cache.matches(original, profile: .development, now: 20))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.private-session
    func testActualExpiryCannotExtendOrReviveReceipt() {
        var cache = WatchPairApprovalReceiptCache()
        XCTAssertFalse(cache.remember(original, profile: .development, expiresAt: 10, now: 10))
        XCTAssertNil(cache.expiresAt)
        XCTAssertTrue(cache.remember(original, profile: .development, expiresAt: 100, now: 10))
        XCTAssertFalse(cache.remember(original, profile: .development, expiresAt: 200, now: 20),
                       "A late duplicate cannot replace backend expiry with arrival TTL")
        XCTAssertEqual(cache.expiresAt, 100)
        XCTAssertFalse(cache.matches(original, profile: .development, now: 100))
        cache.prune(profile: .development, now: 100)
        XCTAssertNil(cache.expiresAt)
        XCTAssertFalse(cache.matches(original, profile: .development, now: 99), "Expired receipt cannot revive")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.private-session
    func testReplacementLogoutAndProfileChangeDiscardPreviouslyAcceptedReceipt() {
        var cache = WatchPairApprovalReceiptCache()
        XCTAssertTrue(cache.remember(original, profile: .development, expiresAt: 100, now: 10))
        cache.clear() // Production bridge new-attempt/logout hooks use this operation.
        XCTAssertFalse(cache.matches(original, profile: .development, now: 20))
        let replacement = WatchPairLoginApproval(token: "DEF456", pin: "DEF346")
        XCTAssertTrue(cache.remember(replacement, profile: .development, expiresAt: 90, now: 20))
        XCTAssertFalse(cache.matches(original, profile: .development, now: 20))
        XCTAssertTrue(cache.matches(replacement, profile: .development, now: 20))
        cache.prune(profile: .production, now: 20)
        XCTAssertNil(cache.expiresAt)
        XCTAssertFalse(cache.matches(replacement, profile: .development, now: 20))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.private-session
    func testServerEquivalenceAndMalformedPINRespectExistingContract() {
        var cache = WatchPairApprovalReceiptCache()
        XCTAssertFalse(cache.remember(WatchPairLoginApproval(token: "ABC123", pin: "123456"),
                                     profile: .development, expiresAt: 100, now: 10))
        XCTAssertTrue(cache.remember(original, profile: .custom(domain: "app.dev.openmates.org"), expiresAt: 100, now: 10))
        XCTAssertTrue(cache.matches(original, profile: .development, now: 20))
        cache.prune(profile: .development, now: 20)
        XCTAssertEqual(cache.expiresAt, 100)
    }
}
