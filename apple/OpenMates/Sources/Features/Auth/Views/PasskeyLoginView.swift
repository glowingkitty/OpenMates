// Native passkey login using ASAuthorizationController.
// Mirrors Login.svelte's passkey loading state and immediate WebAuthn start.
// Uses the PRF extension for zero-knowledge master-key unwrapping, then
// completes the same /auth/login session path as the web app.
// Specification: specifications/features/auth/specification.yml
// Assertions: auth.login.method-convergence, auth.session.isolation

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
    @State private var loginTask: Task<Void, Never>?
    // Local preview injection exercises the production task ownership without OS UI.
    var login: (@MainActor () async throws -> Void)? = nil

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
            await runPasskeyLogin(preferImmediatelyAvailableCredentials: false)
        }
        .onDisappear {
            loginTask?.cancel()
            loginTask = nil
        }
    }

    private func startPasskeyLogin(preferImmediatelyAvailableCredentials: Bool) {
        guard loginTask == nil else { return }
        loginTask = Task {
            await runPasskeyLogin(preferImmediatelyAvailableCredentials: preferImmediatelyAvailableCredentials)
            loginTask = nil
        }
    }

    @MainActor
    private func runPasskeyLogin(preferImmediatelyAvailableCredentials: Bool) async {
        isLoading = true
        errorMessage = nil
        do {
            if let login { try await login() }
            else {
                try await PasskeyLoginCoordinator.login(
                    authManager: authManager, stayLoggedIn: stayLoggedIn,
                    preferImmediatelyAvailableCredentials: preferImmediatelyAvailableCredentials
                )
            }
        } catch is CancellationError {
            return
        } catch {
            guard !Task.isCancelled else { return }
            errorMessage = error.localizedDescription
            AccessibilityAnnouncement.announce(error.localizedDescription)
        }
        guard !Task.isCancelled else { return }
        isLoading = false
    }

}

enum PasskeyLoginCoordinator {
    @MainActor private static let assertions = PasskeyAssertionLifecycle()
    /// Verifies a fresh passkey assertion without creating or switching the
    /// current session. The backend binds this proof to the existing refresh
    /// cookie before allowing a sensitive pair approval.
    @MainActor
    static func verifyCurrentSessionAssertion(expectedUserID: String) async throws {
        let options: PasskeyAssertionInitResponse = try await APIClient.shared.request(
            .post, path: "/v1/auth/passkey/assertion/initiate", body: [:] as [String: String]
        )
        try Task.checkCancellation()
        guard options.success else { throw PasskeyError.serverMessage(options.message) }
        let assertion = try await performPlatformAssertion(
            options: options, stayLoggedIn: true,
            sessionId: AuthManager.nativeSessionId,
            preferImmediatelyAvailableCredentials: false
        )
        let response: PasskeyVerifyResponse = try await APIClient.shared.request(
            .post, path: "/v1/auth/passkey/assertion/verify", body: assertion.verifyRequest
        )
        guard response.success, response.userId == expectedUserID else {
            throw PasskeyError.assertionFailed
        }
    }

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

        try Task.checkCancellation()
        guard options.success else {
            throw PasskeyError.serverMessage(options.message)
        }

        let assertion = try await performPlatformAssertion(
            options: options,
            stayLoggedIn: stayLoggedIn,
            sessionId: AuthManager.nativeSessionId,
            preferImmediatelyAvailableCredentials: preferImmediatelyAvailableCredentials
        )

        try Task.checkCancellation()
        let verifyResponse: PasskeyVerifyResponse = try await api.request(
            .post,
            path: "/v1/auth/passkey/assertion/verify",
            body: assertion.verifyRequest
        )

        try Task.checkCancellation()
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

        try Task.checkCancellation()
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

        try Task.checkCancellation()
        try await authManager.completePasskeyLogin(response: response, masterKey: masterKey)
    }

    @MainActor
    private static func performPlatformAssertion(
        options: PasskeyAssertionInitResponse,
        stayLoggedIn: Bool,
        sessionId: String,
        preferImmediatelyAvailableCredentials: Bool
    ) async throws -> PasskeyAssertionResult {
        try await assertions.perform {
            try PlatformPasskeyAssertionController(options: options, stayLoggedIn: stayLoggedIn,
                sessionId: sessionId,
                preferImmediatelyAvailableCredentials: preferImmediatelyAvailableCredentials)
        }
    }
}

struct PasskeyAssertionResult {
    let credentialId: String
    let prfSignature: Data
    let verifyRequest: PasskeyAssertionVerifyRequest
}

/// Owns one OS authorization at a time. Cancellation waits for the controller's
/// delegate completion before admitting a successor, matching the web abort/drain.
@MainActor
protocol PasskeyAssertionController: AnyObject {
    func start(completion: @escaping @MainActor (Result<PasskeyAssertionResult, Error>) -> Void)
    func cancel()
}

@MainActor
final class PasskeyAssertionLifecycle {
    private var active: PasskeyAssertionOperation?

    func perform(makeController: () throws -> any PasskeyAssertionController) async throws -> PasskeyAssertionResult {
        try Task.checkCancellation()
        while let previous = active {
            previous.cancel()
            await previous.waitUntilFinished()
            if active === previous { active = nil }
            try Task.checkCancellation()
        }
        try Task.checkCancellation()
        let operation = PasskeyAssertionOperation(controller: try makeController())
        active = operation
        defer { if active === operation { active = nil } }
        return try await withTaskCancellationHandler {
            let result = try await operation.run()
            try Task.checkCancellation()
            return result
        } onCancel: {
            Task { @MainActor in operation.cancel() }
        }
    }
}

@MainActor
final class PasskeyAssertionOperation {
    private let controller: any PasskeyAssertionController
    private var continuation: CheckedContinuation<PasskeyAssertionResult, Error>?
    private var waiters: [CheckedContinuation<Void, Never>] = []
    private var finished = false
    private var cancelled = false

    init(controller: any PasskeyAssertionController) { self.controller = controller }

    func run() async throws -> PasskeyAssertionResult {
        try await withCheckedThrowingContinuation { continuation in
            guard !finished, !cancelled, !Task.isCancelled else {
                cancel()
                continuation.resume(throwing: CancellationError())
                return
            }
            self.continuation = continuation
            controller.start { [self] result in finish(result) }
        }
    }

    func cancel() {
        guard !finished, !cancelled else { return }
        cancelled = true
        // ASAuthorizationController.cancel guarantees the delegate callback;
        // retain the operation until it arrives so a manual request cannot overlap.
        if continuation != nil { controller.cancel() }
        else { finish(.failure(CancellationError())) }
    }

    func waitUntilFinished() async {
        guard !finished else { return }
        await withCheckedContinuation { waiters.append($0) }
    }

    private func finish(_ result: Result<PasskeyAssertionResult, Error>) {
        guard !finished else { return }
        finished = true
        let continuation = self.continuation
        self.continuation = nil
        if cancelled { continuation?.resume(throwing: CancellationError()) }
        else { continuation?.resume(with: result) }
        let waiters = self.waiters
        self.waiters.removeAll()
        for waiter in waiters { waiter.resume() }
    }
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

@MainActor
private final class PlatformPasskeyAssertionController: NSObject, PasskeyAssertionController,
    ASAuthorizationControllerDelegate, ASAuthorizationControllerPresentationContextProviding {
    private let controller: ASAuthorizationController
    private let preferImmediatelyAvailableCredentials: Bool
    private var completion: (@MainActor (Result<PasskeyAssertionResult, Error>) -> Void)?
    private let stayLoggedIn: Bool
    private let sessionId: String

    init(options: PasskeyAssertionInitResponse, stayLoggedIn: Bool, sessionId: String,
         preferImmediatelyAvailableCredentials: Bool) throws {
        guard let challenge = Data(base64URLEncoded: options.challenge) else { throw PasskeyError.invalidChallenge }
        let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(relyingPartyIdentifier: options.rp.id)
        let request = provider.createCredentialAssertionRequest(challenge: challenge)
        if let allowCredentials = options.allowCredentials {
            request.allowedCredentials = allowCredentials.compactMap { credential in
                guard let data = Data(base64URLEncoded: credential.id) else { return nil }
                return ASAuthorizationPlatformPublicKeyCredentialDescriptor(credentialID: data)
            }
        }
        if #available(iOS 18.0, macOS 15.0, *),
           let salt = options.extensions?.prf?.eval?.first.flatMap(Data.init(base64URLEncoded:)) {
            request.prf = .inputValues(.saltInput1(salt))
        }
        self.controller = ASAuthorizationController(authorizationRequests: [request])
        self.stayLoggedIn = stayLoggedIn
        self.sessionId = sessionId
        self.preferImmediatelyAvailableCredentials = preferImmediatelyAvailableCredentials
        super.init()
        controller.delegate = self
        controller.presentationContextProvider = self
    }

    func start(completion: @escaping @MainActor (Result<PasskeyAssertionResult, Error>) -> Void) {
        self.completion = completion
        if preferImmediatelyAvailableCredentials { controller.performRequests(options: .preferImmediatelyAvailableCredentials) }
        else { controller.performRequests() }
    }

    func cancel() { controller.cancel() }

    private func finish(_ result: Result<PasskeyAssertionResult, Error>) {
        let completion = self.completion
        self.completion = nil
        completion?(result)
    }

    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithAuthorization authorization: ASAuthorization
    ) {
        guard let credential = authorization.credential as? ASAuthorizationPlatformPublicKeyCredentialAssertion else {
            finish(.failure(PasskeyError.assertionFailed))
            return
        }

        guard #available(iOS 18.0, macOS 15.0, *),
              let prfSignature = credential.prf?.first.withUnsafeBytes({ Data($0) }) else {
            finish(.failure(PasskeyError.missingPRF))
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

        finish(.success(PasskeyAssertionResult(
            credentialId: credentialId,
            prfSignature: prfSignature,
            verifyRequest: request
        )))
    }

    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithError error: Error
    ) {
        if (error as? ASAuthorizationError)?.code == .canceled {
            finish(.failure(PasskeyError.cancelled))
        } else {
            finish(.failure(error))
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
