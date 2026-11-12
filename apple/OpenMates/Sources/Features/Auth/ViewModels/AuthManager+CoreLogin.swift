// Specification: specifications/features/auth/specification.yml
// Assertions: auth.session.lifecycle, auth.login.method-convergence
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.apple.strangler-order
//
// Sign-ins that end in the Rust core besides the password and pair login in
// `AuthManager.swift` (plan apple-client-core-migration A4 lane 1): backup
// code, recovery key, passkey login and passkey device verification. The core
// derives, verifies, unwraps, stores and admits; Swift only runs the system
// passkey ceremony (`PasskeyLoginCoordinator`) and maps the core's typed
// errors to the app's existing messages. The one Swift-finished sign-in left
// is the passkey signup, which the core adopts (`CoreSession.adoptCeremony`)
// because the core has no signup yet.

import CryptoKit
import Foundation

/// The core's fixed `CoreError.Invalid` reasons of a passkey finish
/// (`PASSKEY_*` in `packages/openmates-rust/src/client/auth_passkey.rs`).
/// They are matched, never shown: the app shows its own strings.
enum CorePasskeyReason {
    static let prfUnavailable =
        "This passkey does not support OpenMates encryption. Please use another login method."
    static let wrongAccount =
        "This passkey belongs to a different OpenMates account. Choose the passkey for this account and try again."
    static let otherRequest = "This passkey answer belongs to another passkey request. Start again."
}

extension AuthManager {
    // MARK: - Backup code and recovery key

    /// Password plus backup code in the core. A refused code or password is
    /// `AuthError.invalidTwoFactorCode`; device verification is no error.
    func loginWithBackupCode(email: String, password: String, backupCode: String,
                             stayLoggedIn: Bool = false) async throws {
        try await runCoreSignIn { (core: CoreSession) async throws -> LoginRecord in
            do {
                return try await core.loginBackupCode(email: email, password: password,
                    backupCode: backupCode, stayLoggedIn: stayLoggedIn)
            } catch CoreError.Authentication {
                throw AuthError.invalidTwoFactorCode
            }
        }
    }

    /// Recovery-key sign-in in the core. A refused key is `AuthError.invalidCredentials`.
    func loginWithRecoveryKey(email: String, recoveryKey: String, stayLoggedIn: Bool = false) async throws {
        try await runCoreSignIn { (core: CoreSession) async throws -> LoginRecord in
            do {
                return try await core.loginRecoveryKey(email: email, recoveryKey: recoveryKey,
                    stayLoggedIn: stayLoggedIn)
            } catch CoreError.Authentication {
                throw AuthError.invalidCredentials
            }
        }
    }

    // MARK: - Passkey login

    /// Begin a passkey sign-in (`email == nil`: any passkey of this device).
    func beginPasskeyLogin(email: String?) async throws -> PasskeyChallengeRecord {
        guard let core else { throw CoreSessionAdoptionError.coreUnavailable }
        bind(core)
        return try await core.beginPasskeyLogin(email: email)
    }

    /// Finish the begun passkey sign-in. The core's fixed passkey reasons and
    /// a refused passkey become `PasskeyError`; other core errors stay typed.
    func finishPasskeyLogin(assertionJSON: Data, prfOutput: Data, stayLoggedIn: Bool) async throws {
        try await runCoreSignIn { (core: CoreSession) async throws -> LoginRecord in
            do {
                return try await core.finishPasskeyLogin(assertionJson: assertionJSON, prfOutput: prfOutput,
                    stayLoggedIn: stayLoggedIn)
            } catch let error as CoreError {
                throw Self.passkeyError(error)
            }
        }
    }

    /// Forget a begun passkey login or device verification in the core.
    func cancelPasskeyLogin() async {
        await core?.cancelPasskeyLogin()
    }

    // MARK: - Passkey device verification

    /// Begin answering the core's pending passkey device verification.
    func beginPasskeyDeviceVerification() async throws -> PasskeyChallengeRecord {
        guard let core else { throw CoreSessionAdoptionError.coreUnavailable }
        return try await core.beginPasskeyDeviceVerification()
    }

    /// Answer the pending passkey device verification. A refused passkey is
    /// `PasskeyError.assertionFailed` and stays pending.
    func finishPasskeyDeviceVerification(assertionJSON: Data) async throws {
        guard let core else { throw CoreSessionAdoptionError.coreUnavailable }
        do {
            try await core.finishPasskeyDeviceVerification(assertionJson: assertionJSON)
        } catch let error as CoreError {
            throw Self.passkeyError(error)
        }
        await drainCoreEvents()
    }

    /// The app's passkey error for a core error of a passkey finish; other
    /// errors are returned unchanged.
    nonisolated static func passkeyError(_ error: CoreError) -> Error {
        switch error {
        case .Invalid(let message) where message == CorePasskeyReason.prfUnavailable:
            return PasskeyError.missingPRF
        case .Invalid(let message)
            where message == CorePasskeyReason.wrongAccount || message == CorePasskeyReason.otherRequest:
            return PasskeyError.assertionFailed
        case .Authentication:
            return PasskeyError.assertionFailed
        default:
            return error
        }
    }

    // MARK: - Shared steps

    /// Run one core sign-in and follow its events. A device-verification
    /// requirement is no error: `state` shows it.
    private func runCoreSignIn(_ login: @MainActor (CoreSession) async throws -> LoginRecord) async throws {
        guard let core else { throw CoreSessionAdoptionError.coreUnavailable }
        bind(core)
        let record: LoginRecord
        do {
            record = try await login(core)
        } catch CoreError.VerificationRequired {
            await drainCoreEvents()
            return
        }
        await drainCoreEvents()
        logPasswordMigration(record.passwordMigration)
        if let user = currentUser { confirmAuthenticated(for: user.id) }
    }

    /// The core's legacy password migration outcome, as a fixed class.
    func logPasswordMigration(_ migration: PasswordMigrationRecord) {
        let outcome: String
        switch migration {
        case .notNeeded: return
        case .completed: outcome = "completed"
        case .legacyRetained: outcome = "legacy_retained"
        case .pendingConfirmation: outcome = "pending_confirmation"
        case .deferredLegacyCredentials: outcome = "deferred_legacy_credentials"
        case .deferredRecentVerification: outcome = "deferred_recent_verification"
        case .deferredFreshLogin: outcome = "deferred_fresh_login"
        case .unsupported: outcome = "unsupported"
        case .failed: outcome = "failed"
        }
        NativeDiagnostics.info("phase=auth.password_migration outcome=\(outcome)", category: "auth")
    }

    // MARK: - Passkey signup (adopted)

    // Signup publishes only after a fresh assertion unwraps the same newly
    // generated master key and /login returns the matching credential envelope.
    func completeNativePasskeySignup(response: LoginResponse, masterKey: SymmetricKey,
        proof: NativeSignupLoginProof, contextIsCurrent: @escaping @MainActor () -> Bool) async throws {
        try validateSignupContext(proof)
        guard contextIsCurrent(), proof.validates(response), proof.validatesMasterKey(masterKey) else {
            throw NativeSignupError.sessionProofMismatch
        }
        guard response.success else { throw AuthError.invalidCredentials }
        guard let core else { throw CoreSessionAdoptionError.coreUnavailable }
        bind(core)
        let result = CoreCeremonyResult(response: response, masterKey: masterKey,
            hashedEmail: proof.request.hashedEmail, userEmailSalt: proof.request.userEmailSalt,
            emailEncryptionKey: nil, sessionID: CoreCeremonySession.sessionID)
        do {
            try await core.adoptCeremony(result, apiBaseURL: ServerProfile.current().apiBaseURL)
        } catch CoreError.VerificationRequired {
            await drainCoreEvents()
            return
        }
        await drainCoreEvents()
        if let user = currentUser { confirmAuthenticated(for: user.id) }
    }
}
