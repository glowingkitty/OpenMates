// Real signup coordinator. Password completion follows signupFlow.ts and
// PasswordBottomContent.svelte; optional security/settings steps are not invented.
import Combine
import Foundation

@MainActor final class SignupViewModel: ObservableObject {
    enum SignupStep: Int, CaseIterable { case alphaDisclaimer, basics, confirmEmail, secureAccount, password, passkeyPRFError, complete }
    typealias Login = @MainActor (NativeSignupPasswordMaterial, String?, String, SignupBasicsForm) async throws -> Void
    @Published private(set) var currentStep: SignupStep = .alphaDisclaimer
    @Published private(set) var transitionIsForward = true
    @Published private(set) var submittedBasics: SignupBasicsForm?
    @Published private(set) var requirements: NativeSignupRequirements?
    @Published private(set) var isLoading = false
    @Published private(set) var error: NativeSignupError?
    @Published var inviteCode = ""
    @Published var password = ""
    @Published var confirmPassword = ""
    @Published var verificationCode = ""
    @Published private(set) var creationAttempted = false
    @Published private(set) var passkeyCreationAttempted = false
    @Published private(set) var email = ""
    @Published private(set) var username = ""
    private var runtime: (any NativeSignupRuntime)?
    private var login: Login?
    private var configuration: SignupBasicsConfiguration
    private var submittedConfiguration: SignupBasicsConfiguration?
    private var pendingMaterial: NativeSignupPasswordMaterial?
    private var pendingPassword: String?
    private var pendingPasskey: NativeSignupPasskeyMaterial?
    private var createdUserId: String?
    private var generation = 0
    private var active = true
    private var operation: Task<Void, Never>?
    private var newsletterOperation: Task<Void, Never>?
    private let suppliedBasicsModel: SignupBasicsFormModel?
    lazy var basicsModel: SignupBasicsFormModel = suppliedBasicsModel ?? SignupBasicsFormModel(
        runtime: BasicsRelay(owner: self), configuration: configuration)

    init(basicsModel: SignupBasicsFormModel? = nil,
         runtime: (any NativeSignupRuntime)? = nil,
         configuration: SignupBasicsConfiguration = .init(inviteCode: nil, language: "en", darkmode: false),
         login: Login? = nil) {
        suppliedBasicsModel = basicsModel
        self.runtime = runtime
        self.configuration = configuration
        self.login = login
        inviteCode = configuration.inviteCode ?? ""
    }
    var totalSteps: Int { SignupStep.allCases.count }
    var supportsPasskey: Bool { runtime?.supportsPasskey == true }
    var canRegisterPasskey: Bool {
        active && currentStep == .secureAccount && !isLoading && supportsPasskey &&
            !creationAttempted && (!passkeyCreationAttempted || pendingPasskey != nil)
    }
    var canChoosePassword: Bool {
        active && currentStep == .secureAccount && !isLoading && !passkeyCreationAttempted
    }
    var passwordValidation: NativeSignupPasswordPolicy.Validation {
        NativeSignupPasswordPolicy.validate(password: password, confirmation: confirmPassword)
    }
    var canSubmitPassword: Bool {
        active && currentStep == .password && !isLoading && login != nil &&
        (creationAttempted ? pendingMaterial != nil : passwordValidation.isValid)
    }
    var canConfirmEmail: Bool {
        active && currentStep == .confirmEmail && !isLoading && verificationCode.count == 6 &&
        verificationCode.allSatisfy { $0.isASCII && $0.isNumber }
    }
    func configure(runtime: any NativeSignupRuntime, configuration: SignupBasicsConfiguration, login: @escaping Login) {
        guard self.runtime == nil, submittedBasics == nil, active else { return }
        self.runtime = runtime
        self.configuration = configuration
        self.login = login
    }
    func continueFromDisclaimer() { guard active, currentStep == .alphaDisclaimer else { return }; move(to: .basics) }
    func selectPassword() { guard canChoosePassword else { return }; move(to: .password) }
    func returnFromPasskeyError() {
        guard active, currentStep == .passkeyPRFError, !passkeyCreationAttempted else { return }
        error = nil
        move(to: .secureAccount)
    }
    func start(_ action: @escaping @MainActor () async -> Void) {
        guard active, operation == nil else { return }
        operation = Task { [weak self] in
            await action()
            self?.operation = nil
        }
    }
    func cancel() {
        active = false
        generation += 1
        operation?.cancel()
        newsletterOperation?.cancel()
        newsletterOperation = nil
        operation = nil
        password = ""
        confirmPassword = ""
        pendingPassword = nil
        pendingMaterial = nil
        pendingPasskey = nil
        isLoading = false
    }
    func loadRequirements() async {
        guard active, requirements == nil, !isLoading, let runtime else { return }
        let owner = generation
        isLoading = true
        error = nil
        defer { if isCurrent(owner) { isLoading = false } }
        do {
            let loaded = try await runtime.requirements()
            guard isCurrent(owner) else { return }
            requirements = loaded
        } catch { if isCurrent(owner) { self.error = classify(error) } }
    }
    private func requestBasics(_ form: SignupBasicsForm) async throws {
        guard active, let runtime, let requirements else { throw NativeSignupError.requirementsNotLoaded }
        let owner = generation
        let snapshot = SignupBasicsConfiguration(inviteCode: inviteCode.isEmpty ? nil : inviteCode,
            language: configuration.language, darkmode: configuration.darkmode)
        error = nil
        do {
            try await runtime.validateBasics(form, configuration: snapshot, requirements: requirements)
            guard isCurrent(owner) else { throw NativeSignupError.staleContext }
            if !requirements.isSelfHosted {
                try await runtime.requestEmailCode(form, configuration: snapshot)
            }
            guard isCurrent(owner) else { throw NativeSignupError.staleContext }
            submittedConfiguration = snapshot
        } catch {
            if isCurrent(owner) { self.error = classify(error) }
            throw error
        }
    }
    // The shared form commits its exact accepted snapshot before notifying us.
    func acceptRequestedEmailCode(_ submitted: SignupBasicsForm) {
        guard active, basicsModel.submittedForm == submitted else { return }
        submittedBasics = submitted
        email = submitted.email
        username = submitted.username
        move(to: requirements?.isSelfHosted == true ? .secureAccount : .confirmEmail)
        if submitted.newsletter, let runtime, let config = submittedConfiguration, newsletterOperation == nil {
            // Web Basics.svelte sends an opted-in newsletter confirmation request
            // independently. A newsletter failure never changes signup success.
            newsletterOperation = Task { try? await runtime.subscribeNewsletter(submitted, configuration: config) }
        }
    }
    func confirmEmail() async {
        guard canConfirmEmail, let runtime, let form = submittedBasics, let config = submittedConfiguration else { return }
        let owner = generation
        isLoading = true
        error = nil
        defer { if isCurrent(owner) { isLoading = false } }
        do {
            try await runtime.confirmEmail(verificationCode, form: form, configuration: config)
            guard isCurrent(owner) else { return }
            verificationCode = ""
            move(to: .secureAccount)
        } catch {
            if isCurrent(owner) {
                verificationCode = "" // Web clears a rejected code so the next six digits retry directly.
                self.error = classify(error)
            }
        }
    }
    func resendEmailCode() async {
        guard active, currentStep == .confirmEmail, !isLoading,
              let runtime, let form = submittedBasics, let config = submittedConfiguration else { return }
        let owner = generation
        isLoading = true
        error = nil
        defer { if isCurrent(owner) { isLoading = false } }
        do {
            try await runtime.requestEmailCode(form, configuration: config)
            guard isCurrent(owner) else { return }
            verificationCode = ""
        } catch { if isCurrent(owner) { self.error = classify(error) } }
    }
    func setPassword() async {
        guard canSubmitPassword, let runtime, let login,
              let form = submittedBasics, let config = submittedConfiguration else { return }
        let owner = generation
        isLoading = true
        error = nil
        defer { if isCurrent(owner) { isLoading = false } }
        do {
            if !creationAttempted {
                let enteredPassword = password
                let material = try await runtime.preparePassword(enteredPassword, form: form, configuration: config)
                guard isCurrent(owner) else { return }
                pendingMaterial = material
                pendingPassword = enteredPassword
                // Once dispatched, transport failure cannot prove creation failed.
                // Retain the exact keys and retry login only, never setup_password.
                creationAttempted = true
                do {
                    let userId = try await runtime.createPassword(material)
                    guard isCurrent(owner) else { return }
                    createdUserId = userId
                } catch NativeSignupError.verificationRequired {
                    guard isCurrent(owner) else { return }
                    creationAttempted = false
                    pendingMaterial = nil
                    pendingPassword = nil
                    move(to: .confirmEmail)
                    try await runtime.requestEmailCode(form, configuration: config)
                    guard isCurrent(owner) else { return }
                    error = .verificationRequired
                    return
                }
            }
            guard isCurrent(owner), let material = pendingMaterial, let enteredPassword = pendingPassword else { return }
            try await login(material, createdUserId, enteredPassword, form)
            guard isCurrent(owner) else { return }
            password = ""
            confirmPassword = ""
            pendingPassword = nil
            pendingMaterial = nil
            move(to: .complete)
        } catch {
            if isCurrent(owner) {
                self.error = creationAttempted ? .creationUnconfirmed : classify(error)
            }
        }
    }
    func registerPasskey() async {
        guard canRegisterPasskey, let runtime, let form = submittedBasics, let config = submittedConfiguration else { return }
        let owner = generation
        isLoading = true
        error = nil
        defer { if isCurrent(owner) { isLoading = false } }
        do {
            if !passkeyCreationAttempted {
                let material = try await runtime.preparePasskey(form: form, configuration: config)
                guard isCurrent(owner) else { return }
                pendingPasskey = material
                // complete may create_user before returning a later failure. Any
                // dispatched attempt becomes exact-credential login recovery only.
                passkeyCreationAttempted = true
                do {
                    let created = try await runtime.createPasskey(material)
                    guard isCurrent(owner) else { return }
                    createdUserId = created
                } catch NativeSignupError.verificationRequired {
                    guard isCurrent(owner) else { return }
                    passkeyCreationAttempted = false
                    pendingPasskey = nil
                    createdUserId = nil
                    move(to: .confirmEmail)
                    try await runtime.requestEmailCode(form, configuration: config)
                    guard isCurrent(owner) else { return }
                    error = .verificationRequired
                    return
                }
            }
            guard isCurrent(owner), let material = pendingPasskey else { return }
            try await runtime.finishPasskey(material, expectedUserID: createdUserId, form: form)
            guard isCurrent(owner) else { return }
            pendingPasskey = nil
            move(to: .complete)
        } catch {
            guard isCurrent(owner) else { return }
            if passkeyCreationAttempted {
                self.error = .creationUnconfirmed
            } else if error as? NativeSignupError == .passkeyUnsupported {
                pendingPasskey = nil
                move(to: .passkeyPRFError)
            } else if error as? NativeSignupError == .passkeyCancelled || error is CancellationError {
                pendingPasskey = nil // User cancellation before completion creates no server account.
            } else {
                self.error = classify(error)
            }
        }
    }

    private func move(to step: SignupStep) {
        transitionIsForward = step.rawValue > currentStep.rawValue
        currentStep = step
    }
    private func isCurrent(_ owner: Int) -> Bool { active && generation == owner && !Task.isCancelled }
    private func classify(_ error: Error) -> NativeSignupError { (error as? NativeSignupError) ?? .accountRejected }
    @MainActor private struct BasicsRelay: SignupBasicsRuntime {
        weak var owner: SignupViewModel?
        func requestCode(form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws {
            guard let owner else { throw NativeSignupError.staleContext }
            try await owner.requestBasics(form)
        }
    }
}
