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
    }

    // contract-test: supporting surface=gui.apple assertions=auth.lookup.anti-enumeration,auth.login.method-convergence
    func testRealAndDecoyPreTFAProfilesRemainChallengeMetadata() throws {
        let actual = try loginResponse(#"{"success":true,"tfa_required":true,"user":{"id":"fixture-account","username":"","tfa_enabled":true}}"#)
        let omitted = try loginResponse(#"{"success":true,"tfa_required":true,"user":null}"#)
        XCTAssertEqual(actual.tfaRequired, omitted.tfaRequired)
        XCTAssertNil(actual.user)
        XCTAssertNil(omitted.user)
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
        let originalProfile = ServerConfiguration.current
        ServerConfiguration.current = ServerProfile.custom(domain: "password-tfa-fixture.example").endpointConfiguration
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [PasswordTFAURLProtocol.self]
        let session = URLSession(configuration: configuration)
        defer {
            session.invalidateAndCancel()
            ServerConfiguration.current = originalProfile
        }
        let api = APIClient(session: session, cookieStorage: try XCTUnwrap(configuration.httpCookieStorage))
        let auth = AuthManager(api: api, profileCacheWriter: { _ in })
        let initialState = auth.state
        let initialValidationState = auth.sessionValidationState
        do {
            try await auth.loginWithPassword(email: "fixture@example.test", password: "FixturePassword1!",
                userEmailSalt: Data((0..<16).map(UInt8.init)).base64EncodedString())
            XCTFail("Pre-TFA response must not complete login")
        } catch AuthError.tfaRequired {}
        XCTAssertNil(auth.currentUser)
        XCTAssertNil(auth.webSocketToken)
        XCTAssertEqual(auth.state, initialState)
        XCTAssertEqual(auth.sessionValidationState, initialValidationState)
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
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let payload: Data
        switch request.url?.path {
        case "/v1/auth/password-v2/challenge":
            payload = try! JSONSerialization.data(withJSONObject: ["challenge_id": "fixture-challenge",
                "nonce": Data(repeating: 0, count: 32).base64URLEncodedString(), "expires_in": 120])
        case "/v1/auth/login":
            payload = Data(#"{"success":true,"message":"2FA required","tfa_required":true,"user":{"id":null,"username":"","tfa_enabled":true}}"#.utf8)
        default:
            XCTFail("Unexpected password-flow endpoint")
            client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL))
            return
        }
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil,
            headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: payload)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
