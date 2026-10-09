// Central auth state manager — mirrors the web app's authStore.ts.
// Handles login flows (password, passkey, recovery key, backup code),
// session persistence, and device verification state.
// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.registration.lifecycle
// Specification: specifications/features/auth/specification.yml
// Assertions: auth.session.lifecycle, auth.session.authoritative-enforcement, auth.session.isolation, auth.lookup.anti-enumeration, auth.login.method-convergence

import Foundation
import SwiftUI
import AuthenticationServices
import CryptoKit

private enum PasswordV2MigrationPendingStore {
    private static let key = "openmates.apple.password_v2.pending_user"

    static func mark(_ userID: String) { UserDefaults.standard.set(userID, forKey: key) }
    static func contains(_ userID: String) -> Bool { UserDefaults.standard.string(forKey: key) == userID }
    static func clear(_ userID: String) {
        if contains(userID) { UserDefaults.standard.removeObject(forKey: key) }
    }
}

/// Captured before network execution; a late rejection cannot challenge a newer
/// account, server, logical native session, or credential validation generation.
struct AuthSessionRecoveryContext: Equatable, Sendable {
    let accountID: String
    let profile: ServerProfile
    let sessionID: String
    let generation: UUID
}

@MainActor
final class AuthManager: ObservableObject {
    @Published var state: AuthState = .initializing {
        didSet { if state != .authenticated { networkAuthority = nil } }
    }
    @Published var currentUser: UserProfile? {
        didSet { if currentUser?.id != oldValue?.id { networkAuthority = nil } }
    }
    @Published var error: String?
    @Published private(set) var webSocketToken: String?
    @Published private(set) var sessionValidationState: SessionValidationState = .initializing {
        didSet {
            switch sessionValidationState {
            case .onlineAuthenticated:
                if let accountID = currentUser?.id,
                   networkAuthority?.accountID != accountID || networkAuthority?.profile != ServerProfile.current() ||
                    networkAuthority?.sessionID != Self.nativeSessionId {
                    networkAuthority = AuthSessionRecoveryContext(accountID: accountID, profile: ServerProfile.current(),
                        sessionID: Self.nativeSessionId, generation: validationGeneration)
                }
            case .validating:
                break // A routine cookie renewal retains its existing authority.
            default:
                networkAuthority = nil
            }
        }
    }
    /// Cached identity unlocks local history; only this grant permits protected IO.
    @Published private(set) var networkAuthority: AuthSessionRecoveryContext?

    var hasNetworkAuthority: Bool {
        guard state == .authenticated, let authority = networkAuthority else { return false }
        return currentUser?.id == authority.accountID && ServerProfile.current() == authority.profile &&
            Self.nativeSessionId == authority.sessionID
    }

    static func hasNetworkAuthority(for profile: ServerProfile, sessionID: String? = nil) -> Bool {
        guard let manager = _shared, manager.hasNetworkAuthority,
              manager.networkAuthority?.profile == profile else { return false }
        return sessionID == nil || manager.networkAuthority?.sessionID == sessionID
    }

    static func captureNetworkAuthority() -> AuthSessionRecoveryContext? {
        guard let manager = _shared, manager.hasNetworkAuthority else { return nil }
        return manager.networkAuthority
    }

    static func requireNetworkAuthority(profile: ServerProfile, sessionID: String? = nil) throws {
        guard hasNetworkAuthority(for: profile, sessionID: sessionID) else { throw CancellationError() }
    }

    /// Public/auth bootstrap remains available without an unlocked account.
    /// Once a cached account exists it must not lend cookies to protected work.
    static func requireProtectedRequestAuthority(profile: ServerProfile) throws {
        guard let manager = _shared else { return }
        guard manager.currentUser != nil || manager.state != .unauthenticated else { return }
        try requireNetworkAuthority(profile: profile)
    }

    static func rejectVerificationRequired(_ expected: AuthSessionRecoveryContext) {
        guard let manager = _shared,
              manager.sessionRecoveryContext == expected || manager.validationFlight?.context == expected,
              manager.currentUser?.id == expected.accountID,
              ServerProfile.current() == expected.profile, Self.nativeSessionId == expected.sessionID else { return }
        manager.validationGeneration = UUID()
        manager.validationFlight?.task.cancel()
        manager.validationFlight = nil
        manager.webSocketToken = nil
        manager.sessionValidationState = .requiresReauthentication(reason: "session_verification_required")
        NativeDiagnostics.warning("Native protected request requires session verification", category: "auth")
    }

    private let api: APIClient
    private let crypto = CryptoManager.shared
    typealias SessionValidator = @MainActor (ServerProfile, SessionRequest) async throws -> SessionResponse
    private let sessionValidator: SessionValidator?
    private let profileCacheWriter: ((UserProfile) -> Void)?
    private var validationGeneration = UUID()
    private var validationFlight: (id: UUID, context: AuthSessionRecoveryContext?, profile: ServerProfile, sessionID: String, task: Task<Void, Never>)?
    private let sessionMasterKeyAvailable: ((String) async -> Bool)?
    private let sessionScopeActivator: ((UserProfile) throws -> Void)?
    private(set) var lastOpenedSelectionRevision = 0

    /// Static accessor for the current user ID (used by ChatViewModel for key loading).
    /// Safe to call from any @MainActor context.
    private static weak var _shared: AuthManager?

    static func currentUserId() async -> String? {
        await MainActor.run { _shared?.currentUser?.id }
    }

    /// Bind a cold-launch notification action before asynchronous session restore.
    static var notificationSession: AuthManager { _shared ?? AuthManager() }

    static var notificationAccountId: String? {
        _shared?.currentUser?.id ?? cachedUser()?.id
    }

    static func isRecoveryEligibleDevice() async -> Bool {
        await MainActor.run {
            _shared?.state == .authenticated && _shared?.sessionValidationState == .onlineAuthenticated
        }
    }

    enum AuthState: Equatable {
        case initializing
        case unauthenticated
        case needsDeviceVerification(type: String)
        case authenticated

        static func == (lhs: AuthState, rhs: AuthState) -> Bool {
            switch (lhs, rhs) {
            case (.initializing, .initializing),
                 (.unauthenticated, .unauthenticated),
                 (.authenticated, .authenticated):
                return true
            case (.needsDeviceVerification(let a), .needsDeviceVerification(let b)):
                return a == b
            default:
                return false
            }
        }
    }

    enum SessionValidationState: Equatable {
        case initializing
        case offlineAuthenticated
        case validating
        case onlineAuthenticated
        case requiresReauthentication(reason: String)
        case unauthenticated
    }

    /// Entered password retained only until the versioned master-key wrapper
    /// has been opened, then cleared from this view model.
    private var pendingPassword: String?
    private var pendingEmail: String?

    init(api: APIClient = .shared, sessionValidator: SessionValidator? = nil, profileCacheWriter: ((UserProfile) -> Void)? = nil,
         sessionMasterKeyAvailable: ((String) async -> Bool)? = nil,
         sessionScopeActivator: ((UserProfile) throws -> Void)? = nil) {
        self.api = api
        self.sessionValidator = sessionValidator
        self.profileCacheWriter = profileCacheWriter
        self.sessionMasterKeyAvailable = sessionMasterKeyAvailable
        self.sessionScopeActivator = sessionScopeActivator
        Self._shared = self
    }

    /// The resume card follows the viewed chat; it does not change chat recency.
    /// Called synchronously for local navigation and the current socket's
    /// last_opened_updated event. Account ownership is explicit for queued callers.
    func updateLastOpened(_ chatId: String, accountId: String) {
        guard state == .authenticated, var user = currentUser, user.id == accountId,
              !chatId.isEmpty, !chatId.hasPrefix("/"),
              ChatStore.isServerSyncChatId(chatId), user.lastOpened != chatId else { return }
        lastOpenedSelectionRevision += 1
        user.lastOpened = chatId
        currentUser = user
        cacheAuthenticatedUser(user)
    }

    func publishPasswordWrapper(for accountId: String, encryptedKey: String,
                                keyIv: String, salt: String, version: Int) {
        guard var user = currentUser, user.id == accountId, version == 2 else { return }
        user.encryptedKey = encryptedKey
        user.keyIv = keyIv
        user.salt = salt
        user.credentialVersion = version
        currentUser = user
        cacheAuthenticatedUser(user)
        PasswordV2MigrationPendingStore.clear(accountId)
    }

    func profilePreservingNewerSelection(_ received: UserProfile, since revision: Int) -> UserProfile {
        var result = received
        if lastOpenedSelectionRevision != revision, currentUser?.id == received.id {
            result.lastOpened = currentUser?.lastOpened
        }
        return result
    }

    /// Only the acknowledged /session preference is copied. Other profile fields
    /// may have changed locally while registration's authoritative read awaited.
    func applyAuthoritativePushNotificationPreference(_ received: UserProfile,
                                                      accountID: String, profile: ServerProfile, scope: UUID) {
        guard state == .authenticated, received.id == accountID,
              currentUser?.id == accountID, ServerProfile.current() == profile,
              OfflineStore.shared.scopeGeneration == scope,
              let enabled = received.pushNotificationEnabled, let currentUser,
              currentUser.pushNotificationEnabled != enabled,
              let data = try? JSONEncoder().encode(currentUser),
              var fields = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return }
        fields["pushNotificationEnabled"] = enabled
        guard let updated = try? JSONSerialization.data(withJSONObject: fields),
              let user = try? JSONDecoder().decode(UserProfile.self, from: updated) else { return }
        self.currentUser = user
        cacheAuthenticatedUser(user)
    }

    private var isCheckingSession = false

    // MARK: - Session check (app launch)

    func checkSession() async {
        if isCheckingSession {
            while isCheckingSession, !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(50))
            }
            return
        }
        isCheckingSession = true
        defer { isCheckingSession = false }
        Self._shared = self
        #if DEBUG
        let isWindowDraftFixture = ProcessInfo.processInfo.arguments.contains("--ui-test-window-drafts")
        if isWindowDraftFixture, state == .authenticated,
           currentUser?.id == "ui-test-window-drafts-user" { return }
        if ProcessInfo.processInfo.arguments.contains("--ui-test-authenticated-chat-navigation") || isWindowDraftFixture {
            currentUser = UserProfile(
                id: isWindowDraftFixture ? "ui-test-window-drafts-user" : "ui-test-chat-navigation-user",
                username: isWindowDraftFixture ? "ui-test-window-drafts" : "ui-test-chat-navigation",
                email: nil,
                credits: 0,
                language: "en",
                darkmode: nil,
                timezone: "UTC",
                lastOpened: "ui-test-regular-chat",
                profileImageUrl: nil,
                isAdmin: false,
                encryptedKey: nil,
                keyIv: nil,
                salt: nil,
                userEmailSalt: nil,
                encryptedSettings: nil,
                autoDeleteChatsAfterDays: nil,
                pushNotificationEnabled: nil,
                emailNotificationsEnabled: nil,
                emailNotificationPreferences: nil,
                backupReminderIntervalDays: nil,
                defaultAiModelSimple: nil,
                defaultAiModelComplex: nil,
                followUpSuggestionsEnabled: nil,
                quickTipsEnabled: nil
            )
            if isWindowDraftFixture, let currentUser {
                do {
                    try await crypto.saveMasterKey(SymmetricKey(data: Data(repeating: 0x42, count: 32)), for: currentUser.id)
                    try activateOfflineScope(for: currentUser)
                    OfflineStore.shared.clearAll()
                } catch {
                    NativeDiagnostics.error("Window draft UI fixture setup failed: \(type(of: error))", category: "apple_composer")
                    state = .unauthenticated
                    return
                }
            }
            webSocketToken = nil
            sessionValidationState = .offlineAuthenticated
            state = .authenticated
            return
        }
        #endif
        if ProcessInfo.processInfo.arguments.contains("--ui-test-disable-auth-cache") {
            sessionValidationState = .unauthenticated
            state = .unauthenticated
            return
        }
        if PairPendingAckStore.userID() != nil {
            await forceLocalLogout(reason: "pair_acknowledgment_incomplete")
            return
        }
        if let cached = Self.cachedUser(), PairSessionDeadlineStore.isExpired(userID: cached.id) {
            await forceLocalLogout(reason: "pair_session_expired")
            return
        }
        let restoredFromDisk = await restoreCachedSessionForStartup()
        guard !restoredFromDisk else { return }
        Task { @MainActor in
            await validateSessionAgainstServer(keepOfflineSessionOnFailure: false)
        }
    }

    func validateSessionAfterOfflineBootstrap() async {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-test-window-drafts") { return }
        #endif
        if case .requiresReauthentication = sessionValidationState { return }
        await validateSessionAgainstServer(keepOfflineSessionOnFailure: currentUser != nil)
    }

    var sessionRecoveryContext: AuthSessionRecoveryContext? {
        guard state == .authenticated, let accountID = currentUser?.id else { return nil }
        return AuthSessionRecoveryContext(accountID: accountID, profile: ServerProfile.current(),
            sessionID: Self.nativeSessionId, generation: validationGeneration)
    }

    static func captureSessionRecoveryContext() -> AuthSessionRecoveryContext? {
        _shared?.sessionRecoveryContext
    }

    static func recoverRejectedRequest(_ expected: AuthSessionRecoveryContext) async {
        await _shared?.recoverSession(expected: expected)
    }

    /// A cookie successor is only a renewal signal for the captured online
    /// identity, never evidence for changing accounts or reviving rejected auth.
    /// Duplicate/stale responses join the existing generation fence instead of
    /// starting a second validation or replaying the original HTTP operation.
    static func acceptRefreshSuccessor(_ expected: AuthSessionRecoveryContext) async {
        guard let manager = _shared, manager.sessionValidationState == .onlineAuthenticated,
              manager.sessionRecoveryContext == expected else { return }
        await manager.recoverSession(expected: expected, revokeAuthority: false)
    }

    /// All callers await one validation for the same identity. Stale HTTP 401s
    /// join their pending validation, but cannot start another after it completes.
    func recoverSession(expected: AuthSessionRecoveryContext, revokeAuthority: Bool = true) async {
        #if DEBUG
        // These cached identities have no server session. Foreground and API
        // rejection recovery must preserve their isolated offline fixtures.
        // The explicit rejection fixture still exercises the production route.
        let arguments = ProcessInfo.processInfo.arguments
        let isSyntheticOfflineFixture = arguments.contains("--ui-test-authenticated-chat-navigation")
            || arguments.contains("--ui-test-window-drafts")
        if isSyntheticOfflineFixture, !arguments.contains("--ui-test-rejected-native-session") { return }
        #endif
        guard sessionRecoveryContext == expected || (validationFlight?.id == validationGeneration && validationFlight?.context == expected) else { return }
        guard currentUser?.id == expected.accountID, ServerProfile.current() == expected.profile,
              Self.nativeSessionId == expected.sessionID, state == .authenticated else { return }
        if case .requiresReauthentication = sessionValidationState { return }
        if revokeAuthority { networkAuthority = nil }
        await validateSessionAgainstServer(keepOfflineSessionOnFailure: true)
    }

    private func validateSessionAgainstServer(keepOfflineSessionOnFailure: Bool) async {
        let context = sessionRecoveryContext
        if let flight = validationFlight, flight.id == validationGeneration,
           flight.context?.accountID == context?.accountID,
           flight.profile == ServerProfile.current(),
           flight.sessionID == Self.nativeSessionId {
            await flight.task.value
            return
        }
        validationFlight?.task.cancel()
        let id = UUID()
        let profile = ServerProfile.current()
        let sessionID = Self.nativeSessionId
        let accountID = currentUser?.id
        let selectionRevision = lastOpenedSelectionRevision
        validationGeneration = id
        let task = Task { @MainActor [weak self] in
            guard let self else { return }
            await self.performSessionValidation(keepOfflineSessionOnFailure: keepOfflineSessionOnFailure,
                generation: id, profile: profile, sessionId: sessionID, accountId: accountID,
                selectionRevision: selectionRevision)
        }
        validationFlight = (id, context, profile, sessionID, task)
        await task.value
        if validationFlight?.id == id { validationFlight = nil }
    }

    private func performSessionValidation(keepOfflineSessionOnFailure: Bool, generation: UUID,
        profile: ServerProfile, sessionId: String, accountId: String?, selectionRevision: Int) async {
        func ownsValidation() -> Bool {
            !Task.isCancelled && validationGeneration == generation &&
                ServerProfile.current() == profile && Self.nativeSessionId == sessionId &&
                currentUser?.id == accountId
        }
        guard ownsValidation() else { return }
        sessionValidationState = .validating
        let cookieCount = (OpenMatesSharedEnvironment.cookieStorage.cookies(for: profile.apiBaseURL) ?? [])
            .filter { $0.name == "auth_refresh_token" }.count
        NativeDiagnostics.info("Native session validation started cached_account=\(accountId != nil) refresh_cookie_count=\(cookieCount) \(NativeClientIdentity.current.diagnosticSummary)", category: "auth")
        do {
            let request = SessionRequest(sessionId: sessionId, deviceInfo: makeDeviceInfo())
            let response: SessionResponse
            if let sessionValidator {
                response = try await sessionValidator(profile, request)
            } else {
                #if DEBUG
                if ProcessInfo.processInfo.arguments.contains("--ui-test-rejected-native-session") {
                    throw APIError.httpError(status: 401, message: "Synthetic rejected session")
                }
                #endif
                response = try await api.validateNativeSession(serverProfile: profile, body: request,
                    expectedAccountID: accountId, isCurrent: ownsValidation)
            }
            guard ownsValidation() else { return }
            NativeDiagnostics.info("Native session validation response authenticated=\(response.isAuthenticated) verification_required=\(response.needsDeviceVerification == true)", category: "auth")

            // Verification is an authority decision even on a success envelope.
            // Never publish its profile/token or activate account runtime first.
            if response.needsDeviceVerification == true || response.reAuthRequired != nil || response.reAuthReason != nil {
                webSocketToken = nil
                sessionValidationState = .requiresReauthentication(reason:
                    response.reAuthReason ?? response.reAuthRequired ?? "session_verification_required")
                if currentUser == nil {
                    if response.needsDeviceVerification == true {
                        state = .needsDeviceVerification(type: response.deviceVerificationType ?? "2fa")
                    } else {
                        sessionValidationState = .unauthenticated
                        state = .unauthenticated
                    }
                }
                return
            }

            if response.isAuthenticated, let user = response.user {
                guard accountId == nil || user.id == accountId else {
                    webSocketToken = nil
                    sessionValidationState = .requiresReauthentication(reason: "session_account_changed")
                    return
                }
                let hasMasterKey: Bool
                if let sessionMasterKeyAvailable {
                    hasMasterKey = await sessionMasterKeyAvailable(user.id)
                } else {
                    hasMasterKey = (try? await crypto.loadMasterKey(for: user.id)) != nil
                }
                if response.needsDeviceVerification != true, !hasMasterKey {
                    guard ownsValidation() else { return }
                    await forceLocalLogout(reason: "missing_master_key")
                    return
                }
                guard ownsValidation() else { return }
                let user = profilePreservingNewerSelection(user, since: selectionRevision)
                if let sessionScopeActivator { try sessionScopeActivator(user) }
                else { try activateOfflineScope(for: user) }
                currentUser = user
                webSocketToken = response.wsToken
                sessionValidationState = .onlineAuthenticated
                cacheAuthenticatedUser(user)
                if response.needsDeviceVerification == true,
                   let type = response.deviceVerificationType {
                    state = .needsDeviceVerification(type: type)
                } else {
                    state = .authenticated
                }
            } else {
                let reason = response.reAuthReason ?? response.reAuthRequired ?? "session_invalid"
                guard currentUser != nil else {
                    webSocketToken = nil
                    sessionValidationState = .unauthenticated
                    state = .unauthenticated
                    return
                }
                if keepOfflineSessionOnFailure {
                    webSocketToken = nil
                    sessionValidationState = .requiresReauthentication(reason: reason)
                    state = .authenticated
                    print("[Auth] Session validation requires re-auth reason=\(reason); preserving cached encrypted session")
                    return
                }
                await forceLocalLogout(reason: reason)
            }
        } catch {
            guard ownsValidation() else { return }
            let failureClass: String
            if case APIError.httpError(let status, _) = error {
                failureClass = status == 401 || status == 403 ? "credential_rejected" : "server_response"
            } else if error is DecodingError {
                failureClass = "response_decoding"
            } else {
                failureClass = "transport_unavailable"
            }
            NativeDiagnostics.warning("Native session validation failed class=\(failureClass) preserve_cached_account=\(keepOfflineSessionOnFailure)", category: "auth")
            webSocketToken = nil
            if keepOfflineSessionOnFailure {
                // An explicit rejected session is not an offline connection.
                // Keep cached account data, but expose a real sign-in route.
                if case APIError.httpError(let status, _) = error, status == 401 || status == 403 {
                    sessionValidationState = .requiresReauthentication(reason: "session_expired")
                    return
                }
                sessionValidationState = .offlineAuthenticated
                print("[Auth] Session validation unavailable; keeping cached offline session: \(error.localizedDescription)")
            } else {
                sessionValidationState = .unauthenticated
                state = .unauthenticated
            }
        }
    }

    // MARK: - Email lookup

    func lookup(email: String, stayLoggedIn: Bool = false) async throws -> LookupResponse {
        let hashedEmail = await crypto.hashEmail(email)
        return try await api.request(
            .post,
            path: "/v1/auth/lookup",
            body: LookupRequest(hashedEmail: hashedEmail, stayLoggedIn: stayLoggedIn)
        )
    }

    // MARK: - Password login

    func loginWithPassword(
        email: String,
        password: String,
        userEmailSalt: String?,
        tfaCode: String? = nil,
        codeType: String? = nil,
        stayLoggedIn: Bool = false,
        signupProof: NativeSignupLoginProof? = nil
    ) async throws {
        validationGeneration = UUID()
        let signupSessionId = signupProof?.sessionId
        if let signupProof, let signupSessionId {
            try validateSignupContext(signupProof, sessionId: signupSessionId)
        }
        guard let userEmailSalt,
              let saltData = Data(base64Encoded: userEmailSalt) else {
            print("[Auth] Missing user_email_salt from lookup; cannot compute web-compatible lookup_hash")
            throw AuthError.missingAuthData
        }

        let hashedEmail = await crypto.hashEmail(email)
        let emailEncryptionKey = await crypto.deriveEmailEncryptionKey(
            email: email,
            salt: saltData
        ).base64EncodedString()

        // Keep the entered password only until the account's versioned wrapper is opened.
        if let signupProof, let signupSessionId {
            try validateSignupContext(signupProof, sessionId: signupSessionId)
        } else {
            pendingPassword = password
            pendingEmail = email
        }

        var request = LoginRequest(
            hashedEmail: hashedEmail,
            lookupHash: nil,
            loginMethod: "password",
            tfaCode: tfaCode,
            codeType: tfaCode == nil ? nil : (codeType ?? "otp"),
            emailEncryptionKey: emailEncryptionKey,
            stayLoggedIn: stayLoggedIn,
            sessionId: Self.sessionId,
            deviceInfo: makeDeviceInfo()
        )

        NativeDiagnostics.info("phase=passwordLogin.request", category: "auth")
        var derivedV2Keys: PasswordV2Keys?
        func send(_ request: LoginRequest) async throws -> LoginResponse {
            if let signupProof, let signupSessionId {
                try validateSignupContext(signupProof, sessionId: signupSessionId)
                let response: LoginResponse = try await api.request(.post, path: "/v1/auth/login",
                    serverProfile: signupProof.serverProfile, body: request)
                try validateSignupContext(signupProof, sessionId: signupSessionId)
                guard signupProof.validates(response) else { throw NativeSignupError.sessionProofMismatch }
                return response
            }
            return try await api.request(.post, path: "/v1/auth/login", body: request)
        }

        let response: LoginResponse
        do {
            let keys = try PasswordV2Keys(password: password, emailSalt: saltData)
            derivedV2Keys = keys
            let challengeRequest = PasswordV2ChallengeRequest(
                hashedEmail: hashedEmail, sessionId: Self.sessionId, purpose: "login")
            let challenge: PasswordV2ChallengeResponse
            if let signupProof {
                challenge = try await api.request(.post, path: "/v1/auth/password-v2/challenge",
                    serverProfile: signupProof.serverProfile, body: challengeRequest)
            } else {
                challenge = try await api.request(.post, path: "/v1/auth/password-v2/challenge",
                    body: challengeRequest)
            }
            guard challenge.expiresIn > 0,
                  let nonce = Data(base64URLEncoded: challenge.nonce), nonce.count == 32 else {
                throw AuthError.missingAuthData
            }
            request.credentialVersion = 2
            request.challengeId = challenge.challengeId
            request.passwordProof = try keys.proof(purpose: "login", nonce: nonce)
            let v2Response = try await send(request)
            // Anti-enumeration decoys report success/TFA without a real identity.
            // Match the web's acceptance gate before deciding against legacy login.
            if (v2Response.success && v2Response.hasAcceptedPasswordIdentity) || signupProof != nil {
                response = v2Response
            } else {
                request.credentialVersion = nil
                request.challengeId = nil
                request.passwordProof = nil
                request.lookupHash = await crypto.hashKey(password, salt: saltData)
                response = try await send(request)
            }
        } catch let error as APIError {
            // A rejected v2 proof can be an existing legacy account. The server
            // must reject this fallback for any record already upgraded to v2.
            guard signupProof == nil, case .httpError(let status, _) = error,
                  status == 401 || status == 403 else { throw error }
            request.credentialVersion = nil
            request.challengeId = nil
            request.passwordProof = nil
            request.lookupHash = await crypto.hashKey(password, salt: saltData)
            response = try await send(request)
        } catch let error as PairOpaqueError {
            guard signupProof == nil else { throw error }
            request.credentialVersion = nil
            request.challengeId = nil
            request.passwordProof = nil
            request.lookupHash = await crypto.hashKey(password, salt: saltData)
            response = try await send(request)
        }
        NativeDiagnostics.info(
            "phase=passwordLogin.response success=\(response.success) tfaRequired=\(response.tfaRequired == true) hasUser=\(response.user != nil) needsDeviceVerification=\(response.needsDeviceVerification == true)",
            category: "auth"
        )

        if response.tfaRequired == true, tfaCode == nil {
            NativeDiagnostics.info("phase=passwordLogin.awaitingTFA", category: "auth")
            throw AuthError.tfaRequired
        }

        if response.needsDeviceVerification == true,
           let type = response.deviceVerificationType {
            state = .needsDeviceVerification(type: type)
            return
        }

        if response.success, response.user != nil {
            NativeDiagnostics.info("phase=passwordLogin.unwrapMasterKey", category: "auth")
            let migrationBaseline: SymmetricKey?
            if let user = response.user, user.credentialVersion == 2,
               PasswordV2MigrationPendingStore.contains(user.id) {
                migrationBaseline = try? await crypto.loadMasterKey(for: user.id)
            } else {
                migrationBaseline = nil
            }
            try await handleSuccessfulLogin(response: response, password: password, signupProof: signupProof, signupSessionId: signupSessionId)
            if signupProof == nil, let user = response.user {
                if user.credentialVersion == 2, let migrationBaseline,
                   PasswordV2MigrationPendingStore.contains(user.id) {
                    await completeStagedPasswordMigration(user: user, password: password,
                                                          expected: migrationBaseline,
                                                          derivedKeys: derivedV2Keys)
                } else if user.credentialVersion == nil || user.credentialVersion == 1 {
                    await migrateLegacyPasswordIfPossible(user: user, password: password,
                                                          emailSalt: saltData,
                                                          derivedKeys: derivedV2Keys)
                }
            }
            return
        }

        if tfaCode != nil {
            throw AuthError.invalidTwoFactorCode
        }

        throw AuthError.invalidCredentials
    }

    // MARK: - Recovery key login

    func loginWithRecoveryKey(email: String, recoveryKey: String, userEmailSalt: String?) async throws {
        validationGeneration = UUID()
        guard let userEmailSalt,
              let saltData = Data(base64Encoded: userEmailSalt) else {
            print("[Auth] Missing user_email_salt from lookup; cannot compute recovery-key lookup_hash")
            throw AuthError.missingAuthData
        }

        let hashedEmail = await crypto.hashEmail(email)
        let lookupHash = await crypto.hashKey(recoveryKey, salt: saltData)
        let emailEncryptionKey = await crypto.deriveEmailEncryptionKey(
            email: email,
            salt: saltData
        ).base64EncodedString()

        let request = LoginRequest(
            hashedEmail: hashedEmail,
            lookupHash: lookupHash,
            loginMethod: "recovery_key",
            tfaCode: nil,
            codeType: nil,
            emailEncryptionKey: emailEncryptionKey,
            stayLoggedIn: false,
            sessionId: Self.sessionId,
            deviceInfo: makeDeviceInfo()
        )

        let response: LoginResponse = try await api.request(.post, path: "/v1/auth/login", body: request)
        print("[Auth] Recovery login response success=\(response.success) hasUser=\(response.user != nil)")

        if response.success, response.user != nil {
            // Recovery key uses same PBKDF2 derivation as password
            try await handleSuccessfulLogin(response: response, password: recoveryKey, wrapperVersion: 1)
            return
        }

        throw AuthError.invalidCredentials
    }

    // MARK: - Backup code login

    func loginWithBackupCode(
        email: String,
        password: String,
        backupCode: String,
        userEmailSalt: String?
    ) async throws {
        try await loginWithPassword(
            email: email, password: password, userEmailSalt: userEmailSalt,
            tfaCode: backupCode, codeType: "backup")
    }

    // MARK: - Device verification

    func verifyDeviceWith2FA(code: String) async throws {
        let _: DeviceVerifyResponse = try await api.request(
            .post,
            path: "/v1/auth/2fa/verify/device",
            body: DeviceVerifyRequest(code: code)
        )
        // Approved verification must re-read the authoritative session before
        // resuming protected services or issuing a WebSocket credential.
        sessionValidationState = .offlineAuthenticated
        state = .authenticated
        await validateSessionAgainstServer(keepOfflineSessionOnFailure: currentUser != nil)
    }

    func completePasskeyLogin(response: LoginResponse, masterKey: SymmetricKey) async throws {
        validationGeneration = UUID()
        if response.needsDeviceVerification == true,
           let type = response.deviceVerificationType {
            state = .needsDeviceVerification(type: type)
            return
        }

        guard response.success, let user = response.user else {
            throw AuthError.invalidCredentials
        }

        webSocketToken = response.wsToken
        try activateOfflineScope(for: user)
        currentUser = user
        try await crypto.saveMasterKey(masterKey, for: user.id)
        await migrateLegacyComposerDrafts()
        cacheAuthenticatedUser(user)
        PairSessionDeadlineStore.save(userID: user.id, deadline: response.pairExpiresAt)
        schedulePairDeadline(for: user.id)
        sessionValidationState = .onlineAuthenticated
        state = .authenticated
    }

    // Signup publishes only after a fresh assertion unwraps the same newly
    // generated master key and /login returns the matching credential envelope.
    func completeNativePasskeySignup(response: LoginResponse, masterKey: SymmetricKey,
        proof: NativeSignupLoginProof, contextIsCurrent: @escaping @MainActor () -> Bool) async throws {
        try validateSignupContext(proof, sessionId: proof.sessionId)
        guard contextIsCurrent(), proof.validates(response), proof.validatesMasterKey(masterKey),
              let user = response.user else { throw NativeSignupError.sessionProofMismatch }
        let owner = UUID()
        validationGeneration = owner
        try await crypto.saveMasterKey(masterKey, for: user.id)
        try validateSignupContext(proof, sessionId: proof.sessionId)
        guard validationGeneration == owner, contextIsCurrent() else { throw NativeSignupError.staleContext }
        try activateOfflineScope(for: user)
        currentUser = user
        await migrateLegacyComposerDrafts()
        try validateSignupContext(proof, sessionId: proof.sessionId, publishingUserId: user.id)
        guard validationGeneration == owner, currentUser?.id == user.id else { throw NativeSignupError.staleContext }
        webSocketToken = response.wsToken
        cacheAuthenticatedUser(user)
        sessionValidationState = .onlineAuthenticated
        state = .authenticated
    }

    func completePairLogin(response: LoginResponse, masterKey: SymmetricKey,
                           acknowledge: () async throws -> Void) async throws {
        validationGeneration = UUID()
        if response.needsDeviceVerification == true,
           let type = response.deviceVerificationType {
            state = .needsDeviceVerification(type: type)
            return
        }

        guard response.success, let user = response.user else {
            throw AuthError.invalidCredentials
        }

        PairPendingAckStore.mark(userID: user.id)
        try await crypto.saveMasterKey(masterKey, for: user.id)
        try activateOfflineScope(for: user)
        cacheAuthenticatedUser(user)
        PairSessionDeadlineStore.save(userID: user.id, deadline: response.pairExpiresAt)
        do {
            try PairPendingAckStore.flushLocalPairState()
            try await acknowledge()
        } catch {
            currentUser = user
            await forceLocalLogout(reason: "pair_acknowledgment_failed")
            throw error
        }
        PairPendingAckStore.clear()
        currentUser = user
        await migrateLegacyComposerDrafts()
        webSocketToken = response.wsToken
        schedulePairDeadline(for: user.id)
        sessionValidationState = .onlineAuthenticated
        state = .authenticated
    }

    // MARK: - Logout

    func logout() async {
        validationGeneration = UUID()
        await PushNotificationManager.shared.unregisterCurrentDevice()
        do {
            let _: Data = try await api.request(.post, path: "/v1/auth/logout")
        } catch {
            NativeDiagnostics.warning(
                "phase=serverLogout.failed errorType=\(type(of: error))",
                category: "auth"
            )
        }

        AppSessionCoordinator.shared.resetTransientRuntime()
        await clearComposerDraftsForLogout()
        OfflineStore.shared.deactivate()
        NotificationPreviewCrypto.clearPrivateKey()
        if let userId = currentUser?.id {
            try? await crypto.deleteMasterKey(for: userId)
        }

        // Clear decryption key caches and Spotlight index on logout
        ChatKeyManager.shared.clearAll()
        EmbedKeyManager.shared.clearAll()
        SpotlightIndexer.shared.removeAllItems()
        Self.resetNativeSessionId()
        Self.clearCachedUser()
        PairSessionDeadlineStore.clear()
        PairPendingAckStore.clear()
        PairVerifiedAccountStore.clear()

        webSocketToken = nil
        currentUser = nil
        sessionValidationState = .unauthenticated
        state = .unauthenticated
    }

    func forceLocalLogout(reason: String) async {
        validationGeneration = UUID()
        PushNotificationManager.shared.invalidateRegistration()
        print("[Auth] Forced local logout reason=\(reason)")
        AppSessionCoordinator.shared.resetTransientRuntime()
        await clearComposerDraftsForLogout()
        OfflineStore.shared.deactivate()
        NotificationPreviewCrypto.clearPrivateKey()
        if let userId = currentUser?.id {
            try? await crypto.deleteMasterKey(for: userId)
        } else {
            try? KeychainHelper.deleteAll()
        }
        ChatKeyManager.shared.clearAll()
        EmbedKeyManager.shared.clearAll()
        SpotlightIndexer.shared.removeAllItems()
        Self.resetNativeSessionId()
        Self.clearCachedUser()
        PairSessionDeadlineStore.clear()
        PairPendingAckStore.clear()
        PairVerifiedAccountStore.clear()
        for cookie in OpenMatesSharedEnvironment.cookieStorage.cookies ?? [] {
            OpenMatesSharedEnvironment.cookieStorage.deleteCookie(cookie)
        }
        webSocketToken = nil
        currentUser = nil
        sessionValidationState = .unauthenticated
        state = .unauthenticated
    }

    // MARK: - Private

    private func validateSignupContext(_ proof: NativeSignupLoginProof, sessionId: String, publishingUserId: String? = nil) throws {
        guard !Task.isCancelled, ServerProfile.current() == proof.serverProfile,
              Self.nativeSessionId == sessionId,
              currentUser == nil || currentUser?.id == publishingUserId else {
            throw NativeSignupError.staleContext
        }
    }

    private func migrateLegacyPasswordIfPossible(user: UserProfile, password: String,
                                                 emailSalt: Data,
                                                 derivedKeys: PasswordV2Keys?) async {
        guard currentUser?.id == user.id,
              let masterKey = try? await crypto.loadMasterKey(for: user.id) else { return }
        if PasswordV2MigrationPendingStore.contains(user.id) {
            await completeStagedPasswordMigration(user: user, password: password,
                                                  expected: masterKey, derivedKeys: derivedKeys)
            return
        }
        do {
            // A lagging self-hosted server may still have the old migrate route,
            // which retires typed v1 immediately. Check the staged protocol first.
            let capabilities: PasswordV2MigrationCapabilities = try await api.request(
                .get, path: "/v1/auth/password-v2/migration-capabilities")
            guard capabilities.stagedProtocol == 2, capabilities.confirmRequired else { return }
            let keys = try derivedKeys ?? PasswordV2Keys(password: password, emailSalt: emailSalt)
            let encrypted = try await crypto.encrypt(
                masterKey.withUnsafeBytes { Data($0) }, using: keys.wrappingKey)
            let body = encrypted.ciphertext.base64EncodedString()
            let iv = encrypted.nonce.base64EncodedString()
            try await crypto.verifyMasterKeyRoundTrip(
                wrappedKeyBase64: body, ivBase64: iv,
                wrappingKey: keys.wrappingKey, expected: masterKey)
            let oldHash = await crypto.hashKey(password, salt: emailSalt)
            let status: PasswordV2MigrationStatus = try await api.request(
                .post, path: "/v1/auth/password-v2/migrate",
                body: PasswordV2MigrationRequest(
                    oldLookupHash: oldHash,
                    passwordAuthKey: keys.authenticationKey.base64URLEncodedString(),
                    encryptedMasterKey: body, salt: emailSalt.base64EncodedString(), keyIv: iv))
            guard status.success else { return }
            if status.migrationStatus == "pending_confirmation" {
                PasswordV2MigrationPendingStore.mark(user.id)
                await completeStagedPasswordMigration(user: user, password: password,
                                                      expected: masterKey, derivedKeys: keys)
            }
        } catch APIError.httpError(let status, let message)
            where status == 409 || status == 428 ||
                (status == 401 && (message == "Recent verification required" ||
                                   message == "Fresh password login required")) {
            // Migration is optional after a successful legacy login. A typed
            // account can wait for explicit strong verification, while an
            // untyped account can wait for its credential methods to be bound.
            // Keep the locally unlocked master key and authenticated session.
            NativeDiagnostics.info("Password migration deferred after legacy login", category: "auth")
        } catch {
            NativeDiagnostics.error("Password migration staging unavailable", category: "auth")
        }
    }

    private func completeStagedPasswordMigration(user: UserProfile, password: String,
                                                 expected: SymmetricKey,
                                                 derivedKeys: PasswordV2Keys?) async {
        guard PasswordV2MigrationPendingStore.contains(user.id), currentUser?.id == user.id,
              let saltText = user.userEmailSalt,
              let emailSalt = Data(base64Encoded: saltText) else { return }
        do {
            let keys = try derivedKeys ?? PasswordV2Keys(password: password, emailSalt: emailSalt)
            let challenge: PasswordV2ChallengeResponse = try await api.request(
                .post, path: "/v1/auth/password-v2/staged-challenge",
                body: [:] as [String: String])
            guard challenge.expiresIn > 0,
                  let nonce = Data(base64URLEncoded: challenge.nonce), nonce.count == 32 else {
                throw AuthError.missingAuthData
            }
            let proof = try keys.proof(purpose: "migration", nonce: nonce)
            let wrapper: PasswordV2StagedWrapper = try await api.request(
                .post, path: "/v1/auth/password-v2/verify-staged",
                body: PasswordV2StagedProofRequest(
                    challengeId: challenge.challengeId, passwordProof: proof))
            guard wrapper.credentialVersion == 2, wrapper.salt == saltText else {
                throw AuthError.missingAuthData
            }
            try await crypto.verifyMasterKeyRoundTrip(
                wrappedKeyBase64: wrapper.encryptedKey, ivBase64: wrapper.keyIv,
                wrappingKey: keys.wrappingKey, expected: expected)
            let result: PasswordV2MigrationStatus = try await api.request(
                .post, path: "/v1/auth/password-v2/confirm-migration",
                body: [:] as [String: String])
            guard result.success, result.migrationStatus == "typed_retired" else {
                throw AuthError.missingAuthData
            }
            publishPasswordWrapper(
                for: user.id, encryptedKey: wrapper.encryptedKey,
                keyIv: wrapper.keyIv, salt: wrapper.salt, version: 2)
        } catch APIError.httpError(let status, _) where status == 428 {
            // The pending v1 credential and locally verified wrapper remain
            // intact until a later session has fresh strong verification.
            NativeDiagnostics.info("Password migration confirmation deferred", category: "auth")
        } catch {
            // The typed v1 credential remains available until the server sees
            // an explicit confirm. Retry on the next authenticated login.
            NativeDiagnostics.error("Password migration confirmation unavailable", category: "auth")
        }
    }

    private func handleSuccessfulLogin(response: LoginResponse, password: String,
                                       signupProof: NativeSignupLoginProof? = nil,
                                       signupSessionId: String? = nil,
                                       wrapperVersion: Int? = nil) async throws {
        guard let user = response.user else {
            throw AuthError.invalidCredentials
        }

        // The server returns the wrapper version with the account. Never trial
        // decrypt across KDF versions: unknown versions fail closed.
        guard let encryptedKeyB64 = user.encryptedKey,
              let keyIvB64 = user.keyIv,
              let saltB64 = user.salt,
              let saltData = Data(base64Encoded: saltB64) else {
            throw AuthError.missingAuthData
        }

        let wrappingKey: SymmetricKey
        switch wrapperVersion ?? user.credentialVersion ?? 1 {
        case 1:
            wrappingKey = try await crypto.deriveWrappingKeyFromPassword(password: password, salt: saltData)
        case 2:
            guard let emailSalt = Data(base64Encoded: user.userEmailSalt ?? ""),
                  emailSalt == saltData else { throw AuthError.missingAuthData }
            wrappingKey = try PasswordV2Keys(password: password, emailSalt: emailSalt).wrappingKey
        default:
            throw AuthError.missingAuthData
        }
        NativeDiagnostics.info("phase=passwordLogin.wrappingKeyDerived", category: "auth")
        let masterKey = try await crypto.unwrapMasterKey(
            wrappedKeyBase64: encryptedKeyB64,
            ivBase64: keyIvB64,
            wrappingKey: wrappingKey
        )
        if user.credentialVersion == 2,
           PasswordV2MigrationPendingStore.contains(user.id),
           let previous = try? await crypto.loadMasterKey(for: user.id) {
            guard previous.withUnsafeBytes({ Data($0) }) == masterKey.withUnsafeBytes({ Data($0) }) else {
                throw CryptoManager.CryptoError.decryptionFailed
            }
        }
        NativeDiagnostics.info("phase=passwordLogin.masterKeyUnwrapped", category: "auth")
        if let signupProof, let signupSessionId {
            try validateSignupContext(signupProof, sessionId: signupSessionId)
            guard signupProof.validatesMasterKey(masterKey) else {
                throw NativeSignupError.sessionProofMismatch
            }
        }
        try await crypto.saveMasterKey(masterKey, for: user.id)
        if let signupProof, let signupSessionId {
            try validateSignupContext(signupProof, sessionId: signupSessionId)
        }
        NativeDiagnostics.info("phase=passwordLogin.masterKeySaved", category: "auth")
        try activateOfflineScope(for: user)
        currentUser = user
        await migrateLegacyComposerDrafts()
        NativeDiagnostics.info("phase=passwordLogin.draftsMigrated", category: "auth")
        if let signupProof, let signupSessionId {
            try validateSignupContext(signupProof, sessionId: signupSessionId, publishingUserId: user.id)
        }

        webSocketToken = response.wsToken
        cacheAuthenticatedUser(user)
        sessionValidationState = .onlineAuthenticated

        // Signup owns its private material in SignupViewModel. Do not mutate
        // another login's shared pending state when completing that operation.
        if signupProof == nil {
            pendingPassword = nil
            pendingEmail = nil
        }

        state = .authenticated
        NativeDiagnostics.info("phase=passwordLogin.authenticated", category: "auth")
    }

    private func restoreCachedSessionForStartup() async -> Bool {
        guard let user = Self.cachedUser() else {
            sessionValidationState = .unauthenticated
            state = .unauthenticated
            return false
        }
        guard (try? await crypto.loadMasterKey(for: user.id)) != nil else {
            Self.clearCachedUser()
            sessionValidationState = .unauthenticated
            state = .unauthenticated
            return false
        }
        do {
            try activateOfflineScope(for: user)
        } catch {
            NativeDiagnostics.error("Offline account store could not be opened", category: "auth")
            sessionValidationState = .unauthenticated
            state = .unauthenticated
            return false
        }
        currentUser = user
        schedulePairDeadline(for: user.id)
        await migrateLegacyComposerDrafts()
        webSocketToken = nil
        sessionValidationState = .offlineAuthenticated
        state = .authenticated
        print("[Auth] Restored cached session for offline startup")
        return true
    }

    private func schedulePairDeadline(for userID: String) {
        guard let deadline = PairSessionDeadlineStore.deadline(userID: userID) else { return }
        Task { @MainActor [weak self] in
            let remaining = max(0, deadline - Int(Date().timeIntervalSince1970))
            try? await Task.sleep(for: .seconds(Int64(remaining)))
            guard let self, self.currentUser?.id == userID,
                  PairSessionDeadlineStore.isExpired(userID: userID) else { return }
            await self.forceLocalLogout(reason: "pair_session_expired")
        }
    }

    private func activateOfflineScope(for user: UserProfile) throws {
        let apiBaseURL = ServerConfiguration.current.apiBaseURL
        let store = OfflineStore.shared
        let scope = OfflineStore.scopeId(userId: user.id, apiBaseURL: apiBaseURL)
        if store.activeScopeId != scope {
            PushNotificationManager.shared.invalidateRegistration()
            AppSessionCoordinator.shared.resetTransientRuntime()
            ChatKeyManager.shared.clearAll()
            EmbedKeyManager.shared.clearAll()
            try store.activate(userId: user.id, apiBaseURL: apiBaseURL)
        }
    }

    private func migrateLegacyComposerDrafts() async {
        do {
            try await DraftService.shared.migrateLegacyDraftsAfterUnlock()
        } catch {
            NativeDiagnostics.error(
                "phase=draftMigration.failed errorType=\(type(of: error))",
                category: "composer_drafts"
            )
        }
    }

    private func clearComposerDraftsForLogout() async {
        do {
            try await DraftService.shared.clearAll()
        } catch {
            NativeDiagnostics.error(
                "phase=logoutDraftClear.failed errorType=\(type(of: error))",
                category: "composer_drafts"
            )
        }
    }

    private func cacheAuthenticatedUser(_ user: UserProfile) {
        if let profileCacheWriter { profileCacheWriter(user); return }
        guard let data = try? JSONEncoder().encode(user) else { return }
        UserDefaults.standard.set(data, forKey: Self.cachedUserDefaultsKey)
        OpenMatesSharedEnvironment.defaults.set(data, forKey: Self.cachedUserDefaultsKey)
    }

    static var nativeSessionId: String {
        sessionId
    }

    static func makeNativeDeviceInfo() -> DeviceInfo {
        #if os(iOS)
        let os = "iOS \(ProcessInfo.processInfo.operatingSystemVersionString)"
        #elseif os(macOS)
        let os = "macOS \(ProcessInfo.processInfo.operatingSystemVersionString)"
        #else
        let os = "Apple \(ProcessInfo.processInfo.operatingSystemVersionString)"
        #endif

        return DeviceInfo(
            os: os,
            deviceModel: getNativeDeviceModel(),
            appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
        )
    }

    private func makeDeviceInfo() -> DeviceInfo {
        Self.makeNativeDeviceInfo()
    }

    private static func getNativeDeviceModel() -> String {
        #if os(iOS)
        return UIDevice.current.model
        #else
        var size = 0
        sysctlbyname("hw.model", nil, &size, nil, 0)
        var model = [CChar](repeating: 0, count: size)
        sysctlbyname("hw.model", &model, &size, nil, 0)
        return String(cString: model)
        #endif
    }

    private static var sessionId: String {
        if let existing = OpenMatesSharedEnvironment.defaults.string(forKey: sessionIdDefaultsKey) {
            return existing
        }
        if let existing = UserDefaults.standard.string(forKey: sessionIdDefaultsKey) {
            OpenMatesSharedEnvironment.defaults.set(existing, forKey: sessionIdDefaultsKey)
            return existing
        }
        let newValue = UUID().uuidString
        UserDefaults.standard.set(newValue, forKey: sessionIdDefaultsKey)
        OpenMatesSharedEnvironment.defaults.set(newValue, forKey: sessionIdDefaultsKey)
        return newValue
    }

    private static let sessionIdDefaultsKey = "openmates.apple.auth.session_id"
    private static let cachedUserDefaultsKey = "openmates.apple.auth.cached_user"

    private static func resetNativeSessionId() {
        UserDefaults.standard.removeObject(forKey: sessionIdDefaultsKey)
        OpenMatesSharedEnvironment.defaults.removeObject(forKey: sessionIdDefaultsKey)
    }

    private static func cachedUser() -> UserProfile? {
        guard let data = OpenMatesSharedEnvironment.defaults.data(forKey: cachedUserDefaultsKey)
            ?? UserDefaults.standard.data(forKey: cachedUserDefaultsKey) else { return nil }
        return try? JSONDecoder().decode(UserProfile.self, from: data)
    }

    private static func clearCachedUser() {
        UserDefaults.standard.removeObject(forKey: cachedUserDefaultsKey)
        OpenMatesSharedEnvironment.defaults.removeObject(forKey: cachedUserDefaultsKey)
    }


}
