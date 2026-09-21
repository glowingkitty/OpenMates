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

    private func user(_ id: String) throws -> UserProfile {
        try JSONDecoder().decode(UserProfile.self,
            from: JSONSerialization.data(withJSONObject: ["id": id, "username": "Fixture"]))
    }
}
