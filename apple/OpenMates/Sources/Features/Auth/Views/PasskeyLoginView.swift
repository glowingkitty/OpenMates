// Native passkey login using ASAuthorizationController.
// Mirrors Login.svelte's passkey loading state and immediate WebAuthn start.
// Swift runs only the system ceremony with the PRF extension: the Rust core
// begins the login (request options), then verifies the assertion, derives
// the wrapping key from the PRF output, unwraps, signs in and admits
// (`AuthManager.finishPasskeyLogin`). Passkey device verification uses the
// same ceremony without PRF.
// Specification: specifications/features/auth/specification.yml
// Assertions: auth.login.method-convergence, auth.session.isolation
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.apple.strangler-order

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
            options: options, preferImmediatelyAvailableCredentials: false)
        let response: PasskeyVerifyResponse = try await APIClient.shared.request(
            .post, path: "/v1/auth/passkey/assertion/verify",
            body: assertion.verifyRequest(sessionId: AuthManager.nativeSessionId, stayLoggedIn: true)
        )
        guard response.success, response.userId == expectedUserID else {
            throw PasskeyError.assertionFailed
        }
    }

    /// Passkey sign-in: the core's options, the system ceremony, the core's
    /// finish. A begun login is forgotten in the core when anything fails.
    @MainActor
    static func login(
        authManager: AuthManager,
        stayLoggedIn: Bool,
        preferImmediatelyAvailableCredentials: Bool
    ) async throws {
        let challenge = try await authManager.beginPasskeyLogin(email: nil)
        do {
            try Task.checkCancellation()
            let assertion = try await performPlatformAssertion(
                options: try decodeOptions(challenge.optionsJson),
                preferImmediatelyAvailableCredentials: preferImmediatelyAvailableCredentials)
            try Task.checkCancellation()
            // Without a PRF output the core refuses with its fixed reason
            // (shown as `PasskeyError.missingPRF`) before any request.
            try await authManager.finishPasskeyLogin(assertionJSON: try assertion.coreAssertionJSON(),
                prfOutput: assertion.prfOutput ?? Data(), stayLoggedIn: stayLoggedIn)
        } catch {
            await authManager.cancelPasskeyLogin()
            throw error
        }
    }

    /// Passkey device verification of the core's pending session: the
    /// core's options, the system ceremony, the core's finish.
    @MainActor
    static func verifyDevice(authManager: AuthManager) async throws {
        let challenge = try await authManager.beginPasskeyDeviceVerification()
        do {
            try Task.checkCancellation()
            let assertion = try await performPlatformAssertion(
                options: try decodeOptions(challenge.optionsJson),
                preferImmediatelyAvailableCredentials: false)
            try Task.checkCancellation()
            try await authManager.finishPasskeyDeviceVerification(assertionJSON: try assertion.coreAssertionJSON())
        } catch {
            await authManager.cancelPasskeyLogin()
            throw error
        }
    }

    /// The server's assertion options as the core handed them over.
    static func decodeOptions(_ json: Data) throws -> PasskeyAssertionInitResponse {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        do {
            return try decoder.decode(PasskeyAssertionInitResponse.self, from: json)
        } catch is DecodingError {
            throw PasskeyError.invalidChallenge
        }
    }

    @MainActor
    private static func performPlatformAssertion(
        options: PasskeyAssertionInitResponse,
        preferImmediatelyAvailableCredentials: Bool
    ) async throws -> PasskeyAssertionResult {
        try await assertions.perform {
            try PlatformPasskeyAssertionController(options: options,
                preferImmediatelyAvailableCredentials: preferImmediatelyAvailableCredentials)
        }
    }
}

/// One finished system ceremony: the raw credential id as base64url, the
/// signed fields as standard base64 of the raw bytes, and the PRF `first`
/// output when the passkey produced one (secret: memory only, never logged).
struct PasskeyAssertionResult {
    let credentialId: String
    let clientDataJSON: String
    let authenticatorData: String
    let signature: String
    let userHandle: String?
    let prfOutput: Data?

    /// The core's assertion JSON (`finishPasskeyLogin`,
    /// `finishPasskeyDeviceVerification`); `user_handle` only when present.
    func coreAssertionJSON() throws -> Data {
        var fields = ["credential_id": credentialId, "client_data_json": clientDataJSON,
                      "authenticator_data": authenticatorData, "signature": signature]
        if let userHandle { fields["user_handle"] = userHandle }
        return try JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys])
    }

    /// The server's verify body of a signed-in assertion (pair approval).
    func verifyRequest(sessionId: String, stayLoggedIn: Bool) -> PasskeyAssertionVerifyRequest {
        PasskeyAssertionVerifyRequest(
            credentialId: credentialId,
            assertionResponse: PasskeyAssertionData(
                authenticatorData: authenticatorData, clientDataJSON: clientDataJSON,
                signature: signature, userHandle: userHandle),
            clientDataJSON: clientDataJSON, authenticatorData: authenticatorData,
            sessionId: sessionId, stayLoggedIn: stayLoggedIn, hashedEmail: nil, emailEncryptionKey: nil)
    }
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
    case serverMessage(String?)

    var errorDescription: String? {
        switch self {
        case .invalidChallenge: return "Invalid server challenge"
        case .assertionFailed: return "Passkey verification failed"
        case .cancelled: return "Passkey login was cancelled"
        case .missingPRF: return "This passkey does not support OpenMates encryption. Please use another login method."
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

    init(options: PasskeyAssertionInitResponse, preferImmediatelyAvailableCredentials: Bool) throws {
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

        // Login needs the PRF output; the core refuses a missing one. Device
        // and signed-in verification send the assertion without it.
        var prfOutput: Data?
        if #available(iOS 18.0, macOS 15.0, *) {
            prfOutput = credential.prf?.first.withUnsafeBytes { Data($0) }
        }
        let userHandle = credential.userID.flatMap { $0.isEmpty ? nil : $0.base64EncodedString() }
        finish(.success(PasskeyAssertionResult(
            credentialId: credential.credentialID.base64URLEncodedString(),
            clientDataJSON: credential.rawClientDataJSON.base64EncodedString(),
            authenticatorData: credential.rawAuthenticatorData.base64EncodedString(),
            signature: credential.signature.base64EncodedString(),
            userHandle: userHandle,
            prfOutput: prfOutput
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
