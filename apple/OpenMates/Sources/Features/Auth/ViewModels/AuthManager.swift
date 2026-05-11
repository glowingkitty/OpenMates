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

    private let api = APIClient.shared
    private let crypto = CryptoManager.shared

    /// Static accessor for the current user ID (used by ChatViewModel for key loading).
    /// Safe to call from any @MainActor context.
    private static weak var _shared: AuthManager?

    static func currentUserId() async -> String? {
        await MainActor.run { _shared?.currentUser?.id }
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

    /// Cached password for master key derivation after login.
    /// Cleared after successful key unwrap. Needed because the login response
    /// includes the user's encrypted_key which we unwrap with PBKDF2(password, salt).
    private var pendingPassword: String?
    private var pendingEmail: String?

    // MARK: - Session check (app launch)

    func checkSession() async {
        Self._shared = self
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
        do {
            let response: SessionResponse = try await api.request(
                .post,
                path: "/v1/auth/session",
                body: SessionRequest(sessionId: Self.sessionId, deviceInfo: makeDeviceInfo())
            )

            if response.isAuthenticated, let user = response.user {
                if response.needsDeviceVerification != true,
                   (try? await crypto.loadMasterKey(for: user.id)) == nil {
                    await forceLocalLogout(reason: "missing_master_key")
                    return
                }
                currentUser = user
                webSocketToken = response.wsToken
                cacheAuthenticatedUser(user)
                if response.needsDeviceVerification == true,
                   let type = response.deviceVerificationType {
                    state = .needsDeviceVerification(type: type)
                } else {
                    state = .authenticated
                }
            } else {
                await forceLocalLogout(reason: response.reAuthReason ?? response.reAuthRequired ?? "session_invalid")
            }
        } catch {
            webSocketToken = nil
            if keepOfflineSessionOnFailure {
                print("[Auth] Session validation unavailable; keeping cached offline session: \(error.localizedDescription)")
            } else {
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
        stayLoggedIn: Bool = false
    ) async throws {
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
        pendingPassword = password
        pendingEmail = email

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

        let response: LoginResponse = try await api.request(.post, path: "/v1/auth/login", body: request)
        print("[Auth] Password login response success=\(response.success) tfaRequired=\(response.tfaRequired == true) hasUser=\(response.user != nil) needsDeviceVerification=\(response.needsDeviceVerification == true)")

        if response.tfaRequired == true, tfaCode == nil {
            throw AuthError.tfaRequired
        }

        if response.needsDeviceVerification == true,
           let type = response.deviceVerificationType {
            state = .needsDeviceVerification(type: type)
            return
        }

        if response.success, response.user != nil {
            try await handleSuccessfulLogin(response: response, password: password)
            return
        }

        if tfaCode != nil {
            throw AuthError.invalidTwoFactorCode
        }

        throw AuthError.invalidCredentials
    }

    // MARK: - Recovery key login

    func loginWithRecoveryKey(email: String, recoveryKey: String, userEmailSalt: String?) async throws {
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
        if response.needsDeviceVerification == true,
           let type = response.deviceVerificationType {
            state = .needsDeviceVerification(type: type)
            return
        }

        guard response.success, let user = response.user else {
            throw AuthError.invalidCredentials
        }

        webSocketToken = response.wsToken
        currentUser = user
        try await crypto.saveMasterKey(masterKey, for: user.id)
        cacheAuthenticatedUser(user)
        state = .authenticated
    }

    func completePairLogin(response: LoginResponse, masterKey: SymmetricKey) async throws {
        if response.needsDeviceVerification == true,
           let type = response.deviceVerificationType {
            state = .needsDeviceVerification(type: type)
            return
        }

        guard response.success, let user = response.user else {
            throw AuthError.invalidCredentials
        }

        try await crypto.saveMasterKey(masterKey, for: user.id)
        webSocketToken = response.wsToken
        currentUser = user
        cacheAuthenticatedUser(user)
        state = .authenticated
    }

    // MARK: - Logout

    func logout() async {
        do {
            let _: Data = try await api.request(.post, path: "/v1/auth/logout")
        } catch {
            // Best-effort server logout
        }

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
        state = .unauthenticated
    }

    func forceLocalLogout(reason: String) async {
        print("[Auth] Forced local logout reason=\(reason)")
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
        state = .unauthenticated
    }

    // MARK: - Private

    private func handleSuccessfulLogin(response: LoginResponse, password: String) async throws {
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

        let wrappingKey = await crypto.deriveWrappingKeyFromPassword(
            password: password, salt: saltData
        )
        let masterKey = try await crypto.unwrapMasterKey(
            wrappedKeyBase64: encryptedKeyB64,
            ivBase64: keyIvB64,
            wrappingKey: wrappingKey
        )
        try await crypto.saveMasterKey(masterKey, for: user.id)
        print("[Auth] Master key derived and saved to Keychain")

        webSocketToken = response.wsToken
        currentUser = user
        cacheAuthenticatedUser(user)

        // Clear sensitive data
        pendingPassword = nil
        pendingEmail = nil

        state = .authenticated
    }

    private func restoreCachedSessionForStartup() async -> Bool {
        guard let user = Self.cachedUser() else {
            state = .unauthenticated
            return false
        }
        guard (try? await crypto.loadMasterKey(for: user.id)) != nil else {
            Self.clearCachedUser()
            state = .unauthenticated
            return false
        }
        currentUser = user
        webSocketToken = nil
        state = .authenticated
        print("[Auth] Restored cached session for offline startup")
        return true
    }

    private func cacheAuthenticatedUser(_ user: UserProfile) {
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

enum AuthError: LocalizedError {
    case tfaRequired
    case invalidCredentials
    case deviceVerificationRequired
    case missingAuthData
    case invalidTwoFactorCode

    var errorDescription: String? {
        switch self {
        case .tfaRequired: return "Two-factor authentication required"
        case .invalidCredentials: return "Invalid email or password"
        case .deviceVerificationRequired: return "Device verification required"
        case .missingAuthData: return "Authentication data not found. Please try logging in again."
        case .invalidTwoFactorCode: return "The two-factor code is wrong or expired"
        }
    }
}
