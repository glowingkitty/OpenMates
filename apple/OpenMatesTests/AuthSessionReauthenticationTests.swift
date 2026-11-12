// Specification: specifications/features/auth/specification.yml
// Assertions: auth.session.lifecycle, auth.session.authoritative-enforcement, auth.session.isolation
// App-local AuthManager behavior that stays in Swift after the Rust core took
// over session validation and password login: last-opened selection, login
// response decoding of the Swift ceremonies, client identity headers and the
// push registration burst. Session transitions: AuthManagerCoreTests.
import XCTest
@testable import OpenMates

@MainActor final class AuthSessionReauthenticationTests: XCTestCase {
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

    // contract-test: supporting surface=gui.apple assertions=auth.session.authoritative-enforcement
    func testClientIdentityPreservesUserAgentAndSanitizesCoarseBuildHeaders() {
        let identity = NativeClientIdentity(appVersion: "0.6.0", appBuild: "107", deviceClass: "ipad")
        XCTAssertEqual(identity.headers["X-OpenMates-App-Version"], "0.6.0")
        XCTAssertEqual(identity.headers["X-OpenMates-App-Build"], "107")
        XCTAssertEqual(identity.headers["X-OpenMates-Device-Class"], "ipad")
        var request = URLRequest(url: URL(string: "https://api.example.test/v1/auth/session")!)
        request.setValue("https://app.example.test", forHTTPHeaderField: "Origin")
        identity.apply(to: &request)
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-OpenMates-App-Build"), "107")
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-OpenMates-Device-Class"), "ipad")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Origin"), "https://app.example.test")
        let invalid = NativeClientIdentity(appVersion: "bad\nvalue", appBuild: nil, deviceClass: "private-device-name")
        XCTAssertEqual(invalid.appVersion, "1.0.0")
        XCTAssertEqual(invalid.appBuild, "unknown")
        XCTAssertEqual(invalid.deviceClass, "unknown")
        XCTAssertEqual(APIClient.nativeClientHeaders["User-Agent"], "OpenMates-Apple/" + NativeClientIdentity.current.appVersion)
        for path in ["/v1/auth/sessions", "/v1/auth/passkeys", "/v1/notifications/register-device", "/v1/projects"] {
            XCTAssertTrue(APIClient.requiresProtectedAuthority(path: path))
        }
        XCTAssertFalse(APIClient.requiresProtectedAuthority(path: "/v1/auth/2fa/verify/device"))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.authoritative-enforcement,apple-notifications.registration.lifecycle
    func testExhaustedPushBurstDoesNotRestartForSameCredentialOnForegroundRefresh() async {
        let profile = ServerProfile.current()
        let scope = UUID()
        var context: PushRegistrationContext? = .init(accountID: "cached-account", profile: profile,
            scope: scope, authorityGeneration: UUID())
        var calls = 0
        let exhausted = expectation(description: "first bounded burst completed")
        var observedFirstExhaustion = false
        let resumed = expectation(description: "new verified authority resumed once")
        let registration = PushDeviceRegistration(context: { context }, register: { _, _ in
            calls += 1
            if calls <= 2 { throw URLError(.timedOut) }
        }, sleep: { _ in }, retryDelays: [.milliseconds(1)], acknowledge: { acknowledged in
            // Invalidation also publishes false without another registration attempt.
            if calls == 2, !acknowledged, !observedFirstExhaustion {
                observedFirstExhaustion = true
                exhausted.fulfill()
            }
            if acknowledged { resumed.fulfill() }
        })
        registration.refresh(token: "synthetic-token")
        await fulfillment(of: [exhausted], timeout: 1)
        await Task.yield()
        for _ in 0..<20 { registration.refresh(token: "synthetic-token"); await Task.yield() }
        XCTAssertEqual(calls, 2)
        context = nil
        registration.refresh(token: "synthetic-token")
        for _ in 0..<20 { registration.refresh(token: "synthetic-token"); await Task.yield() }
        XCTAssertEqual(calls, 2, "Blocked cached identity cannot register")
        context = .init(accountID: "cached-account", profile: profile, scope: scope, authorityGeneration: UUID())
        registration.refresh(token: "synthetic-token")
        await fulfillment(of: [resumed], timeout: 1)
        for _ in 0..<20 { registration.refresh(token: "synthetic-token"); await Task.yield() }
        XCTAssertEqual(calls, 3)
    }

    private func loginResponse(_ payload: String) throws -> LoginResponse {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(LoginResponse.self, from: Data(payload.utf8))
    }

    private func user(_ id: String) throws -> UserProfile {
        try JSONDecoder().decode(UserProfile.self,
            from: JSONSerialization.data(withJSONObject: ["id": id, "username": "Fixture"]))
    }
}
