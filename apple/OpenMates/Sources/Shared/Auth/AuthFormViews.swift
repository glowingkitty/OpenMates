// Shared production form pieces; no account, passkey, network or persistence service.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/Login.svelte
//         frontend/packages/ui/src/components/signup/steps/basics/Basics.svelte
// CSS:    frontend/packages/ui/src/styles/auth.css (.form-container, .agreement-row)
//         frontend/packages/ui/src/styles/fields.css
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift,
//         TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/auth/specification.yml
// Assertions: auth.login.method-convergence, auth.surface.first-party-boundary
import SwiftUI

struct AuthLoginHeading: View {
    let compact: Bool
    var body: some View {
        VStack(spacing: compact ? .spacing2 : .spacing4) {
            Text(AppStrings.login)
                .font(.custom("Lexend Deca", size: compact ? 36 : 60).weight(.heavy))
                .foregroundStyle(LinearGradient.primary)
                .accessibilityIdentifier("login-heading")
            VStack(spacing: 0) {
                Text(AppStrings.toChatToYour).foregroundStyle(Color.fontPrimary)
                Text(AppStrings.digitalTeamMates).foregroundStyle(LinearGradient.primary)
            }
            .font(compact ? .custom("Lexend Deca", size: 24).weight(.bold) : .omH2.weight(.bold))
            .multilineTextAlignment(.center)
        }
    }
}

struct SignupBasicsFormView: View {
    @ObservedObject var model: SignupBasicsFormModel
    var compact = true
    let onOpenURL: (URL) -> Void
    let onCodeRequested: (SignupBasicsForm) -> Void
    @FocusState private var focusedField: Field?
    private enum Field { case email, username }

    var body: some View {
        VStack(spacing: 0) {
            Text(AppStrings.signup)
                .font(.custom("Lexend Deca", size: compact ? 36 : 60).weight(.heavy))
                .foregroundStyle(LinearGradient.primary)
                .padding(.bottom, compact ? .spacing2 : .spacing4)
            // Basics.svelte .advantages-list: four left-aligned rows in a
            // centered fit-content block, 17.6px bold type and 20px check icons.
            VStack(alignment: .leading, spacing: .spacing5) {
                ForEach(Array(AppStrings.signupAdvantages.enumerated()), id: \.offset) { index, title in
                    HStack(spacing: .spacing5) {
                        Icon("check", size: 20).foregroundStyle(Color.success)
                        Text(title).font(.custom("Lexend Deca", size: 17.6).weight(.bold))
                            .foregroundStyle(Color.fontPrimary)
                            .accessibilityIdentifier("signup-advantage-\(index)")
                    }
                }
            }
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity)
            .padding(.bottom, .spacing12 + .spacing20)
            emailInput
                .padding(.bottom, .spacing5)
            warning(model.form.emailErrorKey, id: "signup-email-error")
            usernameInput
                .padding(.bottom, .spacing5)
            warning(model.form.usernameErrorKey, id: "signup-username-error")
            VStack(spacing: .spacing4) {
                consent(AppStrings.stayLoggedIn, value: $model.form.stayLoggedIn, id: "signup-stay")
                consent(AppStrings.signupNewsletter, value: $model.form.newsletter, id: "signup-newsletter")
                legalConsent(AppStrings.signupTerms, value: $model.form.termsAccepted, id: "signup-terms", path: "terms")
                legalConsent(AppStrings.signupPrivacy, value: $model.form.privacyAccepted, id: "signup-privacy", path: "privacy")
            }
            .frame(maxWidth: 330)
            if !model.isAvailable {
                Text(LocalizationManager.shared.text("signup.native_setup_unavailable"))
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("signup-unavailable")
            }
            if model.error != nil {
                Text(LocalizationManager.shared.text("signup.native_request_failed"))
                    .font(.omSmall).foregroundStyle(Color.error)
                    .accessibilityIdentifier("auth-form-error")
            }
            Button(action: submit) {
                Group {
                    if model.loading { ProgressView().tint(.fontButton) }
                    else { Text(AppStrings.signupCreateAccount) }
                }.frame(maxWidth: .infinity)
            }
            .buttonStyle(AuthPrimaryButtonStyle())
            .padding(.top, .spacing12)
            .disabled(!model.canSubmit).accessibilityIdentifier("signup-submit")
        }
        .frame(maxWidth: .infinity)
    }

    private var emailInput: some View {
        HStack(spacing: .spacing6) {
            Icon("mail", size: 20).foregroundStyle(LinearGradient.primary)
            TextField(AppStrings.emailPlaceholder, text: $model.form.email)
                .textContentType(.emailAddress).autocorrectionDisabled()
                #if os(iOS)
                .keyboardType(.emailAddress).textInputAutocapitalization(.never)
                #endif
                .focused($focusedField, equals: .email)
                .onChange(of: model.form.email) { _, _ in model.form.suggestUsernameIfEmpty() }
                .onSubmit { focusedField = .username }
                .accessibilityIdentifier("signup-email")
                .accessibilityLabel(AppStrings.emailPlaceholder)
        }.modifier(SignupInputChrome(hasError: model.form.emailErrorKey != nil, isFocused: focusedField == .email))
            .disabled(model.loading)
    }

    private var usernameInput: some View {
        HStack(spacing: .spacing6) {
            Icon("user", size: 20).foregroundStyle(LinearGradient.primary)
            TextField(AppStrings.signupEnterUsername, text: $model.form.username)
                .textContentType(.username).autocorrectionDisabled()
                #if os(iOS)
                .textInputAutocapitalization(.never)
                #endif
                .focused($focusedField, equals: .username)
                .onSubmit { submit() }
                .accessibilityIdentifier("signup-username")
                .accessibilityLabel(AppStrings.username)
        }.modifier(SignupInputChrome(hasError: model.form.usernameErrorKey != nil, isFocused: focusedField == .username))
            .disabled(model.loading)
    }

    @ViewBuilder private func warning(_ key: String?, id: String) -> some View {
        if let key {
            Text(LocalizationManager.shared.text(key)).font(.omXs).foregroundStyle(Color.error)
                .frame(maxWidth: .infinity, alignment: .leading).accessibilityIdentifier(id)
        }
    }
    private func legalConsent(_ title: String, value: Binding<Bool>, id: String, path: String) -> some View {
        HStack(spacing: .spacing4) {
            OMToggle(isOn: value, disabled: model.loading, accessibilityIdentifier: id)
                .accessibilityLabel(title)
            ViewThatFits(in: .horizontal) {
                HStack(spacing: .spacing2) {
                    Text(AppStrings.signupAgreeTo).foregroundStyle(Color.grey60)
                    legalLink(title, id: id, path: path)
                }
                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(AppStrings.signupAgreeTo).foregroundStyle(Color.grey60)
                    legalLink(title, id: id, path: path)
                }
            }
            .font(.omP)
            Spacer(minLength: 0)
        }
    }
    private func legalLink(_ title: String, id: String, path: String) -> some View {
        Button(title) {
            if let url = URL(string: "https://openmates.org/legal/" + path) { onOpenURL(url) }
        }.buttonStyle(.plain).foregroundStyle(LinearGradient.primary)
            .accessibilityIdentifier(id + "-link")
    }
    private func consent(_ title: String, value: Binding<Bool>, id: String) -> some View {
        HStack(spacing: .spacing4) {
            OMToggle(isOn: value, disabled: model.loading, accessibilityIdentifier: id)
                .accessibilityLabel(title)
            Button { value.wrappedValue.toggle() } label: {
                Text(title).font(.omP).foregroundStyle(Color.grey60)
                    .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
            }
                .buttonStyle(.plain)
                .disabled(model.loading).accessibilityIdentifier(id + "-label")
            Spacer(minLength: 0)
        }
    }
    private func submit() {
        guard model.canSubmit else { return }
        focusedField = nil
        Task {
            if let form = await model.submit() { onCodeRequested(form) }
        }
    }
}

private struct SignupInputChrome: ViewModifier {
    let hasError: Bool
    let isFocused: Bool
    func body(content: Content) -> some View {
        content.font(.omP).padding(.horizontal, .spacing8).frame(height: .spacing24)
            .frame(maxWidth: 350)
            .background(Color.grey0, in: Capsule())
            .overlay(Capsule().stroke(hasError ? Color.error : isFocused ? Color.buttonPrimary : Color.grey0, lineWidth: 2))
            .shadow(color: isFocused ? Color.buttonPrimary.opacity(0.22) : .clear, radius: 3)
            .shadow(color: .black.opacity(0.08), radius: 6, x: 0, y: 4)
            .tint(Color.buttonPrimary)
    }
}

// Auth.css + buttons.css compute a 50px auth action, 20px corners and 0.7
// disabled opacity. Keep this scoped; other product buttons retain their metrics.
struct AuthPrimaryButtonStyle: ButtonStyle {
    var expands = true
    @Environment(\.isEnabled) private var isEnabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.omP).fontWeight(.medium)
            .foregroundStyle(Color.fontButton)
            .padding(.horizontal, expands ? 0 : 30)
            .frame(maxWidth: expands ? 350 : nil).frame(height: 50)
            .background(configuration.isPressed ? Color.buttonPrimaryPressed : Color.buttonPrimary)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
            .opacity(isEnabled ? 1 : 0.7)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.easeInOut(duration: 0.15), value: configuration.isPressed)
            .omClickablePointer()
    }
}

// Auth-specific accessors reuse existing web translations; this extension keeps
// the auth presentation change independent of the shared account/localization work.
extension AppStrings {
    static var authDemo: String { LocalizationManager.shared.text("login.demo") }
    static var authContinue: String { LocalizationManager.shared.text("common.continue") }
    static var authOr: String { LocalizationManager.shared.text("login.or") }
    static var authPasskeyOption: String { LocalizationManager.shared.text("login.login_with_passkey") }
    static var authPairOption: String { LocalizationManager.shared.text("login.login_with_phone_or_pc") }
    static var signupNewsletter: String { LocalizationManager.shared.text("signup.subscribe_to_newsletter") }
    static var signupTerms: String { LocalizationManager.shared.text("signup.terms_of_service") }
    static var signupPrivacy: String { LocalizationManager.shared.text("signup.privacy_policy") }
    static var signupAgreeTo: String { LocalizationManager.shared.text("signup.agree_to") }
    static var signupEnterUsername: String { LocalizationManager.shared.text("signup.enter_username") }
    static var signupCreateAccount: String { LocalizationManager.shared.text("signup.create_new_account") }
    static var signupAlphaDescription: String { LocalizationManager.shared.text("signup.is_alpha_disclaimer") }
    static var signupAlphaStable: String { LocalizationManager.shared.text("signup.decent_stable") }
    static var signupAlphaIncomplete: String { LocalizationManager.shared.text("signup.not_all_core_features_implemented") }
    static var signupAlphaBugs: String { LocalizationManager.shared.text("signup.expect_bugs_and_missing_features") }
    static var signupGitHub: String { LocalizationManager.shared.text("signup.view_on_github") }
    static var signupGitHubDescription: String { LocalizationManager.shared.text("signup.view_on_github_description") }
    static var signupInstagram: String { LocalizationManager.shared.text("signup.view_on_instagram") }
    static var signupInstagramDescription: String { LocalizationManager.shared.text("signup.view_on_instagram_description") }
    static var signupContinueWithAlpha: String {
        LocalizationManager.shared.text("signup.continue_with_alpha", replacements: ["version": signupVersionTitle])
    }
    static var signupAdvantages: [String] {
        ["signup.advantage_no_ads", "signup.advantage_no_subscription", "signup.advantage_privacy_focus", "signup.advantage_pay_per_use"]
            .map { LocalizationManager.shared.text($0) }
    }
}
