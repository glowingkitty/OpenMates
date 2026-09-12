// Native passkey signup protocol. Web: signup/steps/secureaccount/
// SecureAccountTopContent.svelte, cryptoService.getPRFSignatureForPasskeyRegistration,
// deriveWrappingKeyFromPRF/hashKeyFromPRF; backend auth_passkey.py + schemas/auth.py.
// No credential, PRF output, plaintext or encrypted payload is logged/persisted here.
import CryptoKit
import Foundation
import Sodium

struct NativeSignupPasskeyOptions: Decodable {
    struct User: Decodable { let id: String; let name: String; let displayName: String }
    struct Parameter: Decodable { let type: String; let alg: Int }
    struct Selection: Decodable { let residentKey: String?; let userVerification: String? }
    let success: Bool
    let challenge: String
    let rp: PasskeyRelyingParty
    let user: User
    let pubKeyCredParams: [Parameter]
    let authenticatorSelection: Selection
    let extensions: PasskeyAssertionExtensions?
    let timeout: Int?
    let attestation: String?
    let message: String?
}
struct NativePasskeyRegistrationResult: Sendable {
    let credentialID: Data
    let clientDataJSON: Data
    let attestationObject: Data
    let prfOutput: Data?
    let supportsPRF: Bool?
}
struct NativePasskeyAssertionResult: Sendable {
    let credentialID: Data
    let clientDataJSON: Data
    let authenticatorData: Data
    let signature: Data
    let userHandle: Data?
    let prfOutput: Data?
}
@MainActor protocol NativeSignupPasskeyAuthorizer {
    var isAvailable: Bool { get }
    func register(options: NativeSignupPasskeyOptions, challenge: Data, userID: Data, prfSalt: Data) async throws -> NativePasskeyRegistrationResult
    func assert(rpID: String, challenge: Data, credentialID: Data, prfSalt: Data) async throws -> NativePasskeyAssertionResult
}

struct NativeSignupPasskeyRequest: Equatable, Sendable {
    let credentialId: String
    let attestationObject: String
    let clientDataJSON: String
    let authenticatorData: String
    let hashedEmail: String
    let username: String
    let inviteCode: String
    let encryptedEmail: String
    let encryptedEmailWithMasterKey: String
    let encryptedDeviceName: String
    let userEmailSalt: String
    let encryptedMasterKey: String
    let keyIv: String
    let lookupHash: String
    let language: String
    let darkmode: Bool

    // Outer API keys are snake_case; WebAuthn's nested keys must stay camelCase.
    // A global JSONEncoder.convertToSnakeCase would corrupt attestationObject.
    func wireData() throws -> Data {
        try JSONSerialization.data(withJSONObject: [
            "credential_id": credentialId,
            "attestation_response": ["attestationObject": attestationObject, "publicKey": [:] as [String: String]],
            "client_data_json": clientDataJSON, "authenticator_data": authenticatorData,
            "hashed_email": hashedEmail, "username": username, "invite_code": inviteCode,
            "encrypted_email": encryptedEmail, "encrypted_email_with_master_key": encryptedEmailWithMasterKey,
            "encrypted_device_name": encryptedDeviceName, "user_email_salt": userEmailSalt,
            "encrypted_master_key": encryptedMasterKey, "key_iv": keyIv, "salt": userEmailSalt,
            "lookup_hash": lookupHash, "language": language, "darkmode": darkmode, "prf_enabled": true,
            "user_id": NSNull(), "pending_gift_card_code": NSNull()
        ], options: [.sortedKeys])
    }
    var proofRequest: NativeSignupPasswordRequest {
        .init(hashedEmail: hashedEmail, encryptedEmail: encryptedEmail, userEmailSalt: userEmailSalt,
            username: username, inviteCode: inviteCode, encryptedMasterKey: encryptedMasterKey,
            keyIv: keyIv, salt: userEmailSalt, lookupHash: lookupHash, language: language,
            darkmode: darkmode, pendingGiftCardCode: nil)
    }
}
struct NativeSignupPasskeyMaterial: Sendable {
    let request: NativeSignupPasskeyRequest
    let masterKey: SymmetricKey
}
private struct NativeSignupPasskeyResponse: Decodable {
    struct User: Decodable { let id: String; let username: String? }
    let success: Bool
    let message: String
    let user: User?
}

@MainActor final class NativeSignupPasskeyRuntime {
    typealias Publish = @MainActor (LoginResponse, SymmetricKey, NativeSignupLoginProof) async throws -> Void
    private let profile: ServerProfile
    private let sessionID: String
    private let authorizer: any NativeSignupPasskeyAuthorizer
    private let transport: NativeSignupLiveRuntime.Transport
    private let isCurrent: @MainActor () -> Bool
    private let publish: Publish
    private let deviceName: String
    var isAvailable: Bool { authorizer.isAvailable }

    init(profile: ServerProfile, sessionID: String, authorizer: any NativeSignupPasskeyAuthorizer,
         deviceName: String, isCurrent: @escaping @MainActor () -> Bool,
         transport: @escaping NativeSignupLiveRuntime.Transport, publish: @escaping Publish) {
        self.profile = profile; self.sessionID = sessionID; self.authorizer = authorizer
        self.deviceName = deviceName; self.isCurrent = isCurrent; self.transport = transport; self.publish = publish
    }
    func prepare(form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws -> NativeSignupPasskeyMaterial {
        try checkOwner()
        guard authorizer.isAvailable else { throw NativeSignupError.passkeyUnsupported }
        guard form.canSubmit else { throw NativeSignupError.invalidForm }
        let hashedEmail = await CryptoManager.shared.hashEmail(form.email)
        let options: NativeSignupPasskeyOptions = try await exchange("/v1/auth/passkey/registration/initiate", data:
            JSONSerialization.data(withJSONObject: ["hashed_email": hashedEmail, "user_id": NSNull(), "username": form.username]))
        guard options.success else { throw NativeSignupError.accountRejected }
        let challenge = try NativePasskeyValidation.challenge(options.challenge)
        let prfSalt = try NativePasskeyValidation.prfSalt(rpID: options.rp.id, extensions: options.extensions, profile: profile)
        guard let userID = Data(base64URLEncoded: options.user.id), userID == Data(base64Encoded: hashedEmail),
              options.user.name == form.username, options.user.displayName == form.username,
              options.pubKeyCredParams.contains(where: { $0.type == "public-key" && $0.alg == -7 }),
              options.authenticatorSelection.userVerification == "required",
              options.authenticatorSelection.residentKey == "required" else { throw NativeSignupError.invalidPasskeyChallenge }
        let registration = try await authorizer.register(options: options, challenge: challenge, userID: userID, prfSalt: prfSalt)
        try checkOwner()
        try NativePasskeyValidation.clientData(registration.clientDataJSON, type: "webauthn.create", challenge: challenge, profile: profile)
        let authenticatorData = try NativePasskeyValidation.registrationAuthenticatorData(registration, rpID: options.rp.id)
        let prf: Data
        if let output = registration.prfOutput {
            prf = try NativePasskeyValidation.prf(output)
        } else {
            guard registration.supportsPRF != false else { throw NativeSignupError.passkeyUnsupported }
            // Some authenticators evaluate PRF only during get(). Keep the exact
            // newly-created credential and original salt/challenge in that request.
            let fallback = try await authorizer.assert(rpID: options.rp.id, challenge: challenge,
                credentialID: registration.credentialID, prfSalt: prfSalt)
            try checkOwner()
            try NativePasskeyValidation.assertion(fallback, credentialID: registration.credentialID,
                userID: userID, challenge: challenge, profile: profile)
            prf = try NativePasskeyValidation.prf(fallback.prfOutput)
        }
        let material = try await CryptoManager.shared.prepareNativeSignupPasskey(registration: registration,
            authenticatorData: authenticatorData, prf: prf, form: form, configuration: configuration, deviceName: deviceName)
        try checkOwner()
        return material
    }
    func create(_ material: NativeSignupPasskeyMaterial) async throws -> String {
        let response: NativeSignupPasskeyResponse = try await exchange("/v1/auth/passkey/registration/complete", data: material.request.wireData())
        if !response.success {
            // This explicit backend condition is evaluated BEFORE create_user.
            if response.message.hasPrefix("Email verification required.") { throw NativeSignupError.verificationRequired }
            throw NativeSignupError.creationUnconfirmed
        }
        guard let user = response.user, !user.id.isEmpty,
              user.username == nil || user.username == material.request.username else { throw NativeSignupError.invalidAccountResponse }
        return user.id
    }
    func finish(_ material: NativeSignupPasskeyMaterial, expectedUserID: String?, form: SignupBasicsForm) async throws {
        try checkOwner()
        let options: PasskeyAssertionInitResponse = try await exchange("/v1/auth/passkey/assertion/initiate", data:
            JSONSerialization.data(withJSONObject: ["hashed_email": material.request.hashedEmail]))
        guard options.success, let credentialID = Data(base64URLEncoded: material.request.credentialId),
              let registeredUserID = Data(base64Encoded: material.request.hashedEmail) else { throw NativeSignupError.sessionProofMismatch }
        let challenge = try NativePasskeyValidation.challenge(options.challenge)
        let prfSalt = try NativePasskeyValidation.prfSalt(rpID: options.rp.id, extensions: options.extensions, profile: profile)
        if let allowed = options.allowCredentials, !allowed.isEmpty {
            guard allowed.contains(where: { $0.type == "public-key" && Data(base64URLEncoded: $0.id) == credentialID }) else { throw NativeSignupError.sessionProofMismatch }
        }
        let assertion = try await authorizer.assert(rpID: options.rp.id, challenge: challenge, credentialID: credentialID, prfSalt: prfSalt)
        try checkOwner()
        try NativePasskeyValidation.assertion(assertion, credentialID: credentialID, userID: registeredUserID, challenge: challenge, profile: profile)
        let prf = try NativePasskeyValidation.prf(assertion.prfOutput)
        let clientData = assertion.clientDataJSON.base64EncodedString()
        let authData = assertion.authenticatorData.base64EncodedString()
        let wire = try JSONSerialization.data(withJSONObject: [
            "credential_id": material.request.credentialId,
            "assertion_response": ["authenticatorData": authData, "clientDataJSON": clientData,
                "signature": assertion.signature.base64EncodedString(), "userHandle": assertion.userHandle?.base64EncodedString() as Any? ?? NSNull()],
            "client_data_json": clientData, "authenticator_data": authData,
            "session_id": sessionID, "stay_logged_in": form.stayLoggedIn,
            "hashed_email": material.request.hashedEmail, "email_encryption_key": NSNull()
        ])
        let verified: PasskeyVerifyResponse = try await exchange("/v1/auth/passkey/assertion/verify", data: wire)
        guard verified.success, let userID = verified.userId, !userID.isEmpty,
              expectedUserID == nil || userID == expectedUserID,
              verified.hashedEmail == material.request.hashedEmail,
              verified.encryptedMasterKey == material.request.encryptedMasterKey,
              verified.keyIv == material.request.keyIv,
              verified.userEmailSalt == material.request.userEmailSalt,
              verified.encryptedEmail == material.request.encryptedEmailWithMasterKey,
              let emailSalt = Data(base64Encoded: material.request.userEmailSalt) else { throw NativeSignupError.sessionProofMismatch }
        let crypto = CryptoManager.shared
        let wrappingKey = await crypto.deriveWrappingKeyFromPRF(prfSignature: prf, emailSalt: emailSalt)
        let masterKey = try await crypto.unwrapMasterKey(wrappedKeyBase64: material.request.encryptedMasterKey,
            ivBase64: material.request.keyIv, wrappingKey: wrappingKey)
        guard masterKey.withUnsafeBytes({ Data($0) }) == material.masterKey.withUnsafeBytes({ Data($0) }),
              try await crypto.decryptContent(base64String: material.request.encryptedEmailWithMasterKey, key: masterKey) == form.email else {
            throw NativeSignupError.sessionProofMismatch
        }
        try checkOwner()
        let login = LoginRequest(hashedEmail: material.request.hashedEmail,
            lookupHash: await crypto.hashKeyFromPRF(prfSignature: prf, emailSalt: emailSalt), loginMethod: "passkey",
            credentialId: material.request.credentialId, tfaCode: nil, codeType: nil,
            emailEncryptionKey: await crypto.deriveEmailEncryptionKey(email: form.email, salt: emailSalt).base64EncodedString(),
            stayLoggedIn: form.stayLoggedIn, sessionId: sessionID, deviceInfo: AuthManager.makeNativeDeviceInfo())
        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
        let response: LoginResponse = try await exchange("/v1/auth/login", data: encoder.encode(login))
        let proof = NativeSignupLoginProof(serverProfile: profile, sessionId: sessionID, expectedUserId: userID,
            masterKey: material.masterKey, request: material.request.proofRequest)
        guard proof.validates(response), proof.validatesMasterKey(masterKey) else { throw NativeSignupError.sessionProofMismatch }
        try checkOwner()
        try await publish(response, masterKey, proof)
        // Publication owns its own final generation checks. Its successful state
        // intentionally changes the unauthenticated context captured by isCurrent.
    }
    private func checkOwner() throws {
        guard isCurrent(), !Task.isCancelled else { throw NativeSignupError.staleContext }
    }
    private func exchange<Response: Decodable>(_ path: String, data: Data) async throws -> Response {
        try checkOwner()
        let response = try await transport(.post, path, data)
        try checkOwner()
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Response.self, from: response)
    }
}

extension CryptoManager {
    func prepareNativeSignupPasskey(registration: NativePasskeyRegistrationResult, authenticatorData: Data,
        prf: Data, form: SignupBasicsForm, configuration: SignupBasicsConfiguration, deviceName: String,
        random: @Sendable (Int) throws -> Data = { try SecureRandom.data(count: $0) }) throws -> NativeSignupPasskeyMaterial {
        guard form.canSubmit, prf.count == 32 else { throw NativeSignupError.invalidCryptoMaterial }
        let master = try random(32), salt = try random(16), iv = try random(12), emailNonce = try random(24)
        let emailIV = try random(12), deviceIV = try random(12)
        guard master.count == 32, salt.count == 16, iv.count == 12, emailNonce.count == 24,
              emailIV.count == 12, deviceIV.count == 12 else { throw NativeSignupError.invalidCryptoMaterial }
        let masterKey = SymmetricKey(data: master)
        let wrappingKey = deriveWrappingKeyFromPRF(prfSignature: prf, emailSalt: salt)
        let wrapped = try encrypt(master, using: wrappingKey, nonceData: iv)
        let emailKey = deriveEmailEncryptionKey(email: form.email, salt: salt)
        guard let emailSealed = Sodium().secretBox.seal(message: Array(form.email.utf8), secretKey: Array(emailKey), nonce: Array(emailNonce)) else { throw NativeSignupError.invalidCryptoMaterial }
        let email = try encrypt(Data(form.email.utf8), using: masterKey, nonceData: emailIV)
        let device = try encrypt(Data(deviceName.utf8), using: masterKey, nonceData: deviceIV)
        return .init(request: .init(credentialId: registration.credentialID.base64URLEncodedString(),
            attestationObject: registration.attestationObject.base64EncodedString(), clientDataJSON: registration.clientDataJSON.base64EncodedString(),
            authenticatorData: authenticatorData.base64EncodedString(), hashedEmail: hashEmail(form.email),
            username: form.username, inviteCode: configuration.inviteCode ?? "",
            encryptedEmail: (emailNonce + Data(emailSealed)).base64EncodedString(),
            encryptedEmailWithMasterKey: (email.nonce + email.ciphertext).base64EncodedString(),
            encryptedDeviceName: (device.nonce + device.ciphertext).base64EncodedString(),
            userEmailSalt: salt.base64EncodedString(), encryptedMasterKey: wrapped.ciphertext.base64EncodedString(),
            keyIv: wrapped.nonce.base64EncodedString(), lookupHash: hashKeyFromPRF(prfSignature: prf, emailSalt: salt),
            language: configuration.language, darkmode: configuration.darkmode), masterKey: masterKey)
    }
}
