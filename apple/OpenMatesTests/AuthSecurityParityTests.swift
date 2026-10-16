// Unit coverage for native auth/security state parity.
// These tests use in-memory state only and never touch credentials, passkeys,
// recovery keys, backup codes, Keychain records, network sessions, or screenshots.

import XCTest
@testable import OpenMates

@MainActor
final class AuthSecurityParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testAuthMethodDiscoveryUsesCoreAuthRoute() {
        XCTAssertEqual(AccountSecurityService.authMethodsPath, "/v1/auth/methods")
        XCTAssertFalse(AccountSecurityService.authMethodsPath.contains("/payments/"))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.authoritative-enforcement
    func testRejectedPasswordCommitDiscardsPendingSecretsAndExpiredProof() throws {
        for status in [401, 428] {
            let failure = AccountSecurityError.passwordUpdateFailure(
                APIError.httpError(status: status, message: "Recent verification required"))
            XCTAssertEqual(failure.localizedDescription, AppStrings.localized("settings.security.verify_identity_description"))
            var current = "synthetic-current"
            var new = "synthetic-new"
            var confirm = new
            var code = "123456"
            var challenge: SensitiveEmailChallenge? = try JSONDecoder().decode(
                SensitiveEmailChallenge.self,
                from: Data(#"{"success":true,"challengeId":"synthetic","expiresIn":60}"#.utf8))
            PasswordSettingsFailureRecovery.resetIfVerificationRequired(
                failure, currentPassword: &current, newPassword: &new,
                confirmPassword: &confirm, factorCode: &code, emailChallenge: &challenge)
            XCTAssertEqual([current, new, confirm, code], ["", "", "", ""])
            XCTAssertNil(challenge, "Expired email verification must restart before another commit")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testUnrelatedPasswordCommitFailurePreservesEditingAndChallenge() throws {
        for status in [403, 409, 500, 503] {
            let failure = AccountSecurityError.passwordUpdateFailure(
                APIError.httpError(status: status, message: "Synthetic rejection"))
            var current = "synthetic-current"
            var new = "synthetic-new"
            var confirm = new
            var code = "123456"
            var challenge: SensitiveEmailChallenge? = try JSONDecoder().decode(
                SensitiveEmailChallenge.self,
                from: Data(#"{"success":true,"challengeId":"synthetic","expiresIn":60}"#.utf8))
            PasswordSettingsFailureRecovery.resetIfVerificationRequired(
                failure, currentPassword: &current, newPassword: &new,
                confirmPassword: &confirm, factorCode: &code, emailChallenge: &challenge)
            XCTAssertEqual([current, new, confirm, code], ["synthetic-current", "synthetic-new", "synthetic-new", "123456"])
            XCTAssertEqual(challenge?.challengeId, "synthetic")
            guard case APIError.httpError(let retainedStatus, _) = failure else {
                return XCTFail("Unrelated failure type must be retained")
            }
            XCTAssertEqual(retainedStatus, status)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.secrets.lifecycle
    func testAuthFlowResetClearsSensitiveLookupState() {
        let state = AuthFlowState()
        state.authMode = .login
        state.currentStep = .passwordLogin
        state.email = "person@example.com"
        state.tfaEnabled = true
        state.userEmailSalt = "salt"

        state.reset()

        XCTAssertEqual(state.authMode, .signup)
        XCTAssertEqual(state.currentStep, .emailLookup)
        XCTAssertEqual(state.email, "")
        XCTAssertEqual(state.availableMethods, [])
        XCTAssertEqual(state.tfaEnabled, false)
        XCTAssertNil(state.userEmailSalt)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.secrets.lifecycle,auth.session.isolation
    func testResetForAnotherAccountPreservesModeButClearsAccountSpecificState() {
        let state = AuthFlowState()
        state.authMode = .login
        state.currentStep = .passwordLogin
        state.email = "person@example.com"
        state.availableMethods = [.password]
        state.userEmailSalt = "salt"

        state.resetForAnotherAccount()

        XCTAssertEqual(state.authMode, .login)
        XCTAssertEqual(state.currentStep, .emailLookup)
        XCTAssertEqual(state.email, "")
        XCTAssertEqual(state.availableMethods, [])
        XCTAssertNil(state.userEmailSalt)
    }
}
