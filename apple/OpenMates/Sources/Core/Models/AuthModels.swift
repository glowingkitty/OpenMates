// Auth data models matching the backend Pydantic schemas.
// Used for login, lookup, session, and device verification flows.

import Foundation

// MARK: - Lookup

struct LookupRequest: Encodable {
    let hashedEmail: String
}

struct LookupResponse: Decodable {
    let availableLoginMethods: [LoginMethod]
    let tfaEnabled: Bool
    let tfaAppName: String?
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
    let tfaCode: String?
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
    let authSession: AuthSession?
    let needsDeviceVerification: Bool?
    let deviceVerificationType: String?
    let encryptedMasterKey: String?
    let keyIv: String?
    let userEmailSalt: String?
}

struct AuthSession: Decodable {
    let user: UserProfile
    let sessionId: String
}

// MARK: - Session check

struct SessionResponse: Decodable {
    let isAuthenticated: Bool
    let user: UserProfile?
    let authSession: AuthSession?
    let needsDeviceVerification: Bool?
    let deviceVerificationType: String?
}

// MARK: - User

struct UserProfile: Decodable, Identifiable {
    let id: String
    let username: String
    let credits: Double?
    let language: String?
    let darkmode: Bool?
    let timezone: String?
    let lastOpened: String?
}

// MARK: - Passkey

struct PasskeyAssertionInitResponse: Decodable {
    let challenge: String
    let rpId: String
    let timeout: Int?
    let userVerification: String?
    let allowCredentials: [PasskeyCredential]?
}

struct PasskeyCredential: Decodable {
    let id: String
    let type: String
}

struct PasskeyAssertionVerifyRequest: Encodable {
    let credentialId: String
    let assertionResponse: PasskeyAssertionData
    let sessionId: String?
    let stayLoggedIn: Bool
}

struct PasskeyAssertionData: Encodable {
    let authenticatorData: String
    let clientDataJSON: String
    let signature: String
    let userHandle: String?
}

struct PasskeyVerifyResponse: Decodable {
    let success: Bool
    let encryptedMasterKey: String?
    let keyIv: String?
    let userEmailSalt: String?
}

// MARK: - Device verification

struct DeviceVerifyRequest: Encodable {
    let code: String
}

struct DeviceVerifyResponse: Decodable {
    let success: Bool
}
