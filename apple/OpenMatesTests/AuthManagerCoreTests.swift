// AuthManager as a thin state holder over the Rust core (plan
// apple-client-core-migration A4 lane 1): its auth state follows the core's
// session states, a restored session unlocks the core's cached profile
// offline, sign-out clears it, failed core logins (password, backup code,
// recovery key, passkey) are typed errors and leave the app signed out, the
// core's passkey reasons map to the app's passkey errors, and the core's
// snake_case user payload decodes into the app's profile. The core reads are injected or come from a
// real core over an in-memory credential store; the API host never resolves,
// so nothing reaches a network or the Keychain.
import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class AuthManagerCoreTests: XCTestCase {
    private static let profileJSON = Data("""
        {"id":"fixture-account","username":"Fixture","email":"user@example.org",
         "last_opened":"fixture-chat","user_email_salt":"c3ludGhldGljLXNhbHQ=",
         "credential_version":2,"push_notification_enabled":true}
        """.utf8)

    private func makeAuth(core: CoreSession? = nil, fresh: Bool = true) -> AuthManager {
        AuthManager(core: core, reads: AuthCoreReads(
                profile: { UserProfileRecord(json: Self.profileJSON, fresh: fresh) },
                socketGrant: { LegacySocketGrantRecord(sessionId: AuthManager.nativeSessionId, wsToken: "fixture-token") }),
            profileCacheWriter: { _ in }, sessionScopeActivator: { _ in })
    }

    private func makeCore() throws -> CoreSession {
        let container = FileManager.default.temporaryDirectory.path
        let name = "auth-manager-core-\(UUID().uuidString)"
        let directory = (container as NSString).appendingPathComponent(name)
        addTeardownBlock { try? FileManager.default.removeItem(atPath: directory) }
        return try CoreSession(
            config: CoreConfig(
                apiUrl: "https://never-contact.example.invalid", appUrl: "https://app.example.invalid",
                cacheContainer: container, cacheDirectoryName: name),
            credentials: InMemoryCredentialStore())
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,client-core.viewmodel.capability-contract
    func testSignedOutEventLeavesTheAppSignedOut() async {
        let auth = makeAuth()
        await auth.apply(.signedOut)
        XCTAssertEqual(auth.state, .unauthenticated)
        XCTAssertEqual(auth.sessionValidationState, .unauthenticated)
        XCTAssertNil(auth.currentUser)
        XCTAssertFalse(auth.hasNetworkAuthority)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,auth.session.authoritative-enforcement,client-core.viewmodel.capability-contract
    func testAdmittedEventPublishesTheCoreProfileAndGrantsNetworkAuthority() async throws {
        let auth = makeAuth()
        await auth.apply(.admitted(username: "Fixture", expiresAt: nil))
        XCTAssertEqual(auth.state, .authenticated)
        XCTAssertEqual(auth.sessionValidationState, .onlineAuthenticated)
        let user = try XCTUnwrap(auth.currentUser)
        XCTAssertEqual(user.id, "fixture-account")
        XCTAssertEqual(user.email, "user@example.org")
        XCTAssertTrue(auth.hasNetworkAuthority)
        XCTAssertEqual(auth.networkAuthority?.accountID, "fixture-account")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
    func testExpiredEventClearsTheAdmittedAccount() async {
        let auth = makeAuth()
        await auth.apply(.admitted(username: "Fixture", expiresAt: nil))
        XCTAssertEqual(auth.state, .authenticated)
        await auth.apply(.expired)
        XCTAssertEqual(auth.state, .unauthenticated)
        XCTAssertEqual(auth.sessionValidationState, .unauthenticated)
        XCTAssertNil(auth.currentUser)
        XCTAssertFalse(auth.hasNetworkAuthority)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,auth.session.risk-reauth,client-core.viewmodel.capability-contract
    func testVerificationRequiredEventAsksForTheDeviceCodeWithoutNetworkAuthority() async {
        let auth = makeAuth()
        await auth.apply(.verificationRequired(
            .device(method: .twoFactor, reason: "new_device", passwordFallbackAvailable: false)))
        XCTAssertEqual(auth.state, .needsDeviceVerification(type: "2fa"))
        XCTAssertEqual(auth.sessionValidationState, .requiresReauthentication(reason: "device_verification_required"))
        XCTAssertFalse(auth.hasNetworkAuthority)

        // A passkey verification asks for the passkey ceremony, still without authority.
        await auth.apply(.verificationRequired(
            .device(method: .passkey, reason: "new_device", passwordFallbackAvailable: false)))
        XCTAssertEqual(auth.state, .needsDeviceVerification(type: "passkey"))
        XCTAssertFalse(auth.hasNetworkAuthority)

        // A re-auth requirement is answered by signing in again, not by a code.
        await auth.apply(.verificationRequired(.reAuth(reason: "session_revoked")))
        XCTAssertEqual(auth.state, .unauthenticated)
        XCTAssertNil(auth.currentUser)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,client-core.credentials.snapshot-boundary
    func testLogoutSignsOutInTheCoreAndClearsTheAccount() async throws {
        let core = try makeCore()
        let auth = makeAuth(core: core)
        await auth.apply(.admitted(username: "Fixture", expiresAt: nil))
        XCTAssertEqual(auth.state, .authenticated)

        await auth.logout()
        // The core reports the sign-out as an event on the main queue.
        for _ in 0..<500 where core.state != .signedOut {
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTAssertEqual(core.state, .signedOut)
        XCTAssertEqual(auth.state, .unauthenticated)
        XCTAssertEqual(auth.sessionValidationState, .unauthenticated)
        XCTAssertNil(auth.currentUser)
        XCTAssertFalse(auth.hasNetworkAuthority)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence,client-core.viewmodel.capability-contract
    func testAFailedCoreLoginIsATypedErrorAndStaysSignedOut() async throws {
        let core = try makeCore()
        let auth = AuthManager(core: core, profileCacheWriter: { _ in }, sessionScopeActivator: { _ in })
        await auth.checkSession()
        XCTAssertEqual(auth.state, .unauthenticated)
        do {
            try await auth.loginWithPassword(email: "user@example.org", password: "synthetic-password",
                userEmailSalt: "c3ludGhldGljLXNhbHQ=")
            XCTFail("a login against an unreachable host succeeded")
        } catch let error as CoreError {
            // The host never resolves: the core reports it, typed.
            XCTAssertNotEqual(error, .Cancelled)
        } catch let error as AuthError {
            XCTAssertEqual(error, .invalidCredentials)
        }
        XCTAssertEqual(auth.state, .unauthenticated)
        XCTAssertNil(auth.currentUser)
        XCTAssertFalse(auth.hasNetworkAuthority)
        XCTAssertEqual(core.state, .signedOut)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,client-core.viewmodel.capability-contract
    func testRestoredEventUnlocksTheCoresCachedProfileWithoutNetworkAuthority() async throws {
        let auth = makeAuth(fresh: false)
        await auth.apply(.restored(displayName: nil))
        XCTAssertEqual(auth.state, .authenticated)
        XCTAssertEqual(auth.sessionValidationState, .offlineAuthenticated)
        XCTAssertEqual(try XCTUnwrap(auth.currentUser).id, "fixture-account")
        XCTAssertFalse(auth.hasNetworkAuthority)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.authoritative-enforcement,client-core.viewmodel.capability-contract
    func testACachedProfileOnAdmissionIsNotTreatedAsServerConfirmed() async {
        let auth = makeAuth(fresh: false)
        await auth.apply(.admitted(username: "Fixture", expiresAt: nil))
        XCTAssertEqual(auth.state, .authenticated)
        XCTAssertEqual(auth.sessionValidationState, .offlineAuthenticated)
        XCTAssertFalse(auth.hasNetworkAuthority)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence,client-core.viewmodel.capability-contract
    func testFailedBackupCodeAndRecoveryKeyLoginsAreTypedAndStaySignedOut() async throws {
        let core = try makeCore()
        let auth = AuthManager(core: core, profileCacheWriter: { _ in }, sessionScopeActivator: { _ in })
        await auth.checkSession()
        do {
            try await auth.loginWithBackupCode(email: "user@example.org", password: "synthetic-password",
                backupCode: "SYNTHETIC-CODE")
            XCTFail("a backup-code login against an unreachable host succeeded")
        } catch let error as CoreError {
            XCTAssertNotEqual(error, .Cancelled)
        } catch let error as AuthError {
            XCTAssertEqual(error, .invalidTwoFactorCode)
        }
        do {
            try await auth.loginWithRecoveryKey(email: "user@example.org", recoveryKey: "synthetic-recovery-key")
            XCTFail("a recovery-key login against an unreachable host succeeded")
        } catch let error as CoreError {
            XCTAssertNotEqual(error, .Cancelled)
        } catch let error as AuthError {
            XCTAssertEqual(error, .invalidCredentials)
        }
        XCTAssertEqual(auth.state, .unauthenticated)
        XCTAssertNil(auth.currentUser)
        XCTAssertEqual(core.state, .signedOut)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence,client-core.viewmodel.capability-contract
    func testAPasskeyFinishWithoutABegunLoginIsRefusedByTheCore() async throws {
        let core = try makeCore()
        let auth = AuthManager(core: core, profileCacheWriter: { _ in }, sessionScopeActivator: { _ in })
        await auth.checkSession()
        let assertion = PasskeyAssertionResult(credentialId: "Zml4dHVyZQ", clientDataJSON: "e30=",
            authenticatorData: "AA==", signature: "AA==", userHandle: nil, prfOutput: Data(repeating: 7, count: 32))
        do {
            try await auth.finishPasskeyLogin(assertionJSON: try assertion.coreAssertionJSON(),
                prfOutput: try XCTUnwrap(assertion.prfOutput), stayLoggedIn: false)
            XCTFail("a passkey finish without a begun login succeeded")
        } catch let error as CoreError {
            guard case .Invalid = error else { return XCTFail("expected CoreError.Invalid, got \(error)") }
        }
        do {
            _ = try await auth.beginPasskeyDeviceVerification()
            XCTFail("a passkey device verification began while signed out")
        } catch CoreError.Authentication {
            // Signed out: the core holds no session to verify.
        } catch CoreError.Invalid {
            // No passkey verification is pending.
        }
        await auth.cancelPasskeyLogin()
        XCTAssertEqual(auth.state, .unauthenticated)
        XCTAssertEqual(core.state, .signedOut)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testTheCoresPasskeyReasonsMapToTheAppsPasskeyErrors() throws {
        func mapped(_ error: CoreError) -> PasskeyError? { AuthManager.passkeyError(error) as? PasskeyError }
        guard case .missingPRF = try XCTUnwrap(mapped(.Invalid(message: CorePasskeyReason.prfUnavailable))) else {
            return XCTFail("a missing PRF output is not the PRF error")
        }
        for reason in [CorePasskeyReason.wrongAccount, CorePasskeyReason.otherRequest] {
            guard case .assertionFailed = try XCTUnwrap(mapped(.Invalid(message: reason))) else {
                return XCTFail("a refused passkey answer is not the verification error")
            }
        }
        guard case .assertionFailed = try XCTUnwrap(mapped(.Authentication)) else {
            return XCTFail("a refused passkey is not the verification error")
        }
        XCTAssertEqual(AuthManager.passkeyError(.Offline) as? CoreError, .Offline)
        XCTAssertEqual(AuthManager.passkeyError(.Invalid(message: "other")) as? CoreError, .Invalid(message: "other"))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testThePasskeyAssertionJSONMatchesTheCoreWireShape() throws {
        let assertion = PasskeyAssertionResult(credentialId: "Y3JlZA", clientDataJSON: "Y2xpZW50",
            authenticatorData: "YXV0aA==", signature: "c2ln", userHandle: nil, prfOutput: nil)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: try assertion.coreAssertionJSON()) as? [String: String])
        XCTAssertEqual(object, ["credential_id": "Y3JlZA", "client_data_json": "Y2xpZW50",
                                "authenticator_data": "YXV0aA==", "signature": "c2ln"])
        let withHandle = PasskeyAssertionResult(credentialId: "Y3JlZA", clientDataJSON: "Y2xpZW50",
            authenticatorData: "YXV0aA==", signature: "c2ln", userHandle: "dXNlcg==", prfOutput: nil)
        let handled = try XCTUnwrap(JSONSerialization.jsonObject(with: try withHandle.coreAssertionJSON()) as? [String: String])
        XCTAssertEqual(handled["user_handle"], "dXNlcg==")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,client-core.viewmodel.capability-contract
    func testTheCoreProfilePayloadDecodesFromSnakeCase() async throws {
        let user = try await AuthManager.decodeProfile(Self.profileJSON)
        XCTAssertEqual(user.id, "fixture-account")
        XCTAssertEqual(user.username, "Fixture")
        XCTAssertEqual(user.email, "user@example.org")
        XCTAssertEqual(user.lastOpened, "fixture-chat")
        XCTAssertEqual(user.userEmailSalt, "c3ludGhldGljLXNhbHQ=")
        XCTAssertEqual(user.credentialVersion, 2)
        XCTAssertEqual(user.pushNotificationEnabled, true)

        do {
            _ = try await AuthManager.decodeProfile(Data(#"{"username":"Fixture"}"#.utf8))
            XCTFail("a payload without an account id decoded")
        } catch is DecodingError {}
    }
}
