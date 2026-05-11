// Native passkey login using ASAuthorizationController.
// Mirrors Login.svelte's passkey loading state and immediate WebAuthn start.
// Uses the PRF extension for zero-knowledge master-key unwrapping, then
// completes the same /auth/login session path as the web app.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/Login.svelte
//          frontend/packages/ui/src/components/EmailLookup.svelte
// CSS:     frontend/packages/ui/src/styles/auth.css
//          .passkey-loading-screen, .passkey-loading-text
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import AuthenticationServices
import CryptoKit

struct PasskeyLoginView: View {
    @EnvironmentObject var authManager: AuthManager
    let email: String
    @Binding var stayLoggedIn: Bool

    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var didStart = false

    var body: some View {
        VStack(spacing: .spacing8) {
            Icon("passkey", size: 64)
                .foregroundStyle(LinearGradient.primary)
                .accessibilityHidden(true)

            Text(LocalizationManager.shared.text("login.logging_in_with_passkey"))
                .font(.omP)
                .fontWeight(.medium)
                .foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)

            if let errorMessage {
                Text(errorMessage)
                    .font(.omXs)
                    .foregroundStyle(Color.error)
                    .multilineTextAlignment(.center)
            }

            Button(action: { startPasskeyLogin(preferImmediatelyAvailableCredentials: false) }) {
                Group {
                    if isLoading {
                        ProgressView()
                            .tint(.fontButton)
                    } else {
                        HStack(spacing: .spacing2) {
                            Icon("passkey", size: 16)
                            Text(LocalizationManager.shared.text("login.login_with_passkey"))
                        }
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(isLoading)
            .opacity(errorMessage == nil ? 0 : 1)
            .accessibleButton(
                LocalizationManager.shared.text("login.login_with_passkey"),
                hint: LocalizationManager.shared.text("login.login_with_passkey")
            )
        }
        .padding(.vertical, .spacing20)
        .task {
            guard !didStart else { return }
            didStart = true
            startPasskeyLogin(preferImmediatelyAvailableCredentials: false)
        }
    }

    private func startPasskeyLogin(preferImmediatelyAvailableCredentials: Bool) {
        isLoading = true
        errorMessage = nil

        Task {
            do {
                try await PasskeyLoginCoordinator.login(
                    authManager: authManager,
                    stayLoggedIn: stayLoggedIn,
                    preferImmediatelyAvailableCredentials: preferImmediatelyAvailableCredentials
                )
            } catch {
                errorMessage = error.localizedDescription
                AccessibilityAnnouncement.announce(error.localizedDescription)
            }
            isLoading = false
        }
    }
}

enum PasskeyLoginCoordinator {
    @MainActor
    static func login(
        authManager: AuthManager,
        stayLoggedIn: Bool,
        preferImmediatelyAvailableCredentials: Bool
    ) async throws {
        let api = APIClient.shared

        let options: PasskeyAssertionInitResponse = try await api.request(
            .post,
            path: "/v1/auth/passkey/assertion/initiate",
            body: [:] as [String: String]
        )

        guard options.success else {
            throw PasskeyError.serverMessage(options.message)
        }

        let assertion = try await performPlatformAssertion(
            options: options,
            stayLoggedIn: stayLoggedIn,
            sessionId: AuthManager.nativeSessionId,
            preferImmediatelyAvailableCredentials: preferImmediatelyAvailableCredentials
        )

        let verifyResponse: PasskeyVerifyResponse = try await api.request(
            .post,
            path: "/v1/auth/passkey/assertion/verify",
            body: assertion.verifyRequest
        )

        guard verifyResponse.success else {
            throw PasskeyError.serverMessage(verifyResponse.message)
        }

        guard let emailSaltB64 = verifyResponse.userEmailSalt,
              let emailSalt = Data(base64Encoded: emailSaltB64),
              let encryptedMasterKey = verifyResponse.encryptedMasterKey,
              let keyIv = verifyResponse.keyIv else {
            throw PasskeyError.missingCryptoData
        }

        let wrappingKey = await CryptoManager.shared.deriveWrappingKeyFromPRF(
            prfSignature: assertion.prfSignature,
            emailSalt: emailSalt
        )
        let masterKey = try await CryptoManager.shared.unwrapMasterKey(
            wrappedKeyBase64: encryptedMasterKey,
            ivBase64: keyIv,
            wrappingKey: wrappingKey
        )

        let userEmail: String
        if let providedEmail = verifyResponse.userEmail, !providedEmail.isEmpty {
            userEmail = providedEmail
        } else if let encryptedEmail = verifyResponse.encryptedEmail {
            userEmail = try await CryptoManager.shared.decryptContent(
                base64String: encryptedEmail,
                key: masterKey
            )
        } else {
            throw PasskeyError.missingEmail
        }

        let hashedEmail: String
        if let responseHashedEmail = verifyResponse.hashedEmail {
            hashedEmail = responseHashedEmail
        } else {
            hashedEmail = await CryptoManager.shared.hashEmail(userEmail)
        }
        let lookupHash = await CryptoManager.shared.hashKeyFromPRF(
            prfSignature: assertion.prfSignature,
            emailSalt: emailSalt
        )
        let emailEncryptionKey = await CryptoManager.shared.deriveEmailEncryptionKey(
            email: userEmail,
            salt: emailSalt
        ).base64EncodedString()

        let response: LoginResponse = try await api.request(
            .post,
            path: "/v1/auth/login",
            body: LoginRequest(
                hashedEmail: hashedEmail,
                lookupHash: lookupHash,
                loginMethod: "passkey",
                credentialId: assertion.credentialId,
                tfaCode: nil,
                codeType: nil,
                emailEncryptionKey: emailEncryptionKey,
                stayLoggedIn: stayLoggedIn,
                sessionId: AuthManager.nativeSessionId,
                deviceInfo: AuthManager.makeNativeDeviceInfo()
            )
        )

        try await authManager.completePasskeyLogin(response: response, masterKey: masterKey)
    }

    @MainActor
    private static func performPlatformAssertion(
        options: PasskeyAssertionInitResponse,
        stayLoggedIn: Bool,
        sessionId: String,
        preferImmediatelyAvailableCredentials: Bool
    ) async throws -> PasskeyAssertionResult {
        try await withCheckedThrowingContinuation { continuation in
            let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(
                relyingPartyIdentifier: options.rp.id
            )

            guard let challengeData = Data(base64URLEncoded: options.challenge) else {
                continuation.resume(throwing: PasskeyError.invalidChallenge)
                return
            }

            let request = provider.createCredentialAssertionRequest(challenge: challengeData)

            if let allowCredentials = options.allowCredentials {
                request.allowedCredentials = allowCredentials.compactMap { cred in
                    guard let credData = Data(base64URLEncoded: cred.id) else { return nil }
                    return ASAuthorizationPlatformPublicKeyCredentialDescriptor(
                        credentialID: credData
                    )
                }
            }

            if #available(iOS 18.0, macOS 15.0, *),
               let prfSalt = options.extensions?.prf?.eval?.first.flatMap(Data.init(base64URLEncoded:)) {
                request.prf = .inputValues(.saltInput1(prfSalt))
            }

            let controller = ASAuthorizationController(authorizationRequests: [request])
            let delegate = PasskeyDelegate(
                continuation: continuation,
                stayLoggedIn: stayLoggedIn,
                sessionId: sessionId
            )
            controller.delegate = delegate
            controller.presentationContextProvider = delegate

            objc_setAssociatedObject(
                controller, &AssociatedKeys.delegate, delegate, .OBJC_ASSOCIATION_RETAIN
            )

            if preferImmediatelyAvailableCredentials, #available(iOS 16.0, macOS 13.0, *) {
                controller.performRequests(options: .preferImmediatelyAvailableCredentials)
            } else {
                controller.performRequests()
            }
        }
    }
}

struct PasskeyAssertionResult {
    let credentialId: String
    let prfSignature: Data
    let verifyRequest: PasskeyAssertionVerifyRequest
}

private enum AssociatedKeys {
    nonisolated(unsafe) static var delegate: UInt8 = 0
}

enum PasskeyError: LocalizedError {
    case invalidChallenge
    case assertionFailed
    case cancelled
    case missingPRF
    case missingCryptoData
    case missingEmail
    case serverMessage(String?)

    var errorDescription: String? {
        switch self {
        case .invalidChallenge: return "Invalid server challenge"
        case .assertionFailed: return "Passkey verification failed"
        case .cancelled: return "Passkey login was cancelled"
        case .missingPRF: return "This passkey does not support OpenMates encryption. Please use another login method."
        case .missingCryptoData: return "Passkey login data is incomplete. Please try again."
        case .missingEmail: return "Could not recover the account email for passkey login."
        case .serverMessage(let message): return message ?? "Passkey login failed"
        }
    }
}

// MARK: - ASAuthorizationController delegate

private class PasskeyDelegate: NSObject, ASAuthorizationControllerDelegate,
                                ASAuthorizationControllerPresentationContextProviding {
    let continuation: CheckedContinuation<PasskeyAssertionResult, Error>
    let stayLoggedIn: Bool
    let sessionId: String

    init(continuation: CheckedContinuation<PasskeyAssertionResult, Error>, stayLoggedIn: Bool, sessionId: String) {
        self.continuation = continuation
        self.stayLoggedIn = stayLoggedIn
        self.sessionId = sessionId
    }

    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithAuthorization authorization: ASAuthorization
    ) {
        guard let credential = authorization.credential as? ASAuthorizationPlatformPublicKeyCredentialAssertion else {
            continuation.resume(throwing: PasskeyError.assertionFailed)
            return
        }

        guard #available(iOS 18.0, macOS 15.0, *),
              let prfSignature = credential.prf?.first.withUnsafeBytes({ Data($0) }) else {
            continuation.resume(throwing: PasskeyError.missingPRF)
            return
        }

        let credentialId = credential.credentialID.base64URLEncodedString()
        let clientDataJSON = credential.rawClientDataJSON.base64EncodedString()
        let authenticatorData = credential.rawAuthenticatorData.base64EncodedString()

        let request = PasskeyAssertionVerifyRequest(
            credentialId: credentialId,
            assertionResponse: PasskeyAssertionData(
                authenticatorData: authenticatorData,
                clientDataJSON: clientDataJSON,
                signature: credential.signature.base64EncodedString(),
                userHandle: credential.userID.base64EncodedString()
            ),
            clientDataJSON: clientDataJSON,
            authenticatorData: authenticatorData,
            sessionId: sessionId,
            stayLoggedIn: stayLoggedIn,
            hashedEmail: nil,
            emailEncryptionKey: nil
        )

        continuation.resume(returning: PasskeyAssertionResult(
            credentialId: credentialId,
            prfSignature: prfSignature,
            verifyRequest: request
        ))
    }

    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithError error: Error
    ) {
        if (error as? ASAuthorizationError)?.code == .canceled {
            continuation.resume(throwing: PasskeyError.cancelled)
        } else {
            continuation.resume(throwing: error)
        }
    }

    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        #if os(iOS)
        guard let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let window = scene.windows.first else {
            return ASPresentationAnchor()
        }
        return window
        #else
        return NSApplication.shared.windows.first ?? ASPresentationAnchor()
        #endif
    }
}
