// Specification: specifications/features/auth/specification.yml
// Assertions: auth.session.lifecycle, auth.session.authoritative-enforcement, auth.session.isolation
// Real AuthManager session-validation transitions with a local transport.
// The error paths must preserve cached identity and avoid any Keychain/network IO.
import XCTest
@testable import OpenMates

@MainActor final class AuthSessionReauthenticationTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle
    func testRejectedSessionOffersReauthenticationWhilePreservingCachedIdentity() async throws {
        let auth = AuthManager(sessionValidator: { profile, _ in
            XCTAssertEqual(profile, ServerProfile.current())
            throw APIError.httpError(status: 401, message: "Expired")
        })
        auth.currentUser = try user("cached-account")
        auth.state = .authenticated
        await auth.validateSessionAfterOfflineBootstrap()
        XCTAssertEqual(auth.state, .authenticated)
        XCTAssertEqual(auth.currentUser?.id, "cached-account")
        XCTAssertEqual(auth.sessionValidationState, .requiresReauthentication(reason: "session_expired"))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,auth.session.authoritative-enforcement,auth.session.isolation
    func testForbiddenRefreshAfterOnlineAuthenticationStopsRecoveryAndPreservesCachedIdentity() async throws {
        var validations = 0
        let accepted = try sessionResponse(account: "cached-account", token: "previously-valid-token")
        let auth = AuthManager(sessionValidator: { _, _ in
            validations += 1
            if validations == 1 { return accepted }
            throw APIError.httpError(status: 403, message: "Rejected refresh")
        }, profileCacheWriter: { _ in }, sessionMasterKeyAvailable: { _ in true },
            sessionScopeActivator: { _ in })
        auth.currentUser = try user("cached-account")
        auth.state = .authenticated
        await auth.validateSessionAfterOfflineBootstrap()
        XCTAssertEqual(auth.sessionValidationState, .onlineAuthenticated)
        XCTAssertEqual(auth.webSocketToken, "previously-valid-token")
        let onlineContext = try XCTUnwrap(auth.sessionRecoveryContext)
        await AuthManager.recoverRejectedRequest(onlineContext)
        XCTAssertEqual(auth.sessionValidationState, .requiresReauthentication(reason: "session_expired"))
        XCTAssertNil(auth.webSocketToken)
        XCTAssertEqual(auth.currentUser?.id, "cached-account")
        XCTAssertEqual(auth.state, .authenticated, "Cached encrypted history must remain accessible")
        let rejectedContext = try XCTUnwrap(auth.sessionRecoveryContext)
        await AuthManager.recoverRejectedRequest(onlineContext)
        await AuthManager.recoverRejectedRequest(rejectedContext)
        XCTAssertEqual(validations, 2, "Neither stale nor current rejection callbacks may revive rejected credentials")
        XCTAssertEqual(auth.sessionValidationState, .requiresReauthentication(reason: "session_expired"))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle
    func testTemporaryNetworkFailureRetainsOfflineAccessWithoutRequestingLogin() async throws {
        let auth = AuthManager(sessionValidator: { _, _ in throw URLError(.timedOut) })
        auth.currentUser = try user("cached-account")
        auth.state = .authenticated
        await auth.validateSessionAfterOfflineBootstrap()
        XCTAssertEqual(auth.currentUser?.id, "cached-account")
        XCTAssertEqual(auth.state, .authenticated)
        XCTAssertEqual(auth.sessionValidationState, .offlineAuthenticated)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle
    func testExplicitSessionResponseKeepsItsReauthenticationReason() async throws {
        let response = try JSONDecoder().decode(SessionResponse.self,
            from: Data(#"{"success":false,"reAuthReason":"session_expired"}"#.utf8))
        let auth = AuthManager(sessionValidator: { _, _ in response })
        auth.currentUser = try user("cached-account")
        auth.state = .authenticated
        await auth.validateSessionAfterOfflineBootstrap()
        XCTAssertEqual(auth.currentUser?.id, "cached-account")
        XCTAssertEqual(auth.sessionValidationState, .requiresReauthentication(reason: "session_expired"))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle
    func testRejectedSessionWithoutCachedAccountRemainsUnauthenticated() async {
        let auth = AuthManager(sessionValidator: { _, _ in
            throw APIError.httpError(status: 401, message: "Expired")
        })
        await auth.validateSessionAfterOfflineBootstrap()
        XCTAssertNil(auth.currentUser)
        XCTAssertEqual(auth.state, .unauthenticated)
        XCTAssertEqual(auth.sessionValidationState, .unauthenticated)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle
    func testStaleValidationCannotOpenLoginForAReplacementAccount() async throws {
        var pending: CheckedContinuation<SessionResponse, Error>?
        let auth = AuthManager(sessionValidator: { _, _ in
            try await withCheckedThrowingContinuation { pending = $0 }
        })
        auth.currentUser = try user("account-A")
        auth.state = .authenticated
        let operation = Task { await auth.validateSessionAfterOfflineBootstrap() }
        while pending == nil { await Task.yield() }
        auth.currentUser = try user("account-B")
        pending?.resume(throwing: APIError.httpError(status: 401, message: "Expired A"))
        await operation.value
        XCTAssertEqual(auth.currentUser?.id, "account-B")
        if case .requiresReauthentication = auth.sessionValidationState {
            XCTFail("A rejected response for account A must not route account B to login")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,chat-navigation.open.local-first-coherent
    func testLocalAndRemoteLastOpenedSelectionUpdatesCachedProfileWithoutChangingAccount() throws {
        var cached: [UserProfile] = []
        let auth = AuthManager(profileCacheWriter: { cached.append($0) })
        auth.currentUser = try user("account-A")
        auth.state = .authenticated
        auth.updateLastOpened("chat-local", accountId: "account-A")
        auth.updateLastOpened("chat-remote", accountId: "account-A")
        XCTAssertEqual(auth.currentUser?.lastOpened, "chat-remote")
        XCTAssertEqual(cached.map(\.lastOpened), ["chat-local", "chat-remote"])
        auth.currentUser = try user("account-B")
        auth.updateLastOpened("old-account-chat", accountId: "account-A")
        auth.updateLastOpened("example-public", accountId: "account-B")
        auth.updateLastOpened("incognito-private", accountId: "account-B")
        auth.updateLastOpened("/chat/new", accountId: "account-B")
        XCTAssertNil(auth.currentUser?.lastOpened)
        XCTAssertEqual(cached.count, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,chat-navigation.open.local-first-coherent
    func testLateSessionRefreshPreservesNewerSelectionForSameAccountOnly() throws {
        let auth = AuthManager(profileCacheWriter: { _ in })
        let old = try user("account-A")
        auth.currentUser = old; auth.state = .authenticated
        let revision = auth.lastOpenedSelectionRevision
        auth.updateLastOpened("recent-selection", accountId: "account-A")
        XCTAssertEqual(auth.profilePreservingNewerSelection(old, since: revision).lastOpened, "recent-selection")
        XCTAssertNil(auth.profilePreservingNewerSelection(try user("account-B"), since: revision).lastOpened)
        var authoritative = old; authoritative.lastOpened = "server-selection"
        XCTAssertEqual(auth.profilePreservingNewerSelection(authoritative, since: auth.lastOpenedSelectionRevision).lastOpened, "server-selection")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,auth.session.isolation
    func testConcurrentHTTPAndSocketRecoveryShareValidationAndRotateCredentials() async throws {
        var pending: CheckedContinuation<SessionResponse, Error>?
        var validations = 0
        let auth = AuthManager(sessionValidator: { _, _ in
            validations += 1
            return try await withCheckedThrowingContinuation { pending = $0 }
        }, profileCacheWriter: { _ in }, sessionMasterKeyAvailable: { _ in true },
            sessionScopeActivator: { _ in })
        auth.currentUser = try user("cached-account")
        auth.state = .authenticated
        let expected = try XCTUnwrap(auth.sessionRecoveryContext)
        let first = Task { await AuthManager.recoverRejectedRequest(expected) }
        while pending == nil { await Task.yield() }
        let second = Task { await auth.recoverSession(expected: expected) }
        await Task.yield()
        XCTAssertEqual(validations, 1)
        pending?.resume(returning: try sessionResponse(account: "cached-account", token: "rotated-token"))
        await first.value
        await second.value
        XCTAssertEqual(auth.sessionValidationState, .onlineAuthenticated)
        XCTAssertEqual(auth.webSocketToken, "rotated-token")
        XCTAssertEqual(auth.currentUser?.id, "cached-account")
        // An old in-flight request's later 401 cannot invalidate these credentials.
        await auth.recoverSession(expected: expected)
        XCTAssertEqual(validations, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.authoritative-enforcement
    func testSessionServiceFailureKeepsOfflineIdentityAndDoesNotOpenLogin() async throws {
        let auth = AuthManager(sessionValidator: { _, _ in
            throw APIError.httpError(status: 503, message: "Unavailable")
        })
        auth.currentUser = try user("cached-account")
        auth.state = .authenticated
        await auth.recoverSession(expected: try XCTUnwrap(auth.sessionRecoveryContext))
        XCTAssertEqual(auth.currentUser?.id, "cached-account")
        XCTAssertEqual(auth.sessionValidationState, .offlineAuthenticated)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.authoritative-enforcement
    func testRevokedSessionRequiresLoginWithoutErasingCachedIdentity() async throws {
        let response = try JSONDecoder().decode(SessionResponse.self,
            from: Data(#"{"success":false,"reAuthReason":"session_revoked"}"#.utf8))
        let auth = AuthManager(sessionValidator: { _, _ in response })
        auth.currentUser = try user("cached-account")
        auth.state = .authenticated
        await auth.recoverSession(expected: try XCTUnwrap(auth.sessionRecoveryContext))
        XCTAssertEqual(auth.currentUser?.id, "cached-account")
        XCTAssertEqual(auth.state, .authenticated)
        XCTAssertEqual(auth.sessionValidationState, .requiresReauthentication(reason: "session_revoked"))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation
    func testSuccessfulSessionForAnotherAccountCannotReplaceCachedAccount() async throws {
        let response = try sessionResponse(account: "another-account", token: "other-token")
        let auth = AuthManager(sessionValidator: { _, _ in response })
        auth.currentUser = try user("cached-account")
        auth.state = .authenticated
        await auth.recoverSession(expected: try XCTUnwrap(auth.sessionRecoveryContext))
        XCTAssertEqual(auth.currentUser?.id, "cached-account")
        XCTAssertNil(auth.webSocketToken)
        XCTAssertEqual(auth.sessionValidationState, .requiresReauthentication(reason: "session_account_changed"))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation
    func testServerChangeFencesPendingRejection() async throws {
        let original = ServerConfiguration.current
        defer { ServerConfiguration.current = original }
        var pending: CheckedContinuation<SessionResponse, Error>?
        let auth = AuthManager(sessionValidator: { _, _ in
            try await withCheckedThrowingContinuation { pending = $0 }
        })
        auth.currentUser = try user("cached-account")
        auth.state = .authenticated
        let expected = try XCTUnwrap(auth.sessionRecoveryContext)
        let operation = Task { await auth.recoverSession(expected: expected) }
        while pending == nil { await Task.yield() }
        ServerConfiguration.current = ServerEndpointConfiguration(
            selectedDomain: "session-fence.example", customDomains: ["session-fence.example"])
        pending?.resume(throwing: APIError.httpError(status: 401, message: "Expired"))
        await operation.value
        XCTAssertEqual(auth.currentUser?.id, "cached-account")
        if case .requiresReauthentication = auth.sessionValidationState {
            XCTFail("The former server must not challenge the newly selected server")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.lookup.anti-enumeration,auth.login.method-convergence
    func testPreTFAResponseDecodesNullIDAsChallengeWithoutPublishingProfile() throws {
        let response = try loginResponse(#"{"success":true,"tfa_required":true,"user":{"id":null,"username":"","tfa_enabled":true}}"#)
        XCTAssertTrue(response.success)
        XCTAssertEqual(response.tfaRequired, true)
        XCTAssertNil(response.user)
        XCTAssertFalse(response.hasAcceptedPasswordIdentity)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.lookup.anti-enumeration,auth.login.method-convergence
    func testRealAndDecoyPreTFAProfilesRemainChallengeMetadata() throws {
        let actual = try loginResponse(#"{"success":true,"tfa_required":true,"user":{"id":"fixture-account","username":"","tfa_enabled":true}}"#)
        let omitted = try loginResponse(#"{"success":true,"tfa_required":true,"user":null}"#)
        XCTAssertEqual(actual.tfaRequired, omitted.tfaRequired)
        XCTAssertNil(actual.user)
        XCTAssertNil(omitted.user)
        XCTAssertTrue(actual.hasAcceptedPasswordIdentity)
        XCTAssertFalse(omitted.hasAcceptedPasswordIdentity)
        for identity in [#"{}"#, #"{"id":""}"#] {
            let empty = try loginResponse("{\"success\":true,\"tfa_required\":true,\"user\":\(identity)}")
            XCTAssertNil(empty.user)
            XCTAssertFalse(empty.hasAcceptedPasswordIdentity)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence,auth.session.authoritative-enforcement
    func testFinalLoginStillRejectsNullOrMissingProfileID() throws {
        for payload in [
            #"{"success":true,"tfa_required":false,"user":{"id":null,"username":""}}"#,
            #"{"success":true,"user":{"username":"Fixture"}}"#,
        ] {
            XCTAssertThrowsError(try loginResponse(payload))
        }
        let completed = try loginResponse(#"{"success":true,"tfa_required":false,"user":{"id":"fixture-account","username":"Fixture"},"ws_token":"fixture-socket"}"#)
        XCTAssertEqual(completed.user?.id, "fixture-account")
        XCTAssertEqual(completed.wsToken, "fixture-socket")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.lookup.anti-enumeration,auth.login.method-convergence
    func testProductionPasswordLoginRoutesDocumentedDecoyToTFAWithoutAuthenticating() async throws {
        try await withPasswordTransport { auth, transport in
            let initialState = auth.state
            let initialValidationState = auth.sessionValidationState
            do {
                try await fixturePasswordLogin(auth)
                XCTFail("Pre-TFA response must not complete login")
            } catch AuthError.tfaRequired {}
            XCTAssertEqual(transport.loginVersions, [2, 1])
            XCTAssertNil(auth.currentUser)
            XCTAssertNil(auth.webSocketToken)
            XCTAssertEqual(auth.state, initialState)
            XCTAssertEqual(auth.sessionValidationState, initialValidationState)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.lookup.anti-enumeration,auth.login.method-convergence
    func testDecoyV2FallsBackToLegacyForTFAAndCompletedServerLogin() async throws {
        try await withPasswordTransport { auth, transport in
            transport.legacyTFAHasIdentity = true
            do {
                try await fixturePasswordLogin(auth)
                XCTFail("Legacy TFA must challenge before login")
            } catch AuthError.tfaRequired {}
            XCTAssertEqual(transport.loginVersions, [2, 1])
            XCTAssertNil(auth.currentUser)
            do {
                try await fixturePasswordLogin(auth, tfaCode: "123456")
                XCTFail("Fixture intentionally omits the key wrapper")
            } catch AuthError.missingAuthData {}
            // Reaching key unwrap proves the completed legacy server response was
            // accepted, without saving keys or publishing a synthetic account.
            XCTAssertEqual(transport.loginVersions, [2, 1, 2, 1])
            XCTAssertEqual(transport.legacyTFACodes, ["123456"])
            XCTAssertNil(auth.currentUser)
            XCTAssertNil(auth.webSocketToken)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence,auth.session.authoritative-enforcement
    func testLegitimateV2TFAKeepsV2WithoutPublishingProfileOrFallingBack() async throws {
        try await withPasswordTransport { auth, transport in
            transport.v2Payload = PasswordTFAURLProtocol.realTFA
            do {
                try await fixturePasswordLogin(auth)
                XCTFail("Real v2 TFA must challenge before login")
            } catch AuthError.tfaRequired {}
            XCTAssertEqual(transport.loginVersions, [2])
            XCTAssertNil(auth.currentUser)
            XCTAssertNil(auth.webSocketToken)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence,auth.session.authoritative-enforcement
    func testCompletedV2ServerLoginDoesNotFallBack() async throws {
        try await withPasswordTransport { auth, transport in
            transport.v2Payload = PasswordTFAURLProtocol.completedLogin
            do {
                try await fixturePasswordLogin(auth)
                XCTFail("Fixture intentionally omits the key wrapper")
            } catch AuthError.missingAuthData {}
            XCTAssertEqual(transport.loginVersions, [2])
            XCTAssertNil(auth.currentUser)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence,auth.session.authoritative-enforcement
    func testV2CredentialRejectionsClearProofMarkersBeforeLegacyFallback() async throws {
        for status in [401, 403] {
            for failsChallenge in [true, false] {
                try await withPasswordTransport { auth, transport in
                    if failsChallenge { transport.challengeStatus = status }
                    else { transport.loginStatus = status }
                    transport.legacyTFAHasIdentity = true
                    do {
                        try await fixturePasswordLogin(auth)
                        XCTFail("Rejected v2 credentials must fall back to a legacy TFA challenge")
                    } catch AuthError.tfaRequired {}
                    XCTAssertEqual(transport.loginVersions, failsChallenge ? [1] : [2, 1])
                    XCTAssertNil(auth.currentUser)
                    XCTAssertNil(auth.webSocketToken)
                }
            }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence,auth.session.authoritative-enforcement
    func testV2RateLimitAndServiceErrorsNeverFallBack() async throws {
        for status in [429, 500, 503] {
            for failsChallenge in [true, false] {
                try await withPasswordTransport { auth, transport in
                    if failsChallenge { transport.challengeStatus = status }
                    else { transport.loginStatus = status }
                    do {
                        try await fixturePasswordLogin(auth)
                        XCTFail("HTTP failure must propagate")
                    } catch APIError.httpError(let actualStatus, _) {
                        XCTAssertEqual(actualStatus, status)
                    }
                    XCTAssertEqual(transport.loginVersions, failsChallenge ? [] : [2])
                    XCTAssertNil(auth.currentUser)
                }
            }
        }
    }

    private func fixturePasswordLogin(_ auth: AuthManager, tfaCode: String? = nil) async throws {
        try await auth.loginWithPassword(email: "fixture@example.test", password: "FixturePassword1!",
            userEmailSalt: Data((0..<16).map(UInt8.init)).base64EncodedString(), tfaCode: tfaCode)
    }

    private func withPasswordTransport(
        _ operation: (AuthManager, PasswordTFAURLProtocol.Fixture) async throws -> Void
    ) async throws {
        let originalProfile = ServerConfiguration.current
        ServerConfiguration.current = ServerProfile.custom(domain: "password-tfa-fixture.example").endpointConfiguration
        let fixture = PasswordTFAURLProtocol.Fixture()
        PasswordTFAURLProtocol.setFixture(fixture)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [PasswordTFAURLProtocol.self]
        let session = URLSession(configuration: configuration)
        defer {
            session.invalidateAndCancel()
            PasswordTFAURLProtocol.setFixture(nil)
            ServerConfiguration.current = originalProfile
        }
        let api = APIClient(session: session, cookieStorage: try XCTUnwrap(configuration.httpCookieStorage))
        try await operation(AuthManager(api: api, profileCacheWriter: { _ in }), fixture)
    }

    private func loginResponse(_ payload: String) throws -> LoginResponse {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(LoginResponse.self, from: Data(payload.utf8))
    }

    private func sessionResponse(account: String, token: String) throws -> SessionResponse {
        try JSONDecoder().decode(SessionResponse.self, from: JSONSerialization.data(withJSONObject: [
            "success": true, "user": ["id": account, "username": "Fixture"], "wsToken": token
        ]))
    }

    private func user(_ id: String) throws -> UserProfile {
        try JSONDecoder().decode(UserProfile.self,
            from: JSONSerialization.data(withJSONObject: ["id": id, "username": "Fixture"]))
    }
}

// Deterministic transport for the real password challenge/login path. This
// protocol intercepts every request; it cannot contact a reserved or live account.
private final class PasswordTFAURLProtocol: URLProtocol, @unchecked Sendable {
    static let decoyTFA = #"{"success":true,"message":"2FA required","tfa_required":true,"user":{"id":null,"username":"","tfa_enabled":true}}"#
    static let realTFA = #"{"success":true,"tfa_required":true,"user":{"id":"fixture-account","username":"","tfa_enabled":true}}"#
    static let completedLogin = #"{"success":true,"tfa_required":false,"user":{"id":"fixture-account","username":"Fixture"}}"#

    final class Fixture: @unchecked Sendable {
        private let lock = NSLock()
        var v2Payload = PasswordTFAURLProtocol.decoyTFA
        var legacyTFAHasIdentity = false
        var challengeStatus = 200
        var loginStatus = 200
        private var versions: [Int] = []
        private var codes: [String] = []
        var loginVersions: [Int] { lock.lock(); defer { lock.unlock() }; return versions }
        var legacyTFACodes: [String] { lock.lock(); defer { lock.unlock() }; return codes }

        func loginPayload(_ body: [String: Any]) -> String {
            lock.lock(); defer { lock.unlock() }
            let version = body["credential_version"] as? Int ?? 1
            versions.append(version)
            if version == 2 { return v2Payload }
            XCTAssertNil(body["challenge_id"])
            XCTAssertNil(body["password_proof"])
            XCTAssertNotNil(body["lookup_hash"] as? String)
            if let code = body["tfa_code"] as? String {
                codes.append(code)
                XCTAssertEqual(body["code_type"] as? String, "otp")
                return PasswordTFAURLProtocol.completedLogin
            }
            return legacyTFAHasIdentity ? PasswordTFAURLProtocol.realTFA : PasswordTFAURLProtocol.decoyTFA
        }
    }

    private static let fixtureLock = NSLock()
    nonisolated(unsafe) private static var fixture: Fixture?
    static func setFixture(_ fixture: Fixture?) { fixtureLock.withLock { Self.fixture = fixture } }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let fixture = Self.fixtureLock.withLock({ Self.fixture }) else {
            client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL))
            return
        }
        let payload: Data
        let status: Int
        switch request.url?.path {
        case "/v1/auth/password-v2/challenge":
            status = fixture.challengeStatus
            payload = try! JSONSerialization.data(withJSONObject: ["challenge_id": "fixture-challenge",
                "nonce": Data(repeating: 0, count: 32).base64URLEncodedString(), "expires_in": 120])
        case "/v1/auth/login":
            guard let bodyData = requestBody(),
                  let body = (try? JSONSerialization.jsonObject(with: bodyData)) as? [String: Any] else {
                XCTFail("Password request must contain its encoded login body")
                client?.urlProtocol(self, didFailWithError: URLError(.cannotParseResponse))
                return
            }
            status = (body["credential_version"] as? Int) == 2 ? fixture.loginStatus : 200
            payload = Data(fixture.loginPayload(body).utf8)
        default:
            XCTFail("Unexpected password-flow endpoint")
            client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL))
            return
        }
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil,
            headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: payload)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}

    private func requestBody() -> Data? {
        if let body = request.httpBody { return body }
        guard let stream = request.httpBodyStream else { return nil }
        stream.open()
        defer { stream.close() }
        var body = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count < 0 { return nil }
            if count == 0 { break }
            body.append(contentsOf: buffer.prefix(count))
        }
        return body
    }
}
