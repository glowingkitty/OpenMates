// Central auth state manager — mirrors the web app's authStore.ts.
// Handles login flows (password, passkey, recovery key, backup code),
// session persistence, and device verification state.

import Foundation
import SwiftUI
import AuthenticationServices
import CryptoKit

@MainActor
final class AuthManager: ObservableObject {
    @Published var state: AuthState = .initializing
    @Published var currentUser: UserProfile?
    @Published var error: String?
    @Published private(set) var webSocketToken: String?
    @Published private(set) var sessionValidationState: SessionValidationState = .initializing

    private let api = APIClient.shared
    private let crypto = CryptoManager.shared
    typealias SessionValidator = @MainActor (ServerProfile, SessionRequest) async throws -> SessionResponse
    private let sessionValidator: SessionValidator?
    private let profileCacheWriter: ((UserProfile) -> Void)?
    private var validationGeneration = UUID()
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

    /// Cached password for master key derivation after login.
    /// Cleared after successful key unwrap. Needed because the login response
    /// includes the user's encrypted_key which we unwrap with PBKDF2(password, salt).
    private var pendingPassword: String?
    private var pendingEmail: String?

    init(sessionValidator: SessionValidator? = nil, profileCacheWriter: ((UserProfile) -> Void)? = nil) {
        self.sessionValidator = sessionValidator
        self.profileCacheWriter = profileCacheWriter
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

    func profilePreservingNewerSelection(_ received: UserProfile, since revision: Int) -> UserProfile {
        var result = received
        if lastOpenedSelectionRevision != revision, currentUser?.id == received.id {
            result.lastOpened = currentUser?.lastOpened
        }
        return result
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
        if ProcessInfo.processInfo.arguments.contains("--ui-test-authenticated-chat-navigation") {
            currentUser = UserProfile(
                id: "ui-test-chat-navigation-user",
                username: "ui-test-chat-navigation",
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
        let restoredFromDisk = await restoreCachedSessionForStartup()
        guard !restoredFromDisk else { return }
        Task { @MainActor in
            await validateSessionAgainstServer(keepOfflineSessionOnFailure: false)
        }
    }

    func validateSessionAfterOfflineBootstrap() async {
        await validateSessionAgainstServer(keepOfflineSessionOnFailure: currentUser != nil)
    }

    private func validateSessionAgainstServer(keepOfflineSessionOnFailure: Bool) async {
        let generation = UUID()
        validationGeneration = generation
        let profile = ServerProfile.current()
        let sessionId = Self.nativeSessionId
        let accountId = currentUser?.id
        let selectionRevision = lastOpenedSelectionRevision
        func ownsValidation() -> Bool {
            !Task.isCancelled && validationGeneration == generation &&
                ServerProfile.current() == profile && Self.nativeSessionId == sessionId &&
                currentUser?.id == accountId
        }
        sessionValidationState = .validating
        do {
            let request = SessionRequest(sessionId: sessionId, deviceInfo: makeDeviceInfo())
            let response: SessionResponse
            if let sessionValidator {
                response = try await sessionValidator(profile, request)
            } else {
                response = try await api.request(.post, path: "/v1/auth/session",
                    serverProfile: profile, body: request)
            }
            guard ownsValidation() else { return }

            if response.isAuthenticated, let user = response.user {
                if response.needsDeviceVerification != true,
                   (try? await crypto.loadMasterKey(for: user.id)) == nil {
                    guard ownsValidation() else { return }
                    await forceLocalLogout(reason: "missing_master_key")
                    return
                }
                guard ownsValidation() else { return }
                let user = profilePreservingNewerSelection(user, since: selectionRevision)
                try activateOfflineScope(for: user)
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
                if keepOfflineSessionOnFailure,
                   !Self.requiresDestructiveLocalLogout(reason: reason) {
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
            webSocketToken = nil
            if keepOfflineSessionOnFailure {
                // An explicit rejected session is not an offline connection.
                // Keep cached account data, but expose a real sign-in route.
                if case APIError.httpError(status: 401, message: _) = error {
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
        let lookupHash = await crypto.hashKey(password, salt: saltData)
        let emailEncryptionKey = await crypto.deriveEmailEncryptionKey(
            email: email,
            salt: saltData
        ).base64EncodedString()

        // Store password temporarily for PBKDF2 master key derivation after login
        if let signupProof, let signupSessionId {
            try validateSignupContext(signupProof, sessionId: signupSessionId)
        } else {
            pendingPassword = password
            pendingEmail = email
        }

        let request = LoginRequest(
            hashedEmail: hashedEmail,
            lookupHash: lookupHash,
            loginMethod: "password",
            tfaCode: tfaCode,
            codeType: tfaCode == nil ? nil : (codeType ?? "otp"),
            emailEncryptionKey: emailEncryptionKey,
            stayLoggedIn: stayLoggedIn,
            sessionId: Self.sessionId,
            deviceInfo: makeDeviceInfo()
        )

        NativeDiagnostics.info("phase=passwordLogin.request", category: "auth")
        let response: LoginResponse
        if let signupProof, let signupSessionId {
            try validateSignupContext(signupProof, sessionId: signupSessionId)
            response = try await api.request(.post, path: "/v1/auth/login",
                serverProfile: signupProof.serverProfile, body: request)
            try validateSignupContext(signupProof, sessionId: signupSessionId)
            guard signupProof.validates(response) else {
                throw NativeSignupError.sessionProofMismatch
            }
        } else {
            response = try await api.request(.post, path: "/v1/auth/login", body: request)
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
            try await handleSuccessfulLogin(response: response, password: password, signupProof: signupProof, signupSessionId: signupSessionId)
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
            try await handleSuccessfulLogin(response: response, password: recoveryKey)
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
        let hashedEmail = await crypto.hashEmail(email)
        guard let userEmailSalt,
              let saltData = Data(base64Encoded: userEmailSalt) else {
            print("[Auth] Missing user_email_salt from lookup; cannot compute backup-code lookup_hash")
            throw AuthError.missingAuthData
        }
        let lookupHash = await crypto.hashKey(password, salt: saltData)
        let emailEncryptionKey = await crypto.deriveEmailEncryptionKey(
            email: email,
            salt: saltData
        ).base64EncodedString()

        let request = LoginRequest(
            hashedEmail: hashedEmail,
            lookupHash: lookupHash,
            loginMethod: "backup_code",
            tfaCode: backupCode,
            codeType: "backup",
            emailEncryptionKey: emailEncryptionKey,
            stayLoggedIn: false,
            sessionId: Self.sessionId,
            deviceInfo: makeDeviceInfo()
        )

        let response: LoginResponse = try await api.request(.post, path: "/v1/auth/login", body: request)
        print("[Auth] Backup-code login response success=\(response.success) hasUser=\(response.user != nil)")

        if response.success, response.user != nil {
            try await handleSuccessfulLogin(response: response, password: password)
            return
        }

        throw AuthError.invalidCredentials
    }

    // MARK: - Device verification

    func verifyDeviceWith2FA(code: String) async throws {
        let _: DeviceVerifyResponse = try await api.request(
            .post,
            path: "/v1/auth/2fa/verify/device",
            body: DeviceVerifyRequest(code: code)
        )
        state = .authenticated
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

    func completePairLogin(response: LoginResponse, masterKey: SymmetricKey) async throws {
        validationGeneration = UUID()
        if response.needsDeviceVerification == true,
           let type = response.deviceVerificationType {
            state = .needsDeviceVerification(type: type)
            return
        }

        guard response.success, let user = response.user else {
            throw AuthError.invalidCredentials
        }

        try await crypto.saveMasterKey(masterKey, for: user.id)
        try activateOfflineScope(for: user)
        currentUser = user
        await migrateLegacyComposerDrafts()
        webSocketToken = response.wsToken
        cacheAuthenticatedUser(user)
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
        if let userId = currentUser?.id {
            try? await crypto.deleteMasterKey(for: userId)
        }

        // Clear decryption key caches and Spotlight index on logout
        ChatKeyManager.shared.clearAll()
        EmbedKeyManager.shared.clearAll()
        SpotlightIndexer.shared.removeAllItems()
        Self.resetNativeSessionId()
        Self.clearCachedUser()

        webSocketToken = nil
        currentUser = nil
        sessionValidationState = .unauthenticated
        state = .unauthenticated
    }

    func forceLocalLogout(reason: String) async {
        validationGeneration = UUID()
        print("[Auth] Forced local logout reason=\(reason)")
        AppSessionCoordinator.shared.resetTransientRuntime()
        await clearComposerDraftsForLogout()
        OfflineStore.shared.deactivate()
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

    private func handleSuccessfulLogin(response: LoginResponse, password: String,
                                       signupProof: NativeSignupLoginProof? = nil,
                                       signupSessionId: String? = nil) async throws {
        guard let user = response.user else {
            throw AuthError.invalidCredentials
        }

        // Derive PBKDF2 wrapping key from password + salt, then unwrap master key.
        // Mirrors web: deriveKeyFromPassword(password, salt) → decryptKey(encrypted_key, key_iv, wrappingKey)
        guard let encryptedKeyB64 = user.encryptedKey,
              let keyIvB64 = user.keyIv,
              let saltB64 = user.salt,
              let saltData = Data(base64Encoded: saltB64) else {
            throw AuthError.missingAuthData
        }

        let wrappingKey = try await crypto.deriveWrappingKeyFromPassword(
            password: password, salt: saltData
        )
        NativeDiagnostics.info("phase=passwordLogin.wrappingKeyDerived", category: "auth")
        let masterKey = try await crypto.unwrapMasterKey(
            wrappedKeyBase64: encryptedKeyB64,
            ivBase64: keyIvB64,
            wrappingKey: wrappingKey
        )
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
        await migrateLegacyComposerDrafts()
        webSocketToken = nil
        sessionValidationState = .offlineAuthenticated
        state = .authenticated
        print("[Auth] Restored cached session for offline startup")
        return true
    }

    private func activateOfflineScope(for user: UserProfile) throws {
        let apiBaseURL = ServerConfiguration.current.apiBaseURL
        let store = OfflineStore.shared
        let scope = OfflineStore.scopeId(userId: user.id, apiBaseURL: apiBaseURL)
        if store.activeScopeId != scope {
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

    private static func requiresDestructiveLocalLogout(reason: String) -> Bool {
        let normalized = reason.lowercased()
        return normalized.contains("revoked")
            || normalized.contains("logout")
            || normalized.contains("deleted")
            || normalized.contains("disabled")
            || normalized.contains("banned")
    }
}
