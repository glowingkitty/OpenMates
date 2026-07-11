// Account and security settings API contracts shared by native settings views.
// Endpoints and payloads mirror the Svelte settings implementations and backend
// Pydantic responses. This layer intentionally exposes failures to callers so
// settings views can render explicit loading, success, and error states.

import Foundation

actor AccountSecurityService {
    static let shared = AccountSecurityService()

    private let api = APIClient.shared

    private init() {}

    func authMethods() async throws -> AuthMethods {
        try await api.request(.get, path: "/v1/payments/user-auth-methods")
    }

    func passkeys() async throws -> [PasskeyRecord] {
        let response: PasskeyListResponse = try await api.request(.get, path: "/v1/auth/passkeys")
        guard response.success else { throw AccountSecurityError.server(response.message) }
        return response.passkeys
    }

    func renamePasskey(id: String, encryptedDeviceName: String) async throws {
        let response: ActionResponse = try await api.request(
            .post,
            path: "/v1/auth/passkeys/rename",
            body: PasskeyRenameRequest(passkeyId: id, encryptedDeviceName: encryptedDeviceName)
        )
        try requireSuccess(response)
    }

    func deletePasskey(id: String) async throws {
        let response: ActionResponse = try await api.request(
            .post,
            path: "/v1/auth/passkeys/delete",
            body: PasskeyDeleteRequest(passkeyId: id)
        )
        try requireSuccess(response)
    }

    func updatePassword(_ request: PasswordUpdateRequest) async throws {
        let response: ActionResponse = try await api.request(
            .post,
            path: "/v1/settings/update-password",
            body: request
        )
        try requireSuccess(response)
    }

    func verifyPasswordReauth(hashedEmail: String, lookupHash: String) async throws {
        let response: ActionResponse = try await api.request(
            .post,
            path: "/v1/settings/user/email/reauth",
            body: PasswordReauthRequest(
                authMethod: "password",
                authCode: "",
                hashedEmail: hashedEmail,
                lookupHash: lookupHash
            )
        )
        try requireSuccess(response)
    }

    func initiateTwoFactor(emailEncryptionKey: String) async throws -> TwoFactorSetupResponse {
        let response: TwoFactorSetupResponse = try await api.request(
            .post,
            path: "/v1/auth/2fa/setup/initiate",
            body: ["email_encryption_key": emailEncryptionKey]
        )
        guard response.success else { throw AccountSecurityError.server(response.message) }
        return response
    }

    func verifyTwoFactor(code: String) async throws {
        let response: ActionResponse = try await api.request(
            .post,
            path: "/v1/auth/2fa/setup/verify-signup",
            body: ["code": code]
        )
        try requireSuccess(response)
    }

    func setTwoFactorProvider(_ provider: String) async throws {
        let response: ActionResponse = try await api.request(
            .post,
            path: "/v1/auth/2fa/setup/provider",
            body: ["provider": provider]
        )
        try requireSuccess(response)
    }

    func requestBackupCodes(reset: Bool) async throws -> [String] {
        let response: BackupCodesResponse = try await api.request(
            reset ? .post : .get,
            path: reset
                ? "/v1/auth/2fa/setup/reset-backup-codes"
                : "/v1/auth/2fa/setup/request-backup-codes"
        )
        guard response.success else { throw AccountSecurityError.server(response.message) }
        return response.backupCodes ?? []
    }

    func confirmBackupCodesStored() async throws {
        let response: ActionResponse = try await api.request(
            .post,
            path: "/v1/auth/2fa/setup/confirm-codes-stored",
            body: ["confirmed": true]
        )
        try requireSuccess(response)
    }

    func regenerateRecoveryKey(_ request: RecoveryKeyUpdateRequest) async throws {
        let response: ActionResponse = try await api.request(
            .post,
            path: "/v1/auth/recovery-key/regenerate",
            body: request
        )
        try requireSuccess(response)
    }

    func sessions() async throws -> [AccountSession] {
        let response: SessionListResponse = try await api.request(.get, path: "/v1/auth/sessions")
        return response.sessions
    }

    func revokeSession(id: String) async throws {
        let response: ActionResponse = try await api.request(.delete, path: "/v1/auth/sessions/\(id)")
        try requireSuccess(response)
    }

    func logoutOtherSessions() async throws {
        let response: ActionResponse = try await api.request(.post, path: "/v1/auth/sessions/logout-others")
        try requireSuccess(response)
    }

    func logoutAllDevices() async throws {
        let response: ActionResponse = try await api.request(.post, path: "/v1/auth/sessions/logout-all-devices")
        try requireSuccess(response)
    }

    func chatCount() async throws -> Int {
        let response: ChatCountResponse = try await api.request(.get, path: "/v1/settings/chats")
        return response.totalCount
    }

    func previewChatDeletion(olderThanDays: Int) async throws -> Int {
        let response: ChatDeletePreviewResponse = try await api.request(
            .get,
            path: "/v1/settings/chats/preview?older_than_days=\(olderThanDays)"
        )
        return response.count
    }

    func deleteOldChats(olderThanDays: Int) async throws -> ChatDeleteResponse {
        try await api.request(
            .post,
            path: "/v1/settings/chats/delete-old",
            body: ["older_than_days": olderThanDays]
        )
    }

    func storageOverview() async throws -> StorageOverview {
        try await api.request(.get, path: "/v1/settings/storage")
    }

    func storageFiles(category: String) async throws -> [StorageFileRecord] {
        let escaped = category.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? category
        let response: StorageFilesResponse = try await api.request(
            .get,
            path: "/v1/settings/storage/files?category=\(escaped)"
        )
        return response.files
    }

    func deleteStorageFiles(ids: [String]) async throws -> Int {
        let response: StorageDeleteResponse = try await api.request(
            .delete,
            path: "/v1/settings/storage/files",
            body: ["file_ids": ids]
        )
        return response.deletedCount
    }

    func uploadProfileImage(_ jpegData: Data) async throws -> ProfileImageUploadResponse {
        let boundary = UUID().uuidString
        var body = Data()
        body.append(Data("--\(boundary)\r\n".utf8))
        body.append(Data("Content-Disposition: form-data; name=\"file\"; filename=\"profile.jpg\"\r\n".utf8))
        body.append(Data("Content-Type: image/jpeg\r\n\r\n".utf8))
        body.append(jpegData)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))

        let uploadBaseURL = await api.uploadBaseURL
        var request = URLRequest(url: uploadBaseURL.appendingPathComponent("v1/upload/profile-image"))
        request.httpMethod = "POST"
        request.httpBody = body
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.setValue((await api.webAppURL).absoluteString, forHTTPHeaderField: "Origin")
        APIClient.nativeClientHeaders.forEach { request.setValue($1, forHTTPHeaderField: $0) }

        let configuration = URLSessionConfiguration.default
        configuration.httpCookieStorage = OpenMatesSharedEnvironment.cookieStorage
        configuration.httpShouldSetCookies = true
        let (data, response) = try await URLSession(configuration: configuration).data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let decoded = try decoder.decode(ProfileImageUploadResponse.self, from: data)
        guard (200...299).contains(httpResponse.statusCode) else {
            throw AccountSecurityError.server(decoded.detail)
        }
        return decoded
    }

    func exportAccountData() async throws -> Data {
        let manifest = try await api.request(.get, path: "/v1/settings/export-account-manifest")
        let accountData = try await api.request(
            .get,
            path: "/v1/settings/export-account-data?include_usage=true&include_invoices=true&include_profile=true&include_settings=true"
        )
        let manifestObject = try JSONSerialization.jsonObject(with: manifest)
        let accountObject = try JSONSerialization.jsonObject(with: accountData)
        return try JSONSerialization.data(
            withJSONObject: ["manifest": manifestObject, "account": accountObject],
            options: [.prettyPrinted, .sortedKeys]
        )
    }

    private func requireSuccess(_ response: ActionResponse) throws {
        guard response.success else { throw AccountSecurityError.server(response.message) }
    }
}

struct ActionResponse: Decodable {
    let success: Bool
    let message: String?
}

struct AuthMethods: Decodable {
    let hasPasskey: Bool
    let hasPassword: Bool
    let has2Fa: Bool
    let hasRecoveryKey: Bool?
}

struct PasskeyListResponse: Decodable {
    let success: Bool
    let passkeys: [PasskeyRecord]
    let message: String?
}

struct PasskeyRecord: Identifiable, Decodable {
    let id: String
    let encryptedDeviceName: String?
    let registeredAt: String?
    let lastUsedAt: String?
    let signCount: Int
    let usageCount: Int
}

struct PasskeyRenameRequest: Encodable {
    let passkeyId: String
    let encryptedDeviceName: String
}

struct PasskeyDeleteRequest: Encodable {
    let passkeyId: String
}

struct PasswordUpdateRequest: Encodable {
    let hashedEmail: String
    let lookupHash: String
    let encryptedMasterKey: String
    let salt: String
    let keyIv: String
    let isNewPassword: Bool
}

struct PasswordReauthRequest: Encodable {
    let authMethod: String
    let authCode: String
    let hashedEmail: String
    let lookupHash: String
}

struct TwoFactorSetupResponse: Decodable {
    let success: Bool
    let message: String?
    let secret: String?
    let otpauthUrl: String?
}

struct BackupCodesResponse: Decodable {
    let success: Bool
    let message: String?
    let backupCodes: [String]?
}

struct RecoveryKeyUpdateRequest: Encodable {
    let newLookupHash: String
    let newWrappedMasterKey: String
    let newKeyIv: String
    let newSalt: String
}

struct SessionListResponse: Decodable {
    let sessions: [AccountSession]
}

struct AccountSession: Identifiable, Decodable {
    let sessionId: String
    let isCurrent: Bool
    let createdAt: Int
    let stayLoggedIn: Bool
    let encryptedMeta: String?
    let deviceName: String?
    let ipTruncated: String?
    let countryCode: String?
    let city: String?

    var id: String { sessionId }
}

struct ChatCountResponse: Decodable { let totalCount: Int }
struct ChatDeletePreviewResponse: Decodable { let count: Int }

struct ChatDeleteResponse: Decodable {
    let deletedCount: Int
    let deletedIds: [String]
}

struct StorageOverview: Decodable {
    let totalBytes: Int
    let totalFiles: Int
    let freeBytes: Int
    let billableGb: Double
    let creditsPerGbPerWeek: Double
    let weeklyCostCredits: Double
    let nextBillingDate: Int?
    let lastBilledAt: Int?
    let breakdown: [StorageCategoryRecord]
}

struct StorageCategoryRecord: Identifiable, Decodable {
    let category: String
    let bytesUsed: Int
    let fileCount: Int
    var id: String { category }
}

struct StorageFilesResponse: Decodable { let files: [StorageFileRecord] }

struct StorageFileRecord: Identifiable, Decodable {
    let id: String
    let filename: String?
    let sizeBytes: Int
    let createdAt: Int?
    let embedId: String
}

struct StorageDeleteResponse: Decodable { let deletedCount: Int }

struct ProfileImageUploadResponse: Decodable {
    let status: String
    let url: String?
    let rejectCount: Int?
    let detail: String?
}

enum AccountSecurityError: LocalizedError {
    case missingAccountData
    case server(String?)

    var errorDescription: String? {
        switch self {
        case .missingAccountData:
            return AppStrings.accountSecurityMissingData
        case .server(let message):
            return message ?? AppStrings.accountSecurityRequestFailed
        }
    }
}
