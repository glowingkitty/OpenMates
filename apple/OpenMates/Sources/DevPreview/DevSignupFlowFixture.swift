#if DEBUG
import CryptoKit
import SwiftUI

// The actual production state machine and forms with a deterministic local server.
// No AuthManager/APIClient, cookie, Keychain, newsletter email or account mutation.
struct DevSignupFlowFixture: View {
    let configuration: DevPreviewLaunchConfiguration
    @StateObject private var runtime: PreviewNativeSignupRuntime
    @StateObject private var model: SignupViewModel
    @StateObject private var unavailable: SignupBasicsFormModel
    @State private var didBootstrap = false
    @State private var destination: URL?
    init(configuration: DevPreviewLaunchConfiguration) {
        self.configuration = configuration
        let runtime = PreviewNativeSignupRuntime(variant: configuration.variant)
        _runtime = StateObject(wrappedValue: runtime)
        _model = StateObject(wrappedValue: SignupViewModel(runtime: runtime,
            configuration: .init(inviteCode: nil, language: "en", darkmode: configuration.theme == .dark),
            login: { material, userId, password, form in
                try runtime.finishLocalLogin(material, userId: userId, password: password, form: form)
            }))
        _unavailable = StateObject(wrappedValue: SignupBasicsFormModel(runtime: nil,
            configuration: .init(inviteCode: nil, language: "en", darkmode: false)))
    }
    var body: some View {
        GeometryReader { geometry in
            ScrollView {
                VStack(spacing: 16) {
                    Text("Local signup fixture. No email is sent and no account session is created.")
                        .font(.omSmall).accessibilityIdentifier("fixture-signup-boundary")
                    ZStack {
                        Group {
                            if configuration.variant == "unavailable" {
                                SignupBasicsFormView(model: unavailable, compact: geometry.size.width <= 730,
                                    onOpenURL: { destination = $0 }, onCodeRequested: { _ in })
                            } else {
                                NativeSignupForm(model: model, compact: geometry.size.width <= 730,
                                    onOpenURL: { destination = $0 })
                            }
                        }.opacity(destination == nil ? 1 : 0).accessibilityHidden(destination != nil)
                        if let destination {
                            VStack(spacing: 16) {
                                Text(destination.absoluteString).accessibilityIdentifier("fixture-auth-destination")
                                Button(AppStrings.back) { self.destination = nil }
                                    .accessibilityIdentifier("fixture-auth-return")
                            }
                        }
                    }
                    if runtime.isWaiting {
                        Button("Complete local request") { runtime.completeRequest() }
                            .accessibilityIdentifier("fixture-complete-signup-request")
                    }
                    Text("create=\(runtime.creationCount);login=\(runtime.loginCount)")
                        .font(.omXs).accessibilityIdentifier("fixture-signup-transport-counts")
                    Text("register=\(runtime.registrationCount);assert=\(runtime.assertionCount)")
                        .font(.omXs).accessibilityIdentifier("fixture-signup-authorization-counts")
                    if model.currentStep == .complete {
                        Text("Verified local fixture transition; no real account was created.")
                            .accessibilityIdentifier("fixture-signup-complete")
                    }
                }.frame(maxWidth: geometry.size.width <= 730 ? 326 : 440)
                    .padding(.vertical, 20).padding(.horizontal, 12).frame(maxWidth: .infinity)
            }.background(Color.grey20)
        }
        .task {
            guard !didBootstrap else { return }; didBootstrap = true
            await model.loadRequirements()
            model.continueFromDisclaimer()
            if ["confirm-email", "secure-account", "password", "creation-uncertain", "passkey", "passkey-prf-error", "passkey-cancel", "passkey-uncertain"].contains(configuration.variant) {
                model.basicsModel.form = .init(email: "fixture@example.test", username: "Fixture", termsAccepted: true, privacyAccepted: true)
                if let accepted = await model.basicsModel.submit() { model.acceptRequestedEmailCode(accepted) }
                if ["secure-account", "password", "creation-uncertain", "passkey", "passkey-prf-error", "passkey-cancel", "passkey-uncertain"].contains(configuration.variant) {
                    model.verificationCode = "123456"
                    await model.confirmEmail()
                    if ["password", "creation-uncertain"].contains(configuration.variant) { model.selectPassword() }
                    if configuration.variant == "passkey-prf-error" { await model.registerPasskey() }
                }
            }
        }
        .onDisappear { model.cancel(); runtime.cancel() }
    }
}

@MainActor final class PreviewNativeSignupRuntime: ObservableObject, NativeSignupRuntime {
    let variant: String
    @Published private(set) var isWaiting = false
    @Published private(set) var creationCount = 0
    @Published private(set) var loginCount = 0
    @Published private(set) var registrationCount = 0
    @Published private(set) var assertionCount = 0
    private var pending: CheckedContinuation<Void, Error>?
    private var created: NativeSignupPasswordMaterial?
    private lazy var passkeyHarness = PreviewSignupPasskeyHarness(variant: variant)
    var supportsPasskey: Bool { true }
    func preparePasskey(form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws -> NativeSignupPasskeyMaterial {
        defer { registrationCount = passkeyHarness.authorizer.registrationCount; assertionCount = passkeyHarness.authorizer.assertionCount }
        return try await passkeyHarness.runtime.prepare(form: form, configuration: configuration)
    }
    func createPasskey(_ material: NativeSignupPasskeyMaterial) async throws -> String {
        defer { creationCount = passkeyHarness.completionCount }
        return try await passkeyHarness.runtime.create(material)
    }
    func finishPasskey(_ material: NativeSignupPasskeyMaterial, expectedUserID: String?, form: SignupBasicsForm) async throws {
        defer { assertionCount = passkeyHarness.authorizer.assertionCount }
        try await passkeyHarness.runtime.finish(material, expectedUserID: expectedUserID, form: form)
        loginCount = passkeyHarness.publishCount
    }
    init(variant: String) { self.variant = variant }
    func requirements() async throws -> NativeSignupRequirements { .init(requiresInvite: false, isSelfHosted: false) }
    func validateBasics(_ form: SignupBasicsForm, configuration: SignupBasicsConfiguration, requirements: NativeSignupRequirements) async throws {
        guard form.canSubmit else { throw NativeSignupError.invalidForm }
        if variant == "error" { throw NativeSignupError.usernameUnavailable }
    }
    func requestEmailCode(_ form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws {
        if variant == "loading" {
            try await withCheckedThrowingContinuation { pending = $0; isWaiting = true }
        }
    }
    func subscribeNewsletter(_ form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws {}
    func confirmEmail(_ code: String, form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws {
        guard code == "123456" else { throw NativeSignupError.invalidEmailCode }
    }
    func preparePassword(_ password: String, form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws -> NativeSignupPasswordMaterial {
        // Exercise the real format while keeping all generated bytes in memory.
        try await CryptoManager.shared.prepareNativeSignupPassword(password, form: form, configuration: configuration)
    }
    func createPassword(_ material: NativeSignupPasswordMaterial) async throws -> String {
        creationCount += 1
        created = material
        if variant == "creation-uncertain" { throw NativeSignupError.invalidAccountResponse }
        return "local-fixture-user"
    }
    func finishLocalLogin(_ material: NativeSignupPasswordMaterial, userId: String?, password: String, form: SignupBasicsForm) throws {
        guard let created, created.request == material.request,
              userId == nil || userId == "local-fixture-user",
              NativeSignupPasswordPolicy.strengthErrorKey(for: password) == nil, form.canSubmit else {
            throw NativeSignupError.sessionProofMismatch
        }
        loginCount += 1
    }
    func completeRequest() { let continuation = pending; pending = nil; isWaiting = false; continuation?.resume() }
    func cancel() {
        passkeyHarness.active = false
        let continuation = pending; pending = nil; isWaiting = false
        continuation?.resume(throwing: CancellationError())
    }
}

// Complete deterministic protocol adapter: exercises the production registration
// serializer, cryptography, scoped assertion/verify/login and proof validation.
// Synthetic WebAuthn bytes are never submitted to a server or OS credential store.
@MainActor final class PreviewSignupPasskeyHarness {
    let authorizer = PreviewSignupPasskeyAuthorizer()
    let variant: String
    var active = true
    var completionCount = 0
    var publishCount = 0
    var requests: [(String, Data)] = []
    var completedPayload: [String: Any]?
    var wrongVerifiedUser = false
    var wrongVerifiedEnvelope = false
    var wrongChallenge = false
    var beforeTransportReturn: (@MainActor (String) async -> Void)?
    lazy var runtime = NativeSignupPasskeyRuntime(profile: .development, sessionID: "local-signup-session",
        authorizer: authorizer, deviceName: "Local fixture", isCurrent: { [weak self] in self?.active == true },
        transport: { [weak self] _, path, data in
            guard let self, let data else { throw NativeSignupError.staleContext }
            return try await self.exchange(path: path, body: data)
        }, publish: { [weak self] response, key, proof in
            guard let self, self.active, proof.validates(response), proof.validatesMasterKey(key) else {
                throw NativeSignupError.sessionProofMismatch
            }
            self.publishCount += 1
        })
    init(variant: String = "passkey") {
        self.variant = variant
        authorizer.unsupported = variant == "passkey-prf-error"
        authorizer.cancelNext = variant == "passkey-cancel"
    }
    private func exchange(path: String, body: Data) async throws -> Data {
        requests.append((path, body))
        let result: [String: Any]
        switch path {
        case "/v1/auth/passkey/registration/initiate":
            let payload = try JSONSerialization.jsonObject(with: body) as? [String: Any] ?? [:]
            result = options(username: payload["username"] as? String ?? "Fixture")
        case "/v1/auth/passkey/registration/complete":
            completionCount += 1
            completedPayload = try JSONSerialization.jsonObject(with: body) as? [String: Any]
            if variant == "passkey-uncertain" { throw NativeSignupError.invalidAccountResponse }
            result = ["success": true, "message": "Local completion", "user": ["id": "local-fixture-user", "username": "Fixture"]]
        case "/v1/auth/passkey/assertion/initiate":
            result = options(username: "Fixture")
        case "/v1/auth/passkey/assertion/verify":
            guard let payload = completedPayload else { throw NativeSignupError.invalidAccountResponse }
            result = ["success": true, "user_id": wrongVerifiedUser ? "foreign-user" : "local-fixture-user",
                "hashed_email": payload["hashed_email"]!, "user_email_salt": payload["user_email_salt"]!,
                "encrypted_master_key": wrongVerifiedEnvelope ? "foreign-envelope" : payload["encrypted_master_key"]!,
                "key_iv": payload["key_iv"]!, "encrypted_email": payload["encrypted_email_with_master_key"]!]
        case "/v1/auth/login":
            guard let payload = completedPayload else { throw NativeSignupError.invalidAccountResponse }
            result = ["success": true, "ws_token": "local-fixture-token", "user": ["id": "local-fixture-user", "username": "Fixture",
                "encrypted_key": payload["encrypted_master_key"]!, "key_iv": payload["key_iv"]!,
                "salt": payload["salt"]!, "user_email_salt": payload["user_email_salt"]!]]
        default: throw NativeSignupError.accountRejected
        }
        await beforeTransportReturn?(path)
        return try JSONSerialization.data(withJSONObject: result)
    }
    private func options(username: String) -> [String: Any] {
        let rp = ServerProfile.development.webBaseURL.host!
        let email = Data(SHA256.hash(data: Data("fixture@example.test".utf8)))
        return ["success": true, "challenge": (wrongChallenge ? Data([1]) : authorizer.challenge).base64URLEncodedString(),
            "rp": ["id": rp, "name": "OpenMates"],
            "user": ["id": email.base64URLEncodedString(), "name": username, "displayName": username],
            "pubKeyCredParams": [["type": "public-key", "alg": -7]],
            "authenticatorSelection": ["residentKey": "required", "userVerification": "required"],
            "extensions": ["prf": ["eval": ["first": Data(SHA256.hash(data: Data(rp.utf8))).base64URLEncodedString()]]],
            "allowCredentials": [["type": "public-key", "id": authorizer.credentialID.base64URLEncodedString()]],
            "timeout": 60_000, "attestation": "direct"]
    }
}

@MainActor final class PreviewSignupPasskeyAuthorizer: NativeSignupPasskeyAuthorizer {
    var isAvailable = true
    let credentialID = Data(repeating: 7, count: 32)
    let challenge = Data(repeating: 3, count: 32)
    let prf = Data(repeating: 11, count: 32)
    var registrationCount = 0
    var assertionCount = 0
    var unsupported = false
    var omitCreatePRF = false
    var cancelNext = false
    var returnForeignCredential = false
    var returnForeignUserHandle = false
    var registrationOrigin: String?
    var beforeReturn: (@MainActor () async -> Void)?
    var assertedCredentialIDs: [Data] = []
    func register(options: NativeSignupPasskeyOptions, challenge: Data, userID: Data, prfSalt: Data) async throws -> NativePasskeyRegistrationResult {
        registrationCount += 1
        if cancelNext { cancelNext = false; throw NativeSignupError.passkeyCancelled }
        await beforeReturn?()
        let authData = authenticatorData(rpID: options.rp.id, registration: true)
        let cbor = Data([0xA3]) + cborText("fmt") + cborText("none") + cborText("attStmt") + Data([0xA0]) + cborText("authData") + cborBytes(authData)
        return .init(credentialID: credentialID,
            clientDataJSON: try clientData(type: "webauthn.create", challenge: challenge,
                origin: registrationOrigin ?? ServerProfile.development.webBaseURL.absoluteString),
            attestationObject: cbor, prfOutput: unsupported || omitCreatePRF ? nil : prf,
            supportsPRF: !unsupported)
    }
    func assert(rpID: String, challenge: Data, credentialID: Data, prfSalt: Data) async throws -> NativePasskeyAssertionResult {
        assertionCount += 1
        assertedCredentialIDs.append(credentialID)
        await beforeReturn?()
        return .init(credentialID: returnForeignCredential ? Data([99]) : credentialID,
            clientDataJSON: try clientData(type: "webauthn.get", challenge: challenge, origin: ServerProfile.development.webBaseURL.absoluteString),
            authenticatorData: authenticatorData(rpID: rpID, registration: false),
            signature: Data(repeating: 8, count: 64), userHandle: returnForeignUserHandle ? Data([99]) : Data(SHA256.hash(data: Data("fixture@example.test".utf8))),
            prfOutput: unsupported ? nil : prf)
    }
    func authenticatorData(rpID: String, registration: Bool) -> Data {
        let header = Data(SHA256.hash(data: Data(rpID.utf8))) + Data([registration ? 0x45 : 0x05, 0, 0, 0, 0])
        guard registration else { return header }
        return header + Data(repeating: 0, count: 16) + Data([0, UInt8(credentialID.count)]) + credentialID + Data([0xA0])
    }
    private func clientData(type: String, challenge: Data, origin: String) throws -> Data {
        try JSONSerialization.data(withJSONObject: ["type": type, "challenge": challenge.base64URLEncodedString(), "origin": origin, "crossOrigin": false])
    }
    private func cborText(_ string: String) -> Data {
        let bytes = Data(string.utf8)
        return Data([0x60 + UInt8(bytes.count)]) + bytes
    }
    private func cborBytes(_ data: Data) -> Data {
        Data([0x58, UInt8(data.count)]) + data
    }
}
#endif
