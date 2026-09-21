// Shared production form pieces; no account, passkey, network or persistence service.
import SwiftUI

struct AuthLoginHeading: View {
    let compact: Bool
    var body: some View {
        VStack(spacing: 16) {
            Text(LocalizationManager.shared.text("login.login"))
                .font(.custom("Lexend Deca", size: compact ? 36 : 60).weight(.heavy))
                .foregroundStyle(LinearGradient.primary)
                .accessibilityIdentifier("login-heading")
            Text("\(LocalizationManager.shared.text("login.to_chat_to_your"))\n\(LocalizationManager.shared.text("login.digital_team_mates"))")
                .font(.custom("Lexend Deca", size: compact ? 24 : 30).weight(.bold))
                .multilineTextAlignment(.center).foregroundStyle(Color.fontPrimary)
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
        VStack(spacing: 10) {
            Text(LocalizationManager.shared.text("signup.sign_up"))
                .font(.custom("Lexend Deca", size: compact ? 36 : 60).weight(.heavy))
                .foregroundStyle(LinearGradient.primary)
            // Four production benefit items wrap at a narrow form width.
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 8) {
                ForEach(["signup.advantage_no_ads", "signup.advantage_no_subscription", "signup.advantage_privacy_focus", "signup.advantage_pay_per_use"], id: \.self) { key in
                    HStack(alignment: .top, spacing: 4) {
                        Icon("check", size: 14).foregroundStyle(LinearGradient.primary)
                        Text(LocalizationManager.shared.text(key)).font(.omSmall)
                    }
                }
            }.padding(.bottom, 10)
            emailInput
            warning(model.form.emailErrorKey, id: "signup-email-error")
            usernameInput
            warning(model.form.usernameErrorKey, id: "signup-username-error")
            consent("login.stay_logged_in", value: $model.form.stayLoggedIn, id: "signup-stay")
            consent("signup.subscribe_to_newsletter", value: $model.form.newsletter, id: "signup-newsletter")
            legalConsent("signup.terms_of_service", value: $model.form.termsAccepted, id: "signup-terms", path: "terms")
            legalConsent("signup.privacy_policy", value: $model.form.privacyAccepted, id: "signup-privacy", path: "privacy")
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
                    else { Text(LocalizationManager.shared.text("signup.create_new_account")) }
                }.frame(maxWidth: .infinity)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(!model.canSubmit).accessibilityIdentifier("signup-submit")
        }
        .frame(maxWidth: .infinity)
    }

    private var emailInput: some View {
        HStack(spacing: 12) {
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
        }.modifier(SignupInputChrome(hasError: model.form.emailErrorKey != nil))
            .disabled(model.loading)
    }

    private var usernameInput: some View {
        HStack(spacing: 12) {
            Icon("user", size: 20).foregroundStyle(LinearGradient.primary)
            TextField(LocalizationManager.shared.text("signup.enter_username"), text: $model.form.username)
                .textContentType(.username).autocorrectionDisabled()
                #if os(iOS)
                .textInputAutocapitalization(.never)
                #endif
                .focused($focusedField, equals: .username)
                .onSubmit { submit() }
                .accessibilityIdentifier("signup-username")
                .accessibilityLabel(AppStrings.username)
        }.modifier(SignupInputChrome(hasError: model.form.usernameErrorKey != nil))
            .disabled(model.loading)
    }

    @ViewBuilder private func warning(_ key: String?, id: String) -> some View {
        if let key {
            Text(LocalizationManager.shared.text(key)).font(.omXs).foregroundStyle(Color.error)
                .frame(maxWidth: .infinity, alignment: .leading).accessibilityIdentifier(id)
        }
    }
    private func legalConsent(_ key: String, value: Binding<Bool>, id: String, path: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            OMToggle(isOn: value, disabled: model.loading, accessibilityIdentifier: id)
                .accessibilityLabel(LocalizationManager.shared.text(key))
            VStack(alignment: .leading, spacing: 2) {
                Text(LocalizationManager.shared.text("signup.agree_to")).font(.omP)
                Button(LocalizationManager.shared.text(key)) {
                    if let url = URL(string: "https://openmates.org/legal/" + path) { onOpenURL(url) }
                }.buttonStyle(.plain).foregroundStyle(LinearGradient.primary)
                    .accessibilityIdentifier(id + "-link")
            }
            Spacer(minLength: 0)
        }
    }
    private func consent(_ key: String, value: Binding<Bool>, id: String) -> some View {
        HStack(spacing: 8) {
            OMToggle(isOn: value, disabled: model.loading, accessibilityIdentifier: id)
                .accessibilityLabel(LocalizationManager.shared.text(key))
            Button(LocalizationManager.shared.text(key)) { value.wrappedValue.toggle() }
                .buttonStyle(.plain).font(.omP).foregroundStyle(Color.fontPrimary)
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
    func body(content: Content) -> some View {
        content.font(.omP).padding(.horizontal, 16).frame(height: 48)
            .background(Color.grey0, in: Capsule())
            .overlay(Capsule().stroke(hasError ? Color.error : Color.grey30, lineWidth: 2))
    }
}
