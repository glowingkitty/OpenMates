// Central auth state manager — mirrors the web app's authStore.ts.
// Handles login flows (password, passkey, recovery key, backup code),
// session persistence, and device verification state.

import Foundation
import SwiftUI
import AuthenticationServices

@MainActor
final class AuthManager: ObservableObject {
    @Published var state: AuthState = .initializing
    @Published var currentUser: UserProfile?
    @Published var error: String?

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
        do {
            let response: SessionResponse = try await api.request(.get, path: "/v1/auth/session")

            if response.isAuthenticated, let user = response.user {
                currentUser = user
                if response.needsDeviceVerification == true,
                   let type = response.deviceVerificationType {
                    state = .needsDeviceVerification(type: type)
                } else {
                    state = .authenticated
                }
            } else {
                state = .unauthenticated
            }
        } catch {
            state = .unauthenticated
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
            codeType: tfaCode == nil ? nil : "otp",
            emailEncryptionKey: emailEncryptionKey,
            stayLoggedIn: stayLoggedIn,
            sessionId: Self.sessionId,
            deviceInfo: makeDeviceInfo()
        )

        let response: LoginResponse = try await api.request(.post, path: "/v1/auth/login", body: request)
        print("[Auth] Password login response success=\(response.success) tfaRequired=\(response.tfaRequired == true) hasUser=\(response.user != nil) needsDeviceVerification=\(response.needsDeviceVerification == true)")

        if response.success, response.tfaRequired == true, tfaCode == nil {
            throw AuthError.tfaRequired
        }

        if response.needsDeviceVerification == true,
           let type = response.deviceVerificationType {
            state = .needsDeviceVerification(type: type)
            return
        }

        if response.success, let user = response.user {
            await handleSuccessfulLogin(user: user, password: password)
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

        if response.success, let user = response.user {
            // Recovery key uses same PBKDF2 derivation as password
            await handleSuccessfulLogin(user: user, password: recoveryKey)
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

        if response.success, let user = response.user {
            await handleSuccessfulLogin(user: user, password: password)
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
        SpotlightIndexer.shared.removeAllItems()

        currentUser = nil
        state = .unauthenticated
    }

    // MARK: - Private

    private func handleSuccessfulLogin(user: UserProfile, password: String) async {
        currentUser = user

        // Derive PBKDF2 wrapping key from password + salt, then unwrap master key.
        // Mirrors web: deriveKeyFromPassword(password, salt) → decryptKey(encrypted_key, key_iv, wrappingKey)
        if let encryptedKeyB64 = user.encryptedKey,
           let keyIvB64 = user.keyIv,
           let saltB64 = user.salt,
           let saltData = Data(base64Encoded: saltB64) {
            do {
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
            } catch {
                print("[Auth] Failed to derive/store master key: \(error)")
            }
        }

        // Clear sensitive data
        pendingPassword = nil
        pendingEmail = nil

        state = .authenticated
    }

    private func makeDeviceInfo() -> DeviceInfo {
        #if os(iOS)
        let os = "iOS \(ProcessInfo.processInfo.operatingSystemVersionString)"
        #elseif os(macOS)
        let os = "macOS \(ProcessInfo.processInfo.operatingSystemVersionString)"
        #else
        let os = "Apple \(ProcessInfo.processInfo.operatingSystemVersionString)"
        #endif

        return DeviceInfo(
            os: os,
            deviceModel: getDeviceModel(),
            appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
        )
    }

    private func getDeviceModel() -> String {
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
        let key = "openmates.apple.auth.session_id"
        if let existing = UserDefaults.standard.string(forKey: key) {
            return existing
        }
        let newValue = UUID().uuidString
        UserDefaults.standard.set(newValue, forKey: key)
        return newValue
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
