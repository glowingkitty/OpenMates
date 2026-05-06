// Auth data models matching the backend Pydantic schemas.
// Used for login, lookup, session, and device verification flows.

import Foundation

// MARK: - Lookup

struct LookupRequest: Encodable {
    let hashedEmail: String
    let stayLoggedIn: Bool
}

struct LookupResponse: Decodable {
    let availableLoginMethods: [LoginMethod]
    let tfaEnabled: Bool
    let tfaAppName: String?
    let userEmailSalt: String? // Salt for PBKDF2 derivation and email encryption
}

enum LoginMethod: String, Decodable {
    case password
    case passkey
    case recoveryKey = "recovery_key"
    case backupCode = "backup_code"
}

// MARK: - Login

struct LoginRequest: Encodable {
    let hashedEmail: String
    let lookupHash: String
    let loginMethod: String
    var credentialId: String? = nil
    let tfaCode: String?
    let codeType: String?
    let emailEncryptionKey: String?
    let stayLoggedIn: Bool
    let sessionId: String?
    let deviceInfo: DeviceInfo?
}

struct DeviceInfo: Encodable {
    let os: String
    let deviceModel: String
    let appVersion: String
}

struct LoginResponse: Decodable {
    let success: Bool
    let tfaRequired: Bool?
    let user: UserProfile?     // Server sends crypto fields on user object
    let needsDeviceVerification: Bool?
    let deviceVerificationType: String?
    let wsToken: String?
}

// MARK: - Session check

struct SessionResponse: Decodable {
    let isAuthenticated: Bool
    let user: UserProfile?
    let needsDeviceVerification: Bool?
    let deviceVerificationType: String?
}

// MARK: - User

struct UserProfile: Decodable, Identifiable {
    let id: String
    let username: String
    let email: String?
    let credits: Double?
    let language: String?
    let darkmode: Bool?
    let timezone: String?
    let lastOpened: String?
    let profileImageUrl: String?
    let isAdmin: Bool?

    // E2EE crypto fields — returned by server on login and session check
    let encryptedKey: String?   // Master key wrapped with PBKDF2-derived wrapping key (base64)
    let keyIv: String?          // 12-byte IV for master key wrapping (base64)
    let salt: String?           // PBKDF2 salt (base64)
    let userEmailSalt: String?  // Salt for email encryption key derivation

    // Settings fields synced from server
    let autoDeleteChatsAfterDays: Int?
    let pushNotificationEnabled: Bool?
}

// MARK: - Passkey

struct PasskeyAssertionInitResponse: Decodable {
    let success: Bool
    let challenge: String
    let rp: PasskeyRelyingParty
    let timeout: Int?
    let userVerification: String?
    let allowCredentials: [PasskeyCredential]?
    let extensions: PasskeyAssertionExtensions?
    let message: String?
}

struct PasskeyRelyingParty: Decodable {
    let id: String
    let name: String
}

struct PasskeyAssertionExtensions: Decodable {
    let prf: PasskeyPRFExtension?
}

struct PasskeyPRFExtension: Decodable {
    let eval: PasskeyPRFEvaluation?
}

struct PasskeyPRFEvaluation: Decodable {
    let first: String?
}

struct PasskeyCredential: Decodable {
    let id: String
    let type: String
}

struct PasskeyAssertionVerifyRequest: Encodable {
    let credentialId: String
    let assertionResponse: PasskeyAssertionData
    let clientDataJSON: String
    let authenticatorData: String
    let sessionId: String?
    let stayLoggedIn: Bool
    let hashedEmail: String?
    let emailEncryptionKey: String?
}

struct PasskeyAssertionData: Encodable {
    let authenticatorData: String
    let clientDataJSON: String
    let signature: String
    let userHandle: String?
}

struct PasskeyVerifyResponse: Decodable {
    let success: Bool
    let message: String?
    let userId: String?
    let hashedEmail: String?
    let encryptedEmail: String?
    let encryptedMasterKey: String?
    let keyIv: String?
    let salt: String?
    let userEmailSalt: String?
    let userEmail: String?
    let authSession: PasskeyAuthSession?
}

struct PasskeyAuthSession: Decodable {
    let user: UserProfile?
    let wsToken: String?
}

// MARK: - Device verification

struct DeviceVerifyRequest: Encodable {
    let code: String
}

struct DeviceVerifyResponse: Decodable {
    let success: Bool
}
