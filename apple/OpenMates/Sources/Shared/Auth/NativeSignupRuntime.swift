// Password signup contract shared by the live coordinator and deterministic tests.
// Source: auth schemas + current web PasswordBottomContent/cryptoService.
import CryptoKit
import Foundation
import Sodium

struct NativeSignupRequirements: Equatable {
    let requiresInvite: Bool
    let isSelfHosted: Bool
}
struct NativeSignupServerStatus: Decodable { let isSelfHosted: Bool }
struct NativeSignupInviteRequest: Encodable { let inviteCode: String }
struct NativeSignupInviteResponse: Decodable { let valid: Bool; let message: String }
struct NativeSignupUsernameRequest: Encodable { let username: String }
struct NativeSignupUsernameResponse: Decodable { let available: Bool; let message: String }
struct NativeSignupRequestEmail: Encodable, Equatable {
    let email: String
    let hashedEmail: String
    let inviteCode: String
    let language: String
    let darkmode: Bool
}
struct NativeSignupNewsletterRequest: Encodable { let email: String; let language: String; let darkmode: Bool }
struct NativeSignupConfirmEmail: Encodable, Equatable {
    let code: String
    let email: String
    let username: String
    let inviteCode: String
    let language: String
    let darkmode: Bool
}
struct NativeSignupActionResponse: Decodable {
    let success: Bool
    let message: String
    let errorCode: String?
}
struct NativeSignupPasswordRequest: Encodable, Equatable, Sendable {
    let hashedEmail: String
    let encryptedEmail: String
    let userEmailSalt: String
    let username: String
    let inviteCode: String
    let encryptedMasterKey: String
    let keyIv: String
    let salt: String
    let lookupHash: String
    let language: String
    let darkmode: Bool
    let pendingGiftCardCode: String?
}
struct NativeSignupPasswordResponse: Decodable {
    struct CreatedUser: Decodable { let id: String; let username: String }
    let success: Bool
    let message: String
    let user: CreatedUser?
}
struct NativeSignupPasswordMaterial: Sendable {
    let request: NativeSignupPasswordRequest
    let masterKey: SymmetricKey
}

// Authentication must prove the password login unwrapped the exact locally
// generated master key before it saves a key or activates the new account scope.
struct NativeSignupLoginProof {
    let serverProfile: ServerProfile
    let sessionId: String
    let expectedUserId: String?
    let masterKey: SymmetricKey
    let request: NativeSignupPasswordRequest

    func validates(_ response: LoginResponse) -> Bool {
        guard response.success, response.tfaRequired != true, response.needsDeviceVerification != true,
              let user = response.user else { return false }
        return (expectedUserId == nil || user.id == expectedUserId) &&
            user.encryptedKey == request.encryptedMasterKey && user.keyIv == request.keyIv &&
            user.salt == request.salt && user.userEmailSalt == request.userEmailSalt
    }
    func validatesMasterKey(_ actual: SymmetricKey) -> Bool {
        actual.withUnsafeBytes { Data($0) } == masterKey.withUnsafeBytes { Data($0) }
    }
}

enum NativeSignupError: Error, Equatable {
    case invalidForm, requirementsNotLoaded, alreadyAuthenticated, inviteRequired, invalidInvite
    case usernameUnavailable, emailRequestRejected, invalidEmailCode, verificationRequired
    case accountRejected, invalidAccountResponse, invalidCryptoMaterial, sessionProofMismatch
    case staleContext, creationUnconfirmed
    case passkeyUnsupported, passkeyCancelled, invalidPasskeyChallenge
}

@MainActor protocol NativeSignupRuntime {
    var supportsPasskey: Bool { get }
    func preparePasskey(form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws -> NativeSignupPasskeyMaterial
    func createPasskey(_ material: NativeSignupPasskeyMaterial) async throws -> String
    func finishPasskey(_ material: NativeSignupPasskeyMaterial, expectedUserID: String?, form: SignupBasicsForm) async throws
    func requirements() async throws -> NativeSignupRequirements
    func validateBasics(_ form: SignupBasicsForm, configuration: SignupBasicsConfiguration, requirements: NativeSignupRequirements) async throws
    func requestEmailCode(_ form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws
    func subscribeNewsletter(_ form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws
    func confirmEmail(_ code: String, form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws
    func preparePassword(_ password: String, form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws -> NativeSignupPasswordMaterial
    func createPassword(_ material: NativeSignupPasswordMaterial) async throws -> String
}

extension NativeSignupRuntime {
    // Existing password-only adapters remain explicit about their capability.
    var supportsPasskey: Bool { false }
    func preparePasskey(form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws -> NativeSignupPasskeyMaterial { throw NativeSignupError.passkeyUnsupported }
    func createPasskey(_ material: NativeSignupPasskeyMaterial) async throws -> String { throw NativeSignupError.passkeyUnsupported }
    func finishPasskey(_ material: NativeSignupPasskeyMaterial, expectedUserID: String?, form: SignupBasicsForm) async throws { throw NativeSignupError.passkeyUnsupported }
}

@MainActor final class NativeSignupLiveRuntime: NativeSignupRuntime {
    typealias Transport = @MainActor (HTTPMethod, String, Data?) async throws -> Data
    let serverProfile: ServerProfile
    private let sessionId: String
    private let transport: Transport
    private let contextIsCurrent: @MainActor () -> Bool
    private let crypto: CryptoManager
    private let passkeys: NativeSignupPasskeyRuntime?
    var supportsPasskey: Bool { passkeys?.isAvailable == true }

    init(serverProfile: ServerProfile, sessionId: String, crypto: CryptoManager = .shared,
         contextIsCurrent: @escaping @MainActor () -> Bool,
         transport: @escaping Transport, passkeys: NativeSignupPasskeyRuntime? = nil) {
        self.serverProfile = serverProfile
        self.sessionId = sessionId
        self.crypto = crypto
        self.contextIsCurrent = contextIsCurrent
        self.transport = transport
        self.passkeys = passkeys
    }
    static func live(serverProfile: ServerProfile, authManager: AuthManager) -> NativeSignupLiveRuntime {
        let sessionId = AuthManager.nativeSessionId
        let accountGeneration = OfflineStore.shared.scopeGeneration
        let current: @MainActor () -> Bool = {
            ServerProfile.current() == serverProfile && AuthManager.nativeSessionId == sessionId &&
                OfflineStore.shared.scopeGeneration == accountGeneration && authManager.currentUser == nil
        }
        let transport: Transport = { method, path, data in
            if let data {
                return try await APIClient.shared.request(method, path: path, serverProfile: serverProfile,
                    body: JSONRawBody(data: data))
            }
            return try await APIClient.shared.request(method, path: path, serverProfile: serverProfile)
        }
        let passkeys = NativeSignupPasskeyRuntime(profile: serverProfile, sessionID: sessionId,
            authorizer: NativeSignupPasskeyPlatform(), deviceName: AuthManager.makeNativeDeviceInfo().deviceModel,
            isCurrent: current, transport: transport, publish: { response, key, proof in
                try await authManager.completeNativePasskeySignup(response: response, masterKey: key,
                    proof: proof, contextIsCurrent: current)
            })
        return .init(serverProfile: serverProfile, sessionId: sessionId,
            contextIsCurrent: current, transport: transport, passkeys: passkeys)
    }
    func preparePasskey(form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws -> NativeSignupPasskeyMaterial {
        try validateContext()
        guard let passkeys else { throw NativeSignupError.passkeyUnsupported }
        return try await passkeys.prepare(form: form, configuration: configuration)
    }
    func createPasskey(_ material: NativeSignupPasskeyMaterial) async throws -> String {
        try validateContext()
        guard let passkeys else { throw NativeSignupError.passkeyUnsupported }
        return try await passkeys.create(material)
    }
    func finishPasskey(_ material: NativeSignupPasskeyMaterial, expectedUserID: String?, form: SignupBasicsForm) async throws {
        try validateContext()
        guard let passkeys else { throw NativeSignupError.passkeyUnsupported }
        try await passkeys.finish(material, expectedUserID: expectedUserID, form: form)
    }
    func requirements() async throws -> NativeSignupRequirements {
        let session: SessionResponse = try await post("/v1/auth/session", SessionRequest(sessionId: sessionId, deviceInfo: nil))
        guard session.user == nil, !session.isAuthenticated else { throw NativeSignupError.alreadyAuthenticated }
        guard let requiresInvite = session.requireInviteCode else { throw NativeSignupError.requirementsNotLoaded }
        let status: NativeSignupServerStatus = try await get("/v1/settings/server-status")
        return .init(requiresInvite: requiresInvite, isSelfHosted: status.isSelfHosted)
    }
    func validateBasics(_ form: SignupBasicsForm, configuration: SignupBasicsConfiguration, requirements: NativeSignupRequirements) async throws {
        guard form.canSubmit else { throw NativeSignupError.invalidForm }
        if requirements.requiresInvite {
            guard let invite = configuration.inviteCode, !invite.isEmpty else { throw NativeSignupError.inviteRequired }
            let response: NativeSignupInviteResponse = try await post("/v1/auth/check_invite_token_valid", NativeSignupInviteRequest(inviteCode: invite))
            guard response.valid else { throw NativeSignupError.invalidInvite }
        }
        let username: NativeSignupUsernameResponse = try await post("/v1/auth/check_username_valid", NativeSignupUsernameRequest(username: form.username))
        guard username.available else { throw NativeSignupError.usernameUnavailable }
    }
    func requestEmailCode(_ form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws {
        let hashedEmail = await crypto.hashEmail(form.email)
        let response: NativeSignupActionResponse = try await post("/v1/auth/request_confirm_email_code", NativeSignupRequestEmail(
            email: form.email, hashedEmail: hashedEmail, inviteCode: configuration.inviteCode ?? "",
            language: configuration.language, darkmode: configuration.darkmode))
        guard response.success else { throw NativeSignupError.emailRequestRejected }
        // Existing-account anti-enumeration can also return success. It means
        // only the request was accepted, never that this address is available.
    }
    func subscribeNewsletter(_ form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws {
        guard form.newsletter else { return }
        let response: NativeSignupActionResponse = try await post("/v1/newsletter/subscribe", NativeSignupNewsletterRequest(
            email: form.email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(),
            language: configuration.language, darkmode: configuration.darkmode))
        guard response.success else { throw NativeSignupError.emailRequestRejected }
    }
    func confirmEmail(_ code: String, form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws {
        guard code.count == 6, code.allSatisfy({ $0.isASCII && $0.isNumber }) else { throw NativeSignupError.invalidEmailCode }
        let response: NativeSignupActionResponse = try await post("/v1/auth/check_confirm_email_code", NativeSignupConfirmEmail(
            code: code, email: form.email, username: form.username, inviteCode: configuration.inviteCode ?? "",
            language: configuration.language, darkmode: configuration.darkmode))
        guard response.success else { throw NativeSignupError.invalidEmailCode }
    }
    func preparePassword(_ password: String, form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws -> NativeSignupPasswordMaterial {
        try validateContext()
        let material = try await crypto.prepareNativeSignupPassword(password, form: form, configuration: configuration)
        try validateContext()
        return material
    }
    func createPassword(_ material: NativeSignupPasswordMaterial) async throws -> String {
        let response: NativeSignupPasswordResponse = try await post("/v1/auth/setup_password", material.request)
        if !response.success {
            // Public status cannot expose the self-hosted domain mode. Follow
            // the web's initial skip, but honor this explicit backend guard.
            if response.message.hasPrefix("Email verification required.") { throw NativeSignupError.verificationRequired }
            throw NativeSignupError.accountRejected
        }
        guard let user = response.user, !user.id.isEmpty, user.username == material.request.username else {
            throw NativeSignupError.invalidAccountResponse
        }
        return user.id
    }
    private func validateContext() throws {
        guard contextIsCurrent(), !Task.isCancelled else { throw NativeSignupError.staleContext }
    }
    private func post<Body: Encodable, Response: Decodable>(_ path: String, _ body: Body) async throws -> Response {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return try await execute(.post, path: path, body: encoder.encode(body))
    }
    private func get<Response: Decodable>(_ path: String) async throws -> Response {
        try await execute(.get, path: path, body: nil)
    }
    private func execute<Response: Decodable>(_ method: HTTPMethod, path: String, body: Data?) async throws -> Response {
        try validateContext()
        let data = try await transport(method, path, body)
        try validateContext()
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Response.self, from: data)
    }
}

extension CryptoManager {
    // All new secrets/nonces use the established secure random source. Injected
    // bytes make interoperable vectors deterministic without persisting secrets.
    func prepareNativeSignupPassword(
        _ password: String, form: SignupBasicsForm, configuration: SignupBasicsConfiguration,
        random: @Sendable (Int) throws -> Data = { try SecureRandom.data(count: $0) }
    ) throws -> NativeSignupPasswordMaterial {
        guard form.canSubmit, NativeSignupPasswordPolicy.strengthErrorKey(for: password) == nil else {
            throw NativeSignupError.invalidForm
        }
        let masterBytes = try random(32)
        let wrappingSalt = try random(16)
        let emailSalt = try random(16)
        let keyIV = try random(12)
        let emailNonce = try random(24)
        guard masterBytes.count == 32, wrappingSalt.count == 16, emailSalt.count == 16,
              keyIV.count == 12, emailNonce.count == 24 else { throw NativeSignupError.invalidCryptoMaterial }
        let masterKey = SymmetricKey(data: masterBytes)
        let wrappingKey = try deriveWrappingKeyFromPassword(password: password, salt: wrappingSalt)
        let wrapped = try encrypt(masterBytes, using: wrappingKey, nonceData: keyIV)
        let emailKey = deriveEmailEncryptionKey(email: form.email, salt: emailSalt)
        guard let sealed = Sodium().secretBox.seal(message: Array(form.email.utf8), secretKey: Array(emailKey), nonce: Array(emailNonce)) else {
            throw NativeSignupError.invalidCryptoMaterial
        }
        return .init(request: NativeSignupPasswordRequest(
            hashedEmail: hashEmail(form.email), encryptedEmail: (emailNonce + Data(sealed)).base64EncodedString(),
            userEmailSalt: emailSalt.base64EncodedString(), username: form.username,
            inviteCode: configuration.inviteCode ?? "", encryptedMasterKey: wrapped.ciphertext.base64EncodedString(),
            keyIv: wrapped.nonce.base64EncodedString(), salt: wrappingSalt.base64EncodedString(),
            lookupHash: hashKey(password, salt: emailSalt), language: configuration.language,
            darkmode: configuration.darkmode, pendingGiftCardCode: nil), masterKey: masterKey)
    }
}
