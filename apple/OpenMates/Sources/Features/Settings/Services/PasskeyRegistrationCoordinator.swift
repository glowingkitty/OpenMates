// Native passkey registration for an existing encrypted OpenMates account.
// The server challenge, AuthenticationServices prompt, PRF output, wrapping-key
// derivation, and completion payload mirror SettingsPasskeys.svelte. The only
// platform-owned UI in this flow is the passkey authorization prompt.

import AuthenticationServices
import CryptoKit
import Foundation
import ObjectiveC

@MainActor
enum PasskeyRegistrationCoordinator {
    static func register(user: UserProfile, deviceName: String) async throws {
        guard let email = user.email,
              let saltBase64 = user.userEmailSalt,
              let emailSalt = Data(base64Encoded: saltBase64),
              let masterKey = try await CryptoManager.shared.loadMasterKey(for: user.id)
        else {
            throw AccountSecurityError.missingAccountData
        }

        let hashedEmail = await CryptoManager.shared.hashEmail(email)
        let options: PasskeyRegistrationOptions = try await APIClient.shared.request(
            .post,
            path: "/v1/auth/passkey/registration/initiate",
            body: PasskeyRegistrationInitiateRequest(
                hashedEmail: hashedEmail,
                userId: "current",
                username: user.username
            )
        )
        guard options.success else { throw AccountSecurityError.server(options.message) }

        let result = try await authorize(options: options)
        let wrappingKey = await CryptoManager.shared.deriveWrappingKeyFromPRF(
            prfSignature: result.prfSignature,
            emailSalt: emailSalt
        )
        let wrapped = try await CryptoManager.shared.encrypt(
            masterKey.withUnsafeBytes { Data($0) },
            using: wrappingKey
        )
        let lookupHash = await CryptoManager.shared.hashKeyFromPRF(
            prfSignature: result.prfSignature,
            emailSalt: emailSalt
        )
        let encryptedEmail = try await CryptoManager.shared.encryptWithMasterKey(email, masterKey: masterKey)
        let encryptedDeviceName = try await CryptoManager.shared.encryptWithMasterKey(deviceName, masterKey: masterKey)

        let response: ActionResponse = try await APIClient.shared.request(
            .post,
            path: "/v1/auth/passkey/registration/complete",
            body: PasskeyRegistrationCompleteRequest(
                credentialId: result.credentialId,
                attestationResponse: .init(
                    attestationObject: result.attestationObject.base64EncodedString(),
                    publicKey: [:]
                ),
                clientDataJson: result.clientDataJSON.base64EncodedString(),
                authenticatorData: Data(result.attestationObject.prefix(37)).base64EncodedString(),
                hashedEmail: hashedEmail,
                username: user.username,
                inviteCode: "",
                encryptedEmail: "",
                encryptedEmailWithMasterKey: encryptedEmail,
                encryptedDeviceName: encryptedDeviceName,
                userEmailSalt: emailSalt.base64EncodedString(),
                encryptedMasterKey: wrapped.ciphertext.base64EncodedString(),
                keyIv: wrapped.nonce.base64EncodedString(),
                salt: emailSalt.base64EncodedString(),
                lookupHash: lookupHash,
                language: user.language ?? "en",
                darkmode: user.darkmode ?? false,
                prfEnabled: true,
                userId: "current"
            )
        )
        guard response.success else { throw AccountSecurityError.server(response.message) }
    }

    private static func authorize(options: PasskeyRegistrationOptions) async throws -> RegistrationResult {
        try await withCheckedThrowingContinuation { continuation in
            guard let challenge = Data(base64URLEncoded: options.challenge),
                  let userId = Data(base64URLEncoded: options.user.id)
            else {
                continuation.resume(throwing: PasskeyRegistrationError.invalidChallenge)
                return
            }

            let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(
                relyingPartyIdentifier: options.rp.id
            )
            let request = provider.createCredentialRegistrationRequest(
                challenge: challenge,
                name: options.user.name,
                userID: userId
            )
            if #available(iOS 18.0, macOS 15.0, *),
               let prfSalt = options.extensions?.prf?.eval?.first.flatMap(Data.init(base64URLEncoded:)) {
                request.prf = .inputValues(.saltInput1(prfSalt))
            }

            let controller = ASAuthorizationController(authorizationRequests: [request])
            let delegate = RegistrationDelegate(
                continuation: continuation,
                invalidCredentialError: PasskeyRegistrationError.invalidCredential,
                missingPRFError: PasskeyRegistrationError.missingPRF
            )
            controller.delegate = delegate
            controller.presentationContextProvider = delegate
            objc_setAssociatedObject(controller, &RegistrationAssociatedKeys.delegate, delegate, .OBJC_ASSOCIATION_RETAIN)
            controller.performRequests()
        }
    }
}

private struct PasskeyRegistrationInitiateRequest: Encodable {
    let hashedEmail: String
    let userId: String
    let username: String
}

private struct PasskeyRegistrationOptions: Decodable {
    let success: Bool
    let challenge: String
    let rp: PasskeyRelyingParty
    let user: RegistrationUser
    let extensions: PasskeyAssertionExtensions?
    let message: String?
}

private struct RegistrationUser: Decodable {
    let id: String
    let name: String
    let displayName: String
}

private struct PasskeyRegistrationCompleteRequest: Encodable {
    struct AttestationResponse: Encodable {
        let attestationObject: String
        let publicKey: [String: String]
    }

    let credentialId: String
    let attestationResponse: AttestationResponse
    let clientDataJson: String
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
    let salt: String
    let lookupHash: String
    let language: String
    let darkmode: Bool
    let prfEnabled: Bool
    let userId: String
}

private struct RegistrationResult {
    let credentialId: String
    let clientDataJSON: Data
    let attestationObject: Data
    let prfSignature: Data
}

private enum RegistrationAssociatedKeys {
    nonisolated(unsafe) static var delegate: UInt8 = 0
}

private final class RegistrationDelegate: NSObject, ASAuthorizationControllerDelegate,
                                           ASAuthorizationControllerPresentationContextProviding {
    let continuation: CheckedContinuation<RegistrationResult, Error>
    let invalidCredentialError: PasskeyRegistrationError
    let missingPRFError: PasskeyRegistrationError

    init(
        continuation: CheckedContinuation<RegistrationResult, Error>,
        invalidCredentialError: PasskeyRegistrationError,
        missingPRFError: PasskeyRegistrationError
    ) {
        self.continuation = continuation
        self.invalidCredentialError = invalidCredentialError
        self.missingPRFError = missingPRFError
    }

    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithAuthorization authorization: ASAuthorization
    ) {
        guard let credential = authorization.credential
            as? ASAuthorizationPlatformPublicKeyCredentialRegistration,
              let attestation = credential.rawAttestationObject
        else {
            continuation.resume(throwing: invalidCredentialError)
            return
        }
        guard #available(iOS 18.0, macOS 15.0, *),
              let prf = credential.prf?.first?.withUnsafeBytes({ Data($0) })
        else {
            continuation.resume(throwing: missingPRFError)
            return
        }
        continuation.resume(returning: RegistrationResult(
            credentialId: credential.credentialID.base64URLEncodedString(),
            clientDataJSON: credential.rawClientDataJSON,
            attestationObject: attestation,
            prfSignature: prf
        ))
    }

    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithError error: Error
    ) {
        continuation.resume(throwing: error)
    }

    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        #if os(iOS)
        return UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap(\.windows)
            .first { $0.isKeyWindow } ?? ASPresentationAnchor()
        #elseif os(macOS)
        return NSApplication.shared.keyWindow ?? ASPresentationAnchor()
        #endif
    }
}

private struct PasskeyRegistrationError: LocalizedError {
    let errorDescription: String?

    @MainActor static var invalidChallenge: Self { .init(errorDescription: AppStrings.passkeyInvalidChallenge) }
    @MainActor static var invalidCredential: Self { .init(errorDescription: AppStrings.passkeyRegistrationFailed) }
    @MainActor static var missingPRF: Self { .init(errorDescription: AppStrings.passkeyPRFRequired) }
}
