// Signup flow — multi-step registration matching the web app's Signup.svelte.
// Steps: basics (email) → confirm email → password → passkey → recovery key →
// backup codes → payment → profile picture → settings → complete.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/signup/Signup.svelte
//          frontend/packages/ui/src/components/signup/SignupNav.svelte
//          frontend/packages/ui/src/components/signup/SignupStatusbar.svelte
//          frontend/packages/ui/src/components/signup/steps/ (per-step components)
// CSS:     frontend/packages/ui/src/styles/auth.css
//          frontend/packages/ui/src/styles/fields.css (form inputs)
//          frontend/packages/ui/src/styles/buttons.css (continue/submit buttons)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import AuthenticationServices

// MARK: - Signup coordinator

struct SignupFlowView: View {
    @StateObject private var viewModel = SignupViewModel()
    @Environment(\.dismiss) var dismiss

    var body: some View {
        VStack(spacing: .spacing5) {
            SignupProgressBar(currentStep: viewModel.currentStep, totalSteps: viewModel.totalSteps)
                .accessibilityLabel("Step \(viewModel.currentStep.rawValue + 1) of \(viewModel.totalSteps)")
                .accessibilityValue(String(describing: viewModel.currentStep))

            Group {
                switch viewModel.currentStep {
                case .alphaDisclaimer:
                    SignupAlphaDisclaimerStep(viewModel: viewModel)
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
    }
}

// MARK: - View model

@MainActor
final class SignupViewModel: ObservableObject {
    @Published var currentStep: SignupStep = .alphaDisclaimer
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
        case alphaDisclaimer, basics, confirmEmail, password, passkey, recoveryKey, backupCodes, payment, profilePicture, complete
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
            AccessibilityAnnouncement.screenChanged("Check your email")
        } catch {
            self.error = error.localizedDescription
            AccessibilityAnnouncement.announce(error.localizedDescription)
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
            AccessibilityAnnouncement.screenChanged("Email verified. Set a password.")
        } catch {
            self.error = error.localizedDescription
            AccessibilityAnnouncement.announce(error.localizedDescription)
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
            AccessibilityAnnouncement.screenChanged("Password saved. Set up a passkey.")
        } catch {
            self.error = error.localizedDescription
            AccessibilityAnnouncement.announce(error.localizedDescription)
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

struct SignupAlphaDisclaimerStep: View {
    @ObservedObject var viewModel: SignupViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing6) {
            Text(AppStrings.signupVersionTitle)
                .font(.custom("Lexend Deca", size: 40).weight(.bold))
                .foregroundStyle(LinearGradient.primary)
                .frame(maxWidth: .infinity, alignment: .center)
                .padding(.vertical, .spacing2)

            VStack(alignment: .leading, spacing: .spacing5) {
                alphaRow(icon: "rocket", text: LocalizationManager.shared.text("signup.is_alpha_disclaimer"))
                alphaRow(icon: "thumbs-up", text: LocalizationManager.shared.text("signup.decent_stable"))
                alphaRow(icon: "check", text: LocalizationManager.shared.text("signup.not_all_core_features_implemented"))
                alphaRow(icon: "bug", text: LocalizationManager.shared.text("signup.expect_bugs_and_missing_features"))
                alphaRow(icon: "asset:github", text: LocalizationManager.shared.text("signup.view_on_github"))
            }

            Button {
                viewModel.nextStep()
            } label: {
                Text(
                    LocalizationManager.shared
                        .text("signup.continue_with_alpha")
                        .replacingOccurrences(of: "{version}", with: AppStrings.signupVersionTitle)
                )
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .padding(.top, .spacing2)
        }
    }

    private func alphaRow(icon: String, text: String) -> some View {
        HStack(alignment: .top, spacing: .spacing4) {
            if icon.hasPrefix("asset:") {
                Icon(String(icon.dropFirst(6)), size: 22)
                    .foregroundStyle(LinearGradient.primary)
                    .frame(width: 28, height: 28)
            } else {
                LucideNativeIcon(icon, size: 22)
                    .foregroundStyle(LinearGradient.primary)
                    .frame(width: 28, height: 28)
            }

            Text(text)
                .font(.omP)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

struct SignupBasicsStep: View {
    @ObservedObject var viewModel: SignupViewModel

    var body: some View {
        ScrollView {
            VStack(spacing: .spacing6) {
                Text(LocalizationManager.shared.text("signup.create_new_account"))
                    .font(.omH2).fontWeight(.bold)

                TextField(LocalizationManager.shared.text("login.email_placeholder"), text: $viewModel.email)
                    #if os(iOS)
                    .keyboardType(.emailAddress)
                    #endif
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
                    .textContentType(.emailAddress)
                    .textFieldStyle(OMTextFieldStyle())
                    .accessibleInput(LocalizationManager.shared.text("login.email_placeholder"), hint: LocalizationManager.shared.text("login.email_placeholder"))

                TextField(AppStrings.username, text: $viewModel.username)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
                    .textFieldStyle(OMTextFieldStyle())
                    .accessibleInput(AppStrings.username, hint: LocalizationManager.shared.text("signup.enter_username"))

                if let error = viewModel.error {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                        .accessibilityLabel(error)
                }

                Button {
                    Task { await viewModel.registerBasics() }
                } label: {
                    HStack {
                        Spacer()
                        if viewModel.isLoading { ProgressView() } else { Text(LocalizationManager.shared.text("common.continue")) }
                        Spacer()
                    }
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(viewModel.email.isEmpty || viewModel.username.isEmpty || viewModel.isLoading)
                .accessibleButton(LocalizationManager.shared.text("common.continue"), hint: LocalizationManager.shared.text("signup.create_new_account"))
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

                Text(LocalizationManager.shared.text("signup.you_received_a_one_time_code_via_email"))
                    .font(.omH2).fontWeight(.bold)

                Text(viewModel.email)
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.center)

                TextField(LocalizationManager.shared.text("signup.enter_one_time_code"), text: $viewModel.verificationCode)
                    #if os(iOS)
                    .keyboardType(.numberPad)
                    #endif
                    .textFieldStyle(.roundedBorder)
                    .multilineTextAlignment(.center)
                    .font(.system(.title2, design: .monospaced))
                    .accessibleInput(
                        LocalizationManager.shared.text("signup.enter_one_time_code"),
                        hint: LocalizationManager.shared.text("signup.you_received_a_one_time_code_via_email")
                    )

                if let error = viewModel.error {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                        .accessibilityLabel(error)
                }

                Button {
                    Task { await viewModel.confirmEmail() }
                } label: {
                    HStack { Spacer(); Text(LocalizationManager.shared.text("common.continue")); Spacer() }
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(viewModel.verificationCode.isEmpty || viewModel.isLoading)
                .accessibleButton(LocalizationManager.shared.text("common.continue"), hint: LocalizationManager.shared.text("signup.enter_one_time_code"))
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
                Text(LocalizationManager.shared.text("signup.create_password"))
                    .font(.omH2).fontWeight(.bold)

                SecureField(LocalizationManager.shared.text("signup.create_password"), text: $viewModel.password)
                    .textContentType(.newPassword).textFieldStyle(OMTextFieldStyle())
                    .accessibleInput(LocalizationManager.shared.text("signup.password"), hint: LocalizationManager.shared.text("signup.create_password"))

                SecureField(LocalizationManager.shared.text("signup.confirm_password"), text: $viewModel.confirmPassword)
                    .textContentType(.newPassword).textFieldStyle(OMTextFieldStyle())
                    .accessibleInput(LocalizationManager.shared.text("signup.confirm_password"), hint: LocalizationManager.shared.text("signup.repeat_password"))

                if !viewModel.confirmPassword.isEmpty && !passwordsMatch {
                    Text(LocalizationManager.shared.text("signup.passwords_do_not_match"))
                        .font(.omXs).foregroundStyle(Color.error)
                        .accessibilityLabel(LocalizationManager.shared.text("signup.passwords_do_not_match"))
                }

                if let error = viewModel.error {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                        .accessibilityLabel(error)
                }

                Button {
                    Task { await viewModel.setPassword() }
                } label: {
                    HStack { Spacer(); Text(LocalizationManager.shared.text("common.continue")); Spacer() }
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(!isValid || viewModel.isLoading)
                .accessibleButton(LocalizationManager.shared.text("common.continue"), hint: LocalizationManager.shared.text("signup.create_password"))
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
                LucideNativeIcon("key-round", size: 48)
                    .foregroundStyle(Color.buttonPrimary)

                Text(LocalizationManager.shared.text("signup.passkey_instruction_title"))
                    .font(.omH2).fontWeight(.bold)

                Text(LocalizationManager.shared.text("signup.passkey_instruction_text"))
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.center)

                Button(LocalizationManager.shared.text("signup.create_passkey")) {
                    // Passkey registration via ASAuthorizationController
                    viewModel.nextStep()
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .accessibleButton(
                    LocalizationManager.shared.text("signup.create_passkey"),
                    hint: LocalizationManager.shared.text("signup.passkey_instruction_text")
                )

                Button(LocalizationManager.shared.text("signup.skip_for_now")) { viewModel.nextStep() }
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .accessibleButton(
                        LocalizationManager.shared.text("signup.skip_for_now"),
                        hint: LocalizationManager.shared.text("signup.skip_for_now")
                    )
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

                Text(LocalizationManager.shared.text("auth.save_your_recovery_key"))
                    .font(.omH2).fontWeight(.bold)

                Text(LocalizationManager.shared.text("auth.recovery_key_description"))
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.center)

                if let key = viewModel.recoveryKey {
                    Text(key)
                        .font(.system(.body, design: .monospaced))
                        .textSelection(.enabled)
                        .padding(.spacing4)
                        .background(Color.grey10)
                        .clipShape(RoundedRectangle(cornerRadius: .radius3))
                        .accessibilityLabel(LocalizationManager.shared.text("auth.recovery_key"))
                        .accessibilityValue(key)
                        .accessibilityHint(LocalizationManager.shared.text("auth.double_tap_to_select"))

                    Button(LocalizationManager.shared.text("auth.copy_key")) {
                        CopyMessageFormatter.copyToClipboard(key)
                        ToastManager.shared.show(AppStrings.copied, type: .success)
                        AccessibilityAnnouncement.announce(AppStrings.copied)
                    }
                    .buttonStyle(.bordered)
                    .accessibleButton(LocalizationManager.shared.text("auth.copy_key"), hint: LocalizationManager.shared.text("auth.copy_recovery_key_hint"))
                }

                Button(LocalizationManager.shared.text("auth.ive_saved_my_key")) { viewModel.nextStep() }
                    .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                    .disabled(viewModel.recoveryKey == nil)
                    .accessibleButton(LocalizationManager.shared.text("auth.ive_saved_my_key"), hint: LocalizationManager.shared.text("auth.confirm_key_saved_hint"))
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
                Text(LocalizationManager.shared.text("auth.backup_codes"))
                    .font(.omH2).fontWeight(.bold)

                Text(LocalizationManager.shared.text("auth.backup_codes_description"))
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

                Button(LocalizationManager.shared.text("auth.copy_all_codes")) {
                    CopyMessageFormatter.copyToClipboard(viewModel.backupCodes.joined(separator: "\n"))
                    ToastManager.shared.show(AppStrings.copied, type: .success)
                    AccessibilityAnnouncement.announce(AppStrings.copied)
                }
                .buttonStyle(.bordered)
                .accessibleButton(LocalizationManager.shared.text("auth.copy_all_codes"), hint: LocalizationManager.shared.text("auth.copy_all_backup_codes_hint"))

                Button(LocalizationManager.shared.text("common.continue")) { viewModel.nextStep() }
                    .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                    .disabled(viewModel.backupCodes.isEmpty)
                    .accessibleButton(LocalizationManager.shared.text("common.continue"), hint: LocalizationManager.shared.text("auth.continue_after_saving_codes"))
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
                Text(LocalizationManager.shared.text("auth.add_credits"))
                    .font(.omH2).fontWeight(.bold)

                Text(LocalizationManager.shared.text("auth.credits_description"))
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.center)

                SettingsPricingView()
                    .frame(height: 400)

                Button(LocalizationManager.shared.text("auth.add_credits")) {
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
                .accessibleButton(LocalizationManager.shared.text("auth.add_credits"), hint: LocalizationManager.shared.text("auth.opens_payment_in_browser"))

                Button(LocalizationManager.shared.text("common.skip_for_now")) { viewModel.nextStep() }
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .accessibleButton(LocalizationManager.shared.text("common.skip_for_now"), hint: LocalizationManager.shared.text("auth.skip_payment_hint"))
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
                Text(AppStrings.profilePicture)
                    .font(.omH2).fontWeight(.bold)

                SettingsProfilePictureView()
                    .frame(height: 300)

                Button(LocalizationManager.shared.text("common.continue")) { viewModel.nextStep() }
                    .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                    .accessibleButton(LocalizationManager.shared.text("common.continue"), hint: LocalizationManager.shared.text("auth.continue_with_profile_picture"))

                Button(AppStrings.skip) { viewModel.nextStep() }
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .accessibleButton(AppStrings.skip, hint: LocalizationManager.shared.text("auth.skip_profile_picture_hint"))
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
                .accessibilityHidden(true)

            Text(LocalizationManager.shared.text("auth.welcome_to_openmates"))
                .font(.omH2).fontWeight(.bold)

            Text(LocalizationManager.shared.text("auth.account_ready"))
                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)

            Button(LocalizationManager.shared.text("auth.get_started")) { onFinish() }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                .accessibleButton(LocalizationManager.shared.text("auth.get_started"), hint: LocalizationManager.shared.text("auth.open_app_hint"))
        }
        .padding(.spacing8)
        .onAppear {
            AccessibilityAnnouncement.announce(LocalizationManager.shared.text("auth.account_ready"))
        }
    }
}
