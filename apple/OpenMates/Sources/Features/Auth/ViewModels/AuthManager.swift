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

    // MARK: - Session check (app launch)

    func checkSession() async {
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

    func lookup(email: String) async throws -> LookupResponse {
        let hashedEmail = await crypto.hashEmail(email)
        return try await api.request(
            .post,
            path: "/v1/auth/lookup",
            body: LookupRequest(hashedEmail: hashedEmail)
        )
    }

    // MARK: - Password login

    func loginWithPassword(
        email: String,
        password: String,
        tfaCode: String? = nil,
        stayLoggedIn: Bool = false
    ) async throws {
        let hashedEmail = await crypto.hashEmail(email)
        let lookupHash = await crypto.hashPassword(password, email: email)

        let request = LoginRequest(
            hashedEmail: hashedEmail,
            lookupHash: lookupHash,
            loginMethod: "password",
            tfaCode: tfaCode,
            stayLoggedIn: stayLoggedIn,
            sessionId: nil,
            deviceInfo: makeDeviceInfo()
        )

        let response: LoginResponse = try await api.request(.post, path: "/v1/auth/login", body: request)

        if response.tfaRequired == true {
            throw AuthError.tfaRequired
        }

        if response.needsDeviceVerification == true,
           let type = response.deviceVerificationType {
            state = .needsDeviceVerification(type: type)
            return
        }

        if response.success, let session = response.authSession {
            await handleSuccessfulLogin(session: session, response: response, email: email)
        }
    }

    // MARK: - Recovery key login

    func loginWithRecoveryKey(email: String, recoveryKey: String) async throws {
        let hashedEmail = await crypto.hashEmail(email)

        let request = LoginRequest(
            hashedEmail: hashedEmail,
            lookupHash: recoveryKey,
            loginMethod: "recovery_key",
            tfaCode: nil,
            stayLoggedIn: false,
            sessionId: nil,
            deviceInfo: makeDeviceInfo()
        )

        let response: LoginResponse = try await api.request(.post, path: "/v1/auth/login", body: request)

        if response.success, let session = response.authSession {
            await handleSuccessfulLogin(session: session, response: response, email: email)
        }
    }

    // MARK: - Backup code login

    func loginWithBackupCode(email: String, password: String, backupCode: String) async throws {
        let hashedEmail = await crypto.hashEmail(email)
        let lookupHash = await crypto.hashPassword(password, email: email)

        let request = LoginRequest(
            hashedEmail: hashedEmail,
            lookupHash: lookupHash,
            loginMethod: "backup_code",
            tfaCode: backupCode,
            stayLoggedIn: false,
            sessionId: nil,
            deviceInfo: makeDeviceInfo()
        )

        let response: LoginResponse = try await api.request(.post, path: "/v1/auth/login", body: request)

        if response.success, let session = response.authSession {
            await handleSuccessfulLogin(session: session, response: response, email: email)
        }
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

        currentUser = nil
        state = .unauthenticated
    }

    // MARK: - Private

    private func handleSuccessfulLogin(
        session: AuthSession,
        response: LoginResponse,
        email: String
    ) async {
        currentUser = session.user

        // Decrypt and store master key if provided
        if let encKeyHex = response.encryptedMasterKey,
           let ivHex = response.keyIv,
           let saltHex = response.userEmailSalt {
            do {
                let emailKey = await crypto.deriveEmailKey(email: email, salt: saltHex)
                let encKey = Data(hexString: encKeyHex)
                let iv = Data(hexString: ivHex)
                let masterKey = try await crypto.decryptMasterKey(encryptedKey: encKey, iv: iv, wrappingKey: emailKey)
                try await crypto.saveMasterKey(masterKey, for: session.user.id)
            } catch {
                print("[Auth] Failed to decrypt/store master key: \(error)")
            }
        }

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
}

enum AuthError: LocalizedError {
    case tfaRequired
    case invalidCredentials
    case deviceVerificationRequired

    var errorDescription: String? {
        switch self {
        case .tfaRequired: return "Two-factor authentication required"
        case .invalidCredentials: return "Invalid email or password"
        case .deviceVerificationRequired: return "Device verification required"
        }
    }
}
