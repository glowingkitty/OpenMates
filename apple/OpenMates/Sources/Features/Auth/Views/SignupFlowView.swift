// Real password signup: basics → confirmation → security choice → password → login.
// Web sources: frontend/packages/ui/src/components/signup/Signup.svelte
//              signup/steps/confirmemail/ConfirmEmail{Top,Bottom}Content.svelte
//              signup/steps/secureaccount/SecureAccountTopContent.svelte
//              signup/steps/password/Password{Top,Bottom}Content.svelte
//              frontend/packages/ui/src/styles/{auth,fields,icons}.css
// Child metrics were measured in the rendered web preview at width390; the
// post-Basics parent card heights follow auth.css and still require parent QA.
import SwiftUI

struct SignupFlowView: View {
    var compact = true
    @EnvironmentObject private var authManager: AuthManager
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.openURL) private var openURL
    @StateObject private var model = SignupViewModel()
    var body: some View {
        NativeSignupForm(model: model, compact: compact, onOpenURL: { _ = openURL($0) })
            .task {
                let profile = ServerProfile.current()
                let sessionId = AuthManager.nativeSessionId
                model.configure(runtime: NativeSignupLiveRuntime.live(serverProfile: profile, authManager: authManager),
                    configuration: .init(inviteCode: nil,
                        language: LocalizationManager.shared.currentLanguage.code, darkmode: colorScheme == .dark),
                    login: { material, userId, password, form in
                        try await authManager.loginWithPassword(email: form.email, password: password,
                            userEmailSalt: material.request.userEmailSalt, stayLoggedIn: form.stayLoggedIn,
                            signupProof: .init(serverProfile: profile, sessionId: sessionId, expectedUserId: userId,
                                masterKey: material.masterKey, request: material.request))
                    })
                await model.loadRequirements()
            }
            .onDisappear { model.cancel() }
    }
}

// Production presentation shared verbatim with the isolated component fixture.
// Key only the two slide contents: their shared model and runtime must survive
// each transition. A disappearing slide must never cancel the signup session.
struct NativeSignupForm: View {
    @ObservedObject var model: SignupViewModel
    var compact = true
    let onOpenURL: (URL) -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var appeared = false

    var body: some View {
        VStack(spacing: 20) {
            if model.currentStep == .alphaDisclaimer {
                SignupAlphaDisclaimerStep(viewModel: model)
            } else if model.currentStep == .basics {
                basics
            } else if model.currentStep == .complete {
                Text(LocalizationManager.shared.text("signup.native_account_ready"))
                    .font(.omH2).accessibilityIdentifier("signup-account-ready")
            } else {
                VStack(spacing: 20) {
                    ZStack(alignment: .top) {
                        topContent
                            .id(model.currentStep)
                            .transition(slide)
                    }
                    .animation(reduceMotion ? nil : Animation(SignupCubicInOut()), value: model.currentStep)
                    .frame(maxWidth: .infinity)
                    .frame(height: model.currentStep == .secureAccount ? 600 : 380, alignment: .top)
                    .background(Color.grey0)
                    .clipShape(RoundedRectangle(cornerRadius: 18))
                    .shadow(color: .black.opacity(0.15), radius: 7.5, x: 0, y: 4)
                    .animation(heightAnimation, value: model.currentStep)
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("signup-top-card")
                    ZStack(alignment: .top) {
                        bottomContent
                            .id(model.currentStep)
                            .transition(slide)
                    }
                    .animation(reduceMotion ? nil : Animation(SignupCubicInOut()), value: model.currentStep)
                    .frame(maxWidth: .infinity)
                    .frame(height: model.currentStep == .secureAccount ? 0 : 260, alignment: .top)
                    .opacity(model.currentStep == .secureAccount ? 0 : 1)
                    .clipped()
                    .allowsHitTesting(model.currentStep != .secureAccount)
                    .accessibilityHidden(model.currentStep == .secureAccount)
                    .animation(heightAnimation, value: model.currentStep)
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("signup-bottom-region")
                }
                .animation(reduceMotion ? nil : Animation(SignupCubicInOut()), value: model.currentStep)
            }
            if let error = model.error, model.currentStep != .confirmEmail, model.currentStep != .password {
                Text(LocalizationManager.shared.text(error.localizationKey))
                    .font(.omSmall).foregroundStyle(Color.error)
                    .accessibilityIdentifier("signup-runtime-error")
            }
            #if DEBUG
            // Diagnostics do not add a stock progress bar or visible debug copy
            // above the reference layout. The state stays queryable by XCUITest.
            Text(String(describing: model.currentStep)).font(.system(size: 1))
                .foregroundStyle(Color.clear).frame(height: 1)
                .accessibilityIdentifier("signup-flow-state")
            #endif
        }
        .frame(maxWidth: .infinity)
        .opacity(appeared ? 1 : 0)
        .onAppear {
            withAnimation(reduceMotion ? nil : .linear(duration: 0.4)) { appeared = true }
        }
    }

    private var heightAnimation: Animation? {
        reduceMotion ? nil : .timingCurve(0.22, 1, 0.36, 1, duration: 0.6)
    }
    private var slide: AnyTransition {
        guard !reduceMotion else { return .opacity }
        return .asymmetric(insertion: .offset(x: model.transitionIsForward ? 100 : -100).combined(with: .opacity),
                           removal: .offset(x: model.transitionIsForward ? -100 : 100).combined(with: .opacity))
    }
    @ViewBuilder private var basics: some View {
        if model.requirements == nil {
            if model.isLoading { ProgressView().accessibilityIdentifier("signup-requirements-loading") }
            else {
                Button(LocalizationManager.shared.text("common.retry")) {
                    model.start { await model.loadRequirements() }
                }.buttonStyle(OMPrimaryButtonStyle()).accessibilityIdentifier("signup-requirements-retry")
            }
        } else {
            if model.requirements?.requiresInvite == true {
                TextField(LocalizationManager.shared.text("signup.enter_personal_invite_code"), text: $model.inviteCode)
                    .textFieldStyle(OMTextFieldStyle()).autocorrectionDisabled()
                    .disabled(model.basicsModel.loading).accessibilityIdentifier("signup-invite")
            }
            SignupBasicsFormView(model: model.basicsModel, compact: compact,
                onOpenURL: onOpenURL, onCodeRequested: model.acceptRequestedEmailCode)
        }
    }
    @ViewBuilder private var topContent: some View {
        switch model.currentStep {
        case .confirmEmail: SignupConfirmEmailStep(viewModel: model, onOpenURL: onOpenURL)
        case .secureAccount: SignupSecureAccountStep(viewModel: model, compact: compact)
        case .password: SignupPasswordStep(viewModel: model, compact: compact)
        case .passkeyPRFError: SignupPasskeyPRFErrorStep(viewModel: model, compact: compact)
        default: EmptyView()
        }
    }
    @ViewBuilder private var bottomContent: some View {
        switch model.currentStep {
        case .confirmEmail: SignupConfirmationInput(viewModel: model)
        case .password: SignupPasswordActions(viewModel: model, onOpenURL: onOpenURL)
        default: EmptyView()
        }
    }
}

// Svelte's cubicInOut is a piecewise cubic, not CSS ease-in-out. Use the same
// polynomial for the 400ms horizontal/opacity transition on both Apple platforms.
struct SignupCubicInOut: CustomAnimation {
    func animate<V: VectorArithmetic>(value: V, time: TimeInterval, context: inout AnimationContext<V>) -> V? {
        guard time < 0.4 else { return nil }
        let t = min(1, max(0, time / 0.4))
        let progress = t < 0.5 ? 4 * t * t * t : 1 - pow(-2 * t + 2, 3) / 2
        var result = value
        result.scale(by: progress)
        return result
    }
}

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
                alphaRow(icon: "project", text: LocalizationManager.shared.text("signup.is_alpha_disclaimer"))
                alphaRow(icon: "thumbsup", text: LocalizationManager.shared.text("signup.decent_stable"))
                alphaRow(icon: "task", text: LocalizationManager.shared.text("signup.not_all_core_features_implemented"))
                alphaRow(icon: "bug", text: LocalizationManager.shared.text("signup.expect_bugs_and_missing_features"))
                alphaRow(
                    icon: "github",
                    text: LocalizationManager.shared.text("signup.view_on_github"),
                    detail: LocalizationManager.shared.text("signup.view_on_github_description"),
                    isLink: true
                )
                alphaRow(
                    icon: "instagram",
                    text: LocalizationManager.shared.text("signup.view_on_instagram"),
                    detail: LocalizationManager.shared.text("signup.view_on_instagram_description"),
                    isLink: true
                )
            }

            Button {
                viewModel.continueFromDisclaimer()
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

    private func alphaRow(icon: String, text: String, detail: String? = nil, isLink: Bool = false) -> some View {
        HStack(alignment: .top, spacing: .spacing4) {
            Icon(icon, size: 24)
                .foregroundStyle(LinearGradient.primary)
                .frame(width: 28, height: 28)

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(text)
                    .font(.omP)
                    .fontWeight(.semibold)
                    .foregroundStyle(isLink ? AnyShapeStyle(LinearGradient.primary) : AnyShapeStyle(Color.fontPrimary))
                    .fixedSize(horizontal: false, vertical: true)

                if let detail {
                    Text(detail)
                        .font(.omSmall)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }
}

struct SignupConfirmEmailStep: View {
    @ObservedObject var viewModel: SignupViewModel
    let onOpenURL: (URL) -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var showBadge = false
    var body: some View {
        VStack(spacing: 0) {
            VStack(spacing: 16) {
                Icon("mail", size: 75).foregroundStyle(LinearGradient.primary)
                    .overlay(alignment: .topTrailing) {
                        Text("1").font(.custom("Lexend Deca", size: 24).weight(.medium))
                            .foregroundStyle(.white).frame(width: 35, height: 35)
                            .background(Color.buttonPrimary, in: Circle())
                            .shadow(color: .black.opacity(0.2), radius: 2, x: 0, y: 2)
                            .offset(x: 8, y: -8).opacity(showBadge ? 1 : 0)
                            .accessibilityHidden(true)
                    }
                    .accessibilityHidden(true)
                Text(LocalizationManager.shared.text("signup.you_received_a_one_time_code_via_email"))
                    .font(.omP).fontWeight(.medium).foregroundStyle(Color.grey80)
                    .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("signup-code-requested")
                Text(viewModel.email).font(.omP).fontWeight(.medium)
                    .foregroundStyle(LinearGradient.primary)
                    .accessibilityIdentifier("signup-requested-email")
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
            Button(LocalizationManager.shared.text("signup.open_mail_app")) {
                if let url = URL(string: "mailto:") { onOpenURL(url) }
            }.buttonStyle(.plain).font(.omP).fontWeight(.medium)
                .foregroundStyle(LinearGradient.primary).padding(.top, 20)
                .accessibilityIdentifier("signup-open-mail")
        }.padding(20).frame(maxWidth: .infinity, maxHeight: .infinity)
            .onAppear {
                withAnimation(reduceMotion ? nil : .linear(duration: 0.4).delay(0.8)) { showBadge = true }
            }
    }
}

private struct SignupConfirmationInput: View {
    @ObservedObject var viewModel: SignupViewModel
    @FocusState private var codeFocused: Bool
    var body: some View {
        VStack(spacing: 16) {
            HStack(spacing: 12) {
                Icon("2fa", size: 20).foregroundStyle(LinearGradient.primary)
                    .opacity(viewModel.isLoading ? 0 : 1).accessibilityHidden(true)
                TextField(LocalizationManager.shared.text("signup.enter_one_time_code"), text: $viewModel.verificationCode)
                    .textFieldStyle(.plain).textContentType(.oneTimeCode)
                    #if os(iOS)
                    .keyboardType(.numberPad)
                    #endif
                    .focused($codeFocused).disabled(viewModel.isLoading)
                    .accessibilityIdentifier("signup-confirmation-code")
                    .opacity(viewModel.isLoading ? 0 : 1)
                    .onChange(of: viewModel.verificationCode) { _, value in
                        let clean = String(value.filter { $0.isASCII && $0.isNumber }.prefix(6))
                        if value != clean { viewModel.verificationCode = clean; return }
                        if viewModel.canConfirmEmail { submit() }
                    }
                    .onSubmit(submit)
            }
            .modifier(SignupStepFieldChrome(focused: codeFocused,
                invalid: viewModel.error == .invalidEmailCode, background: .grey0))
            .accessibilityElement(children: .contain).accessibilityIdentifier("signup-code-field")
            .overlay {
                if viewModel.isLoading {
                    Text(LocalizationManager.shared.text("common.loading")).font(.omP).foregroundStyle(Color.grey80)
                        .accessibilityIdentifier("signup-confirmation-loading")
                }
            }
            .animation(.easeInOut(duration: 0.3), value: viewModel.isLoading)
            SignupStepRuntimeError(viewModel: viewModel)
        }.padding(24)
            #if os(macOS)
            .onAppear { codeFocused = true }
            #endif
    }
    private func submit() {
        guard viewModel.canConfirmEmail else { return }
        codeFocused = false
        viewModel.start { await viewModel.confirmEmail() }
    }
}

private struct SignupStepHeader: View {
    let icon: String
    let title: String
    let compact: Bool
    var body: some View {
        HStack(spacing: 16) {
            Icon(icon, size: compact ? 21 : 25).foregroundStyle(.white)
                .frame(width: compact ? 42 : 50, height: compact ? 42 : 50)
                .background(LinearGradient.primary, in: RoundedRectangle(cornerRadius: compact ? 10 : 14))
                .accessibilityHidden(true)
            Text(LocalizationManager.shared.text(title))
                .font(.custom("Lexend Deca", size: 24).weight(.bold)).foregroundStyle(Color.grey100)
                .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
        }.frame(maxWidth: .infinity)
    }
}

struct SignupSecureAccountStep: View {
    @ObservedObject var viewModel: SignupViewModel
    let compact: Bool
    var body: some View {
        VStack(spacing: 16) {
            SignupStepHeader(icon: "secret", title: "signup.secure_your_account", compact: compact)
                .padding(.top, 20).padding(.bottom, 4)
            Text(LocalizationManager.shared.text("signup.how_to_login"))
                .font(.omP).fontWeight(.medium).foregroundStyle(Color.grey60)
                .multilineTextAlignment(.center).padding(.bottom, 8)
            VStack(spacing: 16) {
                Button {
                    viewModel.start { await viewModel.registerPasskey() }
                } label: {
                    option(icon: "passkey", title: viewModel.passkeyCreationAttempted ? "signup.native_retry_login" : "signup.passkey",
                        description: viewModel.isLoading ? "common.loading" : "signup.passkey_descriptor")
                }.buttonStyle(.plain).disabled(!viewModel.canRegisterPasskey)
                    .overlay(RoundedRectangle(cornerRadius: 16).stroke(LinearGradient.primary, lineWidth: 3))
                    .overlay(alignment: .top) {
                        HStack(spacing: 5) {
                            Icon("thumbsup", size: 12)
                            Text(LocalizationManager.shared.text("signup.recommended")).font(.omXxs).fontWeight(.semibold)
                        }.foregroundStyle(.white).padding(.vertical, 4).padding(.horizontal, 10)
                            .background(LinearGradient.primary, in: Capsule())
                            .shadow(color: .black.opacity(0.2), radius: 4, x: 0, y: 2)
                            .offset(y: -12).accessibilityHidden(true)
                    }
                    .accessibilityIdentifier("signup-passkey-option")
                    .padding(.top, 10)
                Button(action: viewModel.selectPassword) {
                    option(icon: "password", title: "common.password", description: "signup.password_descriptor")
                }.buttonStyle(.plain).disabled(!viewModel.canChoosePassword)
                    .accessibilityIdentifier("signup-password-option")
            }
            if !viewModel.supportsPasskey {
                Text(LocalizationManager.shared.text("signup.passkey_prf_error_message"))
                    .font(.omSmall).foregroundStyle(Color.fontSecondary).multilineTextAlignment(.center)
                    .accessibilityIdentifier("signup-passkey-registration-boundary")
            }
            SignupStepRuntimeError(viewModel: viewModel)
            Spacer(minLength: 0)
        }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }
    private func option(icon: String, title: String, description: String) -> some View {
        VStack(spacing: 5) {
            HStack(spacing: 16) {
                Icon(icon, size: 30).foregroundStyle(LinearGradient.primary)
                    .frame(width: 48, height: 48)
                    .accessibilityHidden(true)
                Text(LocalizationManager.shared.text(title)).font(.omP).fontWeight(.semibold)
                    .foregroundStyle(Color.grey80).frame(maxWidth: .infinity)
            }
            Text(LocalizationManager.shared.text(description).replacingOccurrences(of: "\n", with: " ")).font(.omSmall).fontWeight(.medium)
                .foregroundStyle(Color.grey60).lineSpacing(2.5)
                .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
        }.padding(15).frame(maxWidth: .infinity)
            .background(Color.grey20, in: RoundedRectangle(cornerRadius: 16))
            .contentShape(RoundedRectangle(cornerRadius: 16))
    }
}

struct SignupPasskeyPRFErrorStep: View {
    @ObservedObject var viewModel: SignupViewModel
    let compact: Bool
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 16) {
                Icon("warning", size: compact ? 23 : 25).foregroundStyle(.white)
                    .frame(width: compact ? 43.05 : 50, height: compact ? 46 : 50)
                    .background(LinearGradient.primary, in: RoundedRectangle(cornerRadius: compact ? 10 : 14))
                    .accessibilityHidden(true)
                Text(LocalizationManager.shared.text("signup.passkey_prf_error_title"))
                    .font(.custom("Lexend Deca", size: 24).weight(.bold)).foregroundStyle(Color.grey100)
                    .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }.padding(.bottom, 30)
            VStack(spacing: 24) {
                Text(LocalizationManager.shared.text("signup.passkey_prf_error_message"))
                    .font(.omSmall).fontWeight(.medium).foregroundStyle(Color.grey70)
                    .lineSpacing(4.4).multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
                    .padding(12).frame(maxWidth: .infinity)
                    .background(Color(hex: 0xFF6B6B).opacity(0.15), in: RoundedRectangle(cornerRadius: 8))
                    .accessibilityIdentifier("signup-passkey-prf-error")
                Button(LocalizationManager.shared.text("common.continue"), action: viewModel.returnFromPasskeyError)
                    .buttonStyle(.plain).font(.omP).fontWeight(.semibold).foregroundStyle(.white)
                    .padding(.horizontal, 24).frame(height: 41)
                    .background(LinearGradient.primary, in: RoundedRectangle(cornerRadius: 8))
                    .accessibilityIdentifier("signup-passkey-prf-continue")
            }
        }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct SignupPasswordStep: View {
    @ObservedObject var viewModel: SignupViewModel
    var compact = true
    @FocusState private var focusedField: Field?
    @State private var displayedValidation = NativeSignupPasswordPolicy.validate(password: "", confirmation: "")
    private enum Field { case password, confirmation }
    var body: some View {
        VStack(spacing: 0) {
            SignupStepHeader(icon: "password", title: "common.password", compact: compact).padding(.bottom, 30)
            Text(LocalizationManager.shared.text("signup.advice"))
                .font(.omP).fontWeight(.semibold).foregroundStyle(Color.grey80)
                .accessibilityIdentifier("signup-password-advice")
            Text(LocalizationManager.shared.text("signup.use_your_password_manager").replacingOccurrences(of: "\n", with: " "))
                .font(.omSmall).fontWeight(.medium).foregroundStyle(Color.grey60)
                .lineSpacing(3).multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
            VStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 12) {
                        Icon("password", size: 20).foregroundStyle(LinearGradient.primary).accessibilityHidden(true)
                        SecureField(LocalizationManager.shared.text("login.password_placeholder"), text: $viewModel.password)
                            .textFieldStyle(.plain).textContentType(.newPassword)
                            .focused($focusedField, equals: .password).submitLabel(.next)
                            .onSubmit { focusedField = .confirmation }
                            .accessibilityIdentifier("signup-password")
                    }.modifier(SignupStepFieldChrome(focused: focusedField == .password,
                        invalid: displayedValidation.strengthErrorKey != nil, background: .grey20))
                        .accessibilityElement(children: .contain).accessibilityIdentifier("signup-password-field")
                    warning(displayedValidation.strengthErrorKey, identifier: "signup-password-validation")
                }
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 12) {
                        Icon("password", size: 20).foregroundStyle(LinearGradient.primary).accessibilityHidden(true)
                        SecureField(LocalizationManager.shared.text("signup.repeat_password"), text: $viewModel.confirmPassword)
                            .textFieldStyle(.plain).textContentType(.newPassword)
                            .focused($focusedField, equals: .confirmation).submitLabel(.go)
                            .onSubmit(submit).accessibilityIdentifier("signup-password-confirmation")
                    }.modifier(SignupStepFieldChrome(focused: focusedField == .confirmation,
                        invalid: displayedValidation.confirmationErrorKey != nil, background: .grey20))
                        .accessibilityElement(children: .contain).accessibilityIdentifier("signup-password-confirmation-field")
                    warning(displayedValidation.confirmationErrorKey, identifier: "signup-password-confirmation-validation")
                }
            }.frame(maxWidth: 400).disabled(viewModel.isLoading || viewModel.creationAttempted)
            Spacer(minLength: 0)
        }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .task(id: PasswordValidationInput(password: viewModel.password, confirmation: viewModel.confirmPassword)) {
                // Same 500ms feedback delay as PasswordTopContent. The submit
                // guard always validates immediately; debouncing cannot bypass it.
                do { try await Task.sleep(for: .milliseconds(500)) } catch { return }
                guard !Task.isCancelled else { return }
                withAnimation(.linear(duration: 0.15)) { displayedValidation = viewModel.passwordValidation }
            }
            #if os(macOS)
            .onAppear { focusedField = .password }
            #endif
    }
    @ViewBuilder private func warning(_ key: String?, identifier: String) -> some View {
        if let key, !viewModel.creationAttempted {
            Text(LocalizationManager.shared.text(key)).font(.omXs).foregroundStyle(Color.error)
                .padding(.horizontal, 4).fixedSize(horizontal: false, vertical: true)
                .transition(.opacity).accessibilityIdentifier(identifier)
        }
    }
    private func submit() {
        guard viewModel.canSubmitPassword else { return }
        focusedField = nil
        viewModel.start { await viewModel.setPassword() }
    }
    private struct PasswordValidationInput: Hashable { let password: String; let confirmation: String }
}

private struct SignupPasswordActions: View {
    @ObservedObject var viewModel: SignupViewModel
    let onOpenURL: (URL) -> Void
    var body: some View {
        VStack(spacing: 10) {
            Button {
                guard viewModel.canSubmitPassword else { return }
                viewModel.start { await viewModel.setPassword() }
            } label: {
                Text(LocalizationManager.shared.text(viewModel.isLoading ? "common.loading" :
                    viewModel.creationAttempted ? "signup.native_retry_login" : "common.continue"))
                    .frame(maxWidth: .infinity)
            }.buttonStyle(OMPrimaryButtonStyle()).disabled(!viewModel.canSubmitPassword)
                .accessibilityIdentifier("signup-create-password")
            SignupStepRuntimeError(viewModel: viewModel)
            VStack(spacing: 0) {
                Text(LocalizationManager.shared.text("signup.dont_have_password_manager_yet"))
                    .foregroundStyle(Color.grey60)
                Button(LocalizationManager.shared.text("signup.click_here_to_show_password_managers")) {
                    if let url = URL(string: "https://search.brave.com/search?q=best+password+manager") { onOpenURL(url) }
                }.buttonStyle(.plain).foregroundStyle(LinearGradient.primary)
                    .accessibilityIdentifier("signup-password-managers")
            }.font(.omSmall).fontWeight(.medium).multilineTextAlignment(.center)
        }.frame(maxWidth: 400).frame(maxWidth: .infinity)
    }
}

private struct SignupStepRuntimeError: View {
    @ObservedObject var viewModel: SignupViewModel
    var body: some View {
        if let error = viewModel.error {
            Text(LocalizationManager.shared.text(error.localizationKey))
                .font(.omSmall).foregroundStyle(Color.error)
                .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("signup-runtime-error")
        }
    }
}

private struct SignupStepFieldChrome: ViewModifier {
    let focused: Bool
    let invalid: Bool
    let background: Color
    func body(content: Content) -> some View {
        content.font(.omP).fontWeight(.medium).foregroundStyle(Color.grey100)
            .tint(Color.buttonPrimary).padding(.horizontal, 16).frame(height: 48)
            .background(background, in: Capsule())
            .overlay(Capsule().strokeBorder(invalid ? Color.error : focused ? Color.buttonPrimary : Color.grey0, lineWidth: 2))
            .shadow(color: focused ? Color.buttonPrimary.opacity(0.22) : .black.opacity(0.05), radius: focused ? 3 : 4, x: 0, y: focused ? 0 : 2)
            .animation(.easeOut(duration: 0.15), value: focused)
    }
}

extension NativeSignupError {
    var localizationKey: String {
        switch self {
        case .inviteRequired, .invalidInvite: "signup.native_invalid_invite"
        case .usernameUnavailable: "signup.native_username_unavailable"
        case .invalidEmailCode: "signup.native_invalid_email_code"
        case .verificationRequired: "signup.native_verification_required"
        case .creationUnconfirmed: "signup.native_creation_unconfirmed"
        case .alreadyAuthenticated, .staleContext: "signup.native_context_changed"
        case .passkeyUnsupported: "signup.passkey_prf_error_message"
        case .passkeyCancelled: "login.login_with_passkey"
        case .invalidPasskeyChallenge: "signup.native_request_failed"
        default: "signup.native_request_failed"
        }
    }
}
