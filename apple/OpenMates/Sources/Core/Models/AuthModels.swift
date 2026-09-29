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
    var lookupHash: String?
    let loginMethod: String
    var credentialId: String? = nil
    let tfaCode: String?
    let codeType: String?
    let emailEncryptionKey: String?
    let stayLoggedIn: Bool
    let sessionId: String?
    let deviceInfo: DeviceInfo?
    var credentialVersion: Int? = nil
    var challengeId: String? = nil
    var passwordProof: String? = nil
}

struct PasswordV2ChallengeRequest: Encodable {
    let hashedEmail: String
    let sessionId: String
    let purpose: String
}

struct PasswordV2ChallengeResponse: Decodable {
    let challengeId: String
    let nonce: String
    let expiresIn: Int
}

struct PasswordV2MigrationRequest: Encodable {
    let oldLookupHash: String
    let passwordAuthKey: String
    let encryptedMasterKey: String
    let salt: String
    let keyIv: String
}

struct PasswordV2MigrationCapabilities: Decodable {
    let stagedProtocol: Int
    let confirmRequired: Bool
}

struct PasswordV2MigrationStatus: Decodable {
    let success: Bool
    let migrationStatus: String
    let legacyPasswordRetained: Bool
}

struct PasswordV2StagedProofRequest: Encodable {
    let challengeId: String
    let passwordProof: String
}

struct PasswordV2StagedWrapper: Decodable {
    let encryptedKey: String
    let salt: String
    let keyIv: String
    let credentialVersion: Int
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
    let pairExpiresAt: Int?
}

// MARK: - PAKE pair login v2

struct PairV2InitiateRequest: Encodable {
    let receiverTokenHash: String
    let sessionId: String
    let deviceHint: String?
}

struct PairV2InitiateResponse: Decodable {
    let protocolVersion: Int
    let token: String
    let expiresAt: Int
}

struct PairV2InfoResponse: Decodable {
    let protocolVersion: Int
    let sessionId: String
    let receiverTokenHash: String
    let deviceName: String?
    let ipTruncated: String?
    let countryCode: String?
    let city: String?
    let createdAt: Int
    let expiresAt: Int
}

struct PairV2ApproveRequest: Encodable {
    let authorizerDeviceName: String
    let autoLogoutMinutes: Int?
}

struct PairV2ApproveResponse: Decodable {
    let success: Bool
    let protocolVersion: Int
    let token: String
    let sessionId: String
    let receiverTokenHash: String
    let authorizerUserId: String
    let autoLogoutMinutes: Int?
    let expiresAt: Int
}

struct PairV2ReceiverPoll: Decodable {
    let status: String
    let expiresAt: Int
    let authorizerUserId: String?
    let authorizerDeviceName: String?
    let autoLogoutMinutes: Int?
    let sessionId: String?
    let receiverTokenHash: String?
    let message: String?
    let encryptedBundle: String?
    let iv: String?
}

struct PairV2AuthorizerPoll: Decodable {
    let status: String
    let expiresAt: Int
    let receiverRequest: String?
    let receiverFinish: String?
}

struct PairV2MessageRequest: Encodable {
    let stage: String
    let message: String
}

struct PairV2BundleRequest: Encodable {
    let encryptedBundle: String
    let iv: String
    let grantHash: String
}

struct PairV2CompleteRequest: Encodable {
    let grantSecret: String
}

struct PairV2StepUpRequest: Encodable {
    let authMethod: String
    let hashedEmail: String?
    let lookupHash: String?
    let authCode: String?
}

struct PairV2StepUpResponse: Decodable {
    let success: Bool
    let expiresIn: Int
}

struct PairV2StepUpMethods: Decodable {
    let hasPasskey: Bool
    let hasPassword: Bool
    let has2Fa: Bool

    private enum CodingKeys: String, CodingKey {
        case hasPasskey
        case hasPassword
        case has2Fa = "has2fa"
    }

    enum Method { case passkey, password, otp }

    func supports(_ method: Method) -> Bool {
        switch method {
        case .passkey: return hasPasskey
        case .password: return hasPassword
        case .otp: return has2Fa
        }
    }
}

struct PairV2Bundle: Decodable {
    let protocolVersion: Int
    let masterKeyExported: String
    let grantSecret: String
    let userEmailSalt: String
    let hashedEmail: String
    let userId: String
    let accountContext: PairV2AccountContext
}

struct PairV2AccountContext: Codable {
    let encryptedEmailWithMasterKey: String
}

struct PairV2AccountCheck: Decodable {
    let userId: String
    let hashedEmail: String
    let encryptedEmailWithMasterKey: String
    let userEmailSalt: String
}

// MARK: - Session check

struct SessionRequest: Encodable {
    let sessionId: String
    let deviceInfo: DeviceInfo?
}

struct SessionResponse: Decodable {
    let success: Bool
    let message: String?
    let user: UserProfile?
    let tokenRefreshNeeded: Bool?
    let reAuthRequired: String?
    let reAuthReason: String?
    let requireInviteCode: Bool?
    let wsToken: String?
    let needsDeviceVerification: Bool?
    let deviceVerificationType: String?

    var isAuthenticated: Bool {
        success && user != nil
    }
}

// MARK: - User

struct UserProfile: Codable, Identifiable {
    let id: String
    let username: String
    let email: String?
    let credits: Double?
    let language: String?
    let darkmode: Bool?
    let timezone: String?
    var lastOpened: String?
    let profileImageUrl: String?
    let isAdmin: Bool?

    // E2EE crypto fields — returned by server on login and session check
    var encryptedKey: String?   // Versioned client-wrapped master key (base64)
    var keyIv: String?          // 12-byte IV for master key wrapping (base64)
    var salt: String?           // Versioned wrapper salt (base64)
    let userEmailSalt: String?  // Salt for email encryption key derivation
    var credentialVersion: Int? = nil

    // Settings fields synced from server
    let encryptedSettings: String?
    let autoDeleteChatsAfterDays: Int?
    let pushNotificationEnabled: Bool?
    let emailNotificationsEnabled: Bool?
    let emailNotificationPreferences: [String: Bool]?
    let backupReminderIntervalDays: Int?
    let defaultAiModelSimple: String?
    let defaultAiModelComplex: String?
    let followUpSuggestionsEnabled: Bool?
    let quickTipsEnabled: Bool?
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
