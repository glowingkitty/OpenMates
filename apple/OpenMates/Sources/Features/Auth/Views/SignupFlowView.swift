// Signup flow — multi-step registration matching the web app's Signup.svelte.
// Steps: basics (email) → confirm email → password → passkey → recovery key →
// backup codes → payment → profile picture → settings → complete.

import SwiftUI
import AuthenticationServices

// MARK: - Signup coordinator

struct SignupFlowView: View {
    @StateObject private var viewModel = SignupViewModel()
    @Environment(\.dismiss) var dismiss

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                SignupProgressBar(currentStep: viewModel.currentStep, totalSteps: viewModel.totalSteps)

                Group {
                    switch viewModel.currentStep {
                    case .basics:
                        SignupBasicsStep(viewModel: viewModel)
                    case .confirmEmail:
                        SignupConfirmEmailStep(viewModel: viewModel)
                    case .password:
                        SignupPasswordStep(viewModel: viewModel)
                    case .passkey:
                        SignupPasskeyStep(viewModel: viewModel)
                    case .recoveryKey:
                        SignupRecoveryKeyStep(viewModel: viewModel)
                    case .backupCodes:
                        SignupBackupCodesStep(viewModel: viewModel)
                    case .payment:
                        SignupPaymentStep(viewModel: viewModel)
                    case .profilePicture:
                        SignupProfilePictureStep(viewModel: viewModel)
                    case .complete:
                        SignupCompleteStep(onFinish: { dismiss() })
                    }
                }
                .transition(.asymmetric(
                    insertion: .move(edge: .trailing),
                    removal: .move(edge: .leading)
                ))
                .animation(.easeInOut(duration: 0.25), value: viewModel.currentStep)
            }
            .navigationTitle("Create Account")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
    }
}

// MARK: - View model

@MainActor
final class SignupViewModel: ObservableObject {
    @Published var currentStep: SignupStep = .basics
    @Published var email = ""
    @Published var username = ""
    @Published var password = ""
    @Published var confirmPassword = ""
    @Published var verificationCode = ""
    @Published var recoveryKey: String?
    @Published var backupCodes: [String] = []
    @Published var isLoading = false
    @Published var error: String?

    enum SignupStep: Int, CaseIterable {
        case basics, confirmEmail, password, passkey, recoveryKey, backupCodes, payment, profilePicture, complete
    }

    var totalSteps: Int { SignupStep.allCases.count }

    func nextStep() {
        guard let next = SignupStep(rawValue: currentStep.rawValue + 1) else { return }
        currentStep = next
    }

    func previousStep() {
        guard let prev = SignupStep(rawValue: currentStep.rawValue - 1) else { return }
        currentStep = prev
    }

    func skipToStep(_ step: SignupStep) {
        currentStep = step
    }

    func registerBasics() async {
        isLoading = true
        error = nil
        do {
            let _: Data = try await APIClient.shared.request(
                .post, path: "/v1/auth/register/basics",
                body: ["email": email, "username": username]
            )
            nextStep()
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    func confirmEmail() async {
        isLoading = true
        error = nil
        do {
            let _: Data = try await APIClient.shared.request(
                .post, path: "/v1/auth/register/confirm-email",
                body: ["code": verificationCode]
            )
            nextStep()
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    func setPassword() async {
        isLoading = true
        error = nil
        do {
            let _: Data = try await APIClient.shared.request(
                .post, path: "/v1/auth/register/password",
                body: ["password": password]
            )
            nextStep()
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    func generateRecoveryKey() async {
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .post, path: "/v1/auth/register/recovery-key",
                body: [:] as [String: String]
            )
            recoveryKey = response["recovery_key"]?.value as? String
        } catch {
            self.error = error.localizedDescription
        }
    }

    func generateBackupCodes() async {
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .post, path: "/v1/auth/register/backup-codes",
                body: [:] as [String: String]
            )
            backupCodes = response["codes"]?.value as? [String] ?? []
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: - Progress bar

struct SignupProgressBar: View {
    let currentStep: SignupViewModel.SignupStep
    let totalSteps: Int

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Rectangle().fill(Color.grey10)
                Rectangle()
                    .fill(Color.buttonPrimary)
                    .frame(width: geo.size.width * CGFloat(currentStep.rawValue + 1) / CGFloat(totalSteps))
                    .animation(.easeInOut, value: currentStep)
            }
        }
        .frame(height: 3)
    }
}

// MARK: - Step views

struct SignupBasicsStep: View {
    @ObservedObject var viewModel: SignupViewModel

    var body: some View {
        ScrollView {
            VStack(spacing: .spacing6) {
                Text("Let's get started")
                    .font(.omH2).fontWeight(.bold)

                TextField("Email", text: $viewModel.email)
                    .keyboardType(.emailAddress)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
                    .textContentType(.emailAddress)
                    .textFieldStyle(.roundedBorder)

                TextField("Username", text: $viewModel.username)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
                    .textFieldStyle(.roundedBorder)

                if let error = viewModel.error {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                }

                Button {
                    Task { await viewModel.registerBasics() }
                } label: {
                    HStack {
                        Spacer()
                        if viewModel.isLoading { ProgressView() } else { Text("Continue") }
                        Spacer()
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(Color.buttonPrimary)
                .disabled(viewModel.email.isEmpty || viewModel.username.isEmpty || viewModel.isLoading)
            }
            .padding(.spacing8)
        }
    }
}

struct SignupConfirmEmailStep: View {
    @ObservedObject var viewModel: SignupViewModel

    var body: some View {
        ScrollView {
            VStack(spacing: .spacing6) {
                Image(systemName: "envelope.badge")
                    .font(.system(size: 48)).foregroundStyle(Color.buttonPrimary)

                Text("Check your email")
                    .font(.omH2).fontWeight(.bold)

                Text("We sent a verification code to \(viewModel.email)")
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.center)

                TextField("Verification code", text: $viewModel.verificationCode)
                    .keyboardType(.numberPad)
                    .textFieldStyle(.roundedBorder)
                    .multilineTextAlignment(.center)
                    .font(.system(.title2, design: .monospaced))

                if let error = viewModel.error {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                }

                Button {
                    Task { await viewModel.confirmEmail() }
                } label: {
                    HStack { Spacer(); Text("Verify"); Spacer() }
                }
                .buttonStyle(.borderedProminent)
                .tint(Color.buttonPrimary)
                .disabled(viewModel.verificationCode.isEmpty || viewModel.isLoading)
            }
            .padding(.spacing8)
        }
    }
}

struct SignupPasswordStep: View {
    @ObservedObject var viewModel: SignupViewModel

    private var passwordsMatch: Bool {
        !viewModel.confirmPassword.isEmpty && viewModel.password == viewModel.confirmPassword
    }

    private var isValid: Bool {
        viewModel.password.count >= 8 && passwordsMatch
    }

    var body: some View {
        ScrollView {
            VStack(spacing: .spacing6) {
                Text("Set a password")
                    .font(.omH2).fontWeight(.bold)

                SecureField("Password (min 8 characters)", text: $viewModel.password)
                    .textContentType(.newPassword).textFieldStyle(.roundedBorder)

                SecureField("Confirm password", text: $viewModel.confirmPassword)
                    .textContentType(.newPassword).textFieldStyle(.roundedBorder)

                if !viewModel.confirmPassword.isEmpty && !passwordsMatch {
                    Text("Passwords don't match")
                        .font(.omXs).foregroundStyle(Color.error)
                }

                if let error = viewModel.error {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                }

                Button {
                    Task { await viewModel.setPassword() }
                } label: {
                    HStack { Spacer(); Text("Continue"); Spacer() }
                }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                .disabled(!isValid || viewModel.isLoading)
            }
            .padding(.spacing8)
        }
    }
}

struct SignupPasskeyStep: View {
    @ObservedObject var viewModel: SignupViewModel

    var body: some View {
        ScrollView {
            VStack(spacing: .spacing6) {
                Image(systemName: "person.badge.key")
                    .font(.system(size: 48)).foregroundStyle(Color.buttonPrimary)

                Text("Add a Passkey")
                    .font(.omH2).fontWeight(.bold)

                Text("Passkeys let you sign in securely with Face ID, Touch ID, or your device PIN.")
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.center)

                Button("Set Up Passkey") {
                    // Passkey registration via ASAuthorizationController
                    viewModel.nextStep()
                }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)

                Button("Skip for Now") { viewModel.nextStep() }
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
            }
            .padding(.spacing8)
        }
    }
}

struct SignupRecoveryKeyStep: View {
    @ObservedObject var viewModel: SignupViewModel

    var body: some View {
        ScrollView {
            VStack(spacing: .spacing6) {
                Image(systemName: "key.horizontal")
                    .font(.system(size: 48)).foregroundStyle(Color.buttonPrimary)

                Text("Save Your Recovery Key")
                    .font(.omH2).fontWeight(.bold)

                Text("This is your last resort to recover your account. Store it somewhere safe.")
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.center)

                if let key = viewModel.recoveryKey {
                    Text(key)
                        .font(.system(.body, design: .monospaced))
                        .textSelection(.enabled)
                        .padding(.spacing4)
                        .background(Color.grey10)
                        .clipShape(RoundedRectangle(cornerRadius: .radius3))

                    Button("Copy Key") {
                        CopyMessageFormatter.copyToClipboard(key)
                        ToastManager.shared.show("Copied", type: .success)
                    }
                    .buttonStyle(.bordered)
                }

                Button("I've Saved My Key") { viewModel.nextStep() }
                    .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                    .disabled(viewModel.recoveryKey == nil)
            }
            .padding(.spacing8)
            .task { await viewModel.generateRecoveryKey() }
        }
    }
}

struct SignupBackupCodesStep: View {
    @ObservedObject var viewModel: SignupViewModel

    var body: some View {
        ScrollView {
            VStack(spacing: .spacing6) {
                Text("Backup Codes")
                    .font(.omH2).fontWeight(.bold)

                Text("Use these one-time codes if you lose access to your 2FA device.")
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.center)

                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: .spacing2) {
                    ForEach(viewModel.backupCodes, id: \.self) { code in
                        Text(code)
                            .font(.system(.caption, design: .monospaced))
                            .padding(.spacing2)
                            .frame(maxWidth: .infinity)
                            .background(Color.grey10)
                            .clipShape(RoundedRectangle(cornerRadius: .radius2))
                    }
                }

                Button("Copy All Codes") {
                    CopyMessageFormatter.copyToClipboard(viewModel.backupCodes.joined(separator: "\n"))
                    ToastManager.shared.show("Copied", type: .success)
                }
                .buttonStyle(.bordered)

                Button("Continue") { viewModel.nextStep() }
                    .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                    .disabled(viewModel.backupCodes.isEmpty)
            }
            .padding(.spacing8)
            .task { await viewModel.generateBackupCodes() }
        }
    }
}

struct SignupPaymentStep: View {
    @ObservedObject var viewModel: SignupViewModel

    var body: some View {
        ScrollView {
            VStack(spacing: .spacing6) {
                Text("Add Credits")
                    .font(.omH2).fontWeight(.bold)

                Text("Credits are used for AI requests. You can always add more later.")
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.center)

                SettingsPricingView()
                    .frame(height: 400)

                Button("Add Credits") {
                    Task {
                        let url = await APIClient.shared.webAppURL.appendingPathComponent("signup/payment")
                        #if os(iOS)
                        await UIApplication.shared.open(url)
                        #elseif os(macOS)
                        NSWorkspace.shared.open(url)
                        #endif
                    }
                }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)

                Button("Skip for Now") { viewModel.nextStep() }
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
            }
            .padding(.spacing8)
        }
    }
}

struct SignupProfilePictureStep: View {
    @ObservedObject var viewModel: SignupViewModel

    var body: some View {
        ScrollView {
            VStack(spacing: .spacing6) {
                Text("Profile Picture")
                    .font(.omH2).fontWeight(.bold)

                SettingsProfilePictureView()
                    .frame(height: 300)

                Button("Continue") { viewModel.nextStep() }
                    .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)

                Button("Skip") { viewModel.nextStep() }
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
            }
            .padding(.spacing8)
        }
    }
}

struct SignupCompleteStep: View {
    let onFinish: () -> Void

    var body: some View {
        VStack(spacing: .spacing6) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 64)).foregroundStyle(.green)

            Text("Welcome to OpenMates!")
                .font(.omH2).fontWeight(.bold)

            Text("Your account is ready. Start chatting with AI.")
                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)

            Button("Get Started") { onFinish() }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
        }
        .padding(.spacing8)
    }
}
