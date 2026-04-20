// Password + optional 2FA login screen. Mirrors PasswordAndTfaOtp.svelte.
// Shows password field first; if server returns tfaRequired, shows OTP field.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/PasswordAndTfaOtp.svelte
// CSS:     frontend/packages/ui/src/styles/auth.css
//          frontend/packages/ui/src/styles/fields.css (password input)
//          frontend/packages/ui/src/styles/buttons.css (login button)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct PasswordLoginView: View {
    @EnvironmentObject var authManager: AuthManager
    let email: String
    let tfaEnabled: Bool
    @Binding var stayLoggedIn: Bool
    let onRecoveryKey: () -> Void
    let onBackupCode: () -> Void

    @State private var password = ""
    @State private var tfaCode = ""
    @State private var showTfaField = false
    @State private var isLoading = false
    @State private var errorMessage: String?
    @FocusState private var focusedField: Field?

    enum Field {
        case password, tfa
    }

    var body: some View {
        VStack(spacing: .spacing6) {
            Text(AppStrings.enterPassword)
                .font(.omH3)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)

            Text(email)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)

            VStack(spacing: .spacing4) {
                SecureField(AppStrings.password, text: $password)
                    .textFieldStyle(OMTextFieldStyle())
                    .textContentType(.password)
                    .focused($focusedField, equals: .password)
                    .onSubmit {
                        if showTfaField { focusedField = .tfa }
                        else { performLogin() }
                    }
                    .accessibilityIdentifier("password-input")
                    .accessibleInput(AppStrings.password, hint: LocalizationManager.shared.text("auth.enter_account_password"))

                if showTfaField {
                    TextField(LocalizationManager.shared.text("auth.authenticator_code"), text: $tfaCode)
                        .textFieldStyle(OMTextFieldStyle())
                        #if os(iOS)
                        .keyboardType(.numberPad)
                        #endif
                        .focused($focusedField, equals: .tfa)
                        .onSubmit { performLogin() }
                        .transition(.move(edge: .top).combined(with: .opacity))
                        .accessibilityIdentifier("tfa-code-input")
                        .accessibleInput(
                            LocalizationManager.shared.text("auth.two_factor_code"),
                            hint: LocalizationManager.shared.text("auth.enter_6_digit_code")
                        )
                }

                if let errorMessage {
                    Text(errorMessage)
                        .font(.omXs)
                        .foregroundStyle(Color.error)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }

            Toggle(LocalizationManager.shared.text("auth.stay_logged_in"), isOn: $stayLoggedIn)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .tint(Color.buttonPrimary)
                .accessibleToggle(LocalizationManager.shared.text("auth.stay_logged_in"), isOn: stayLoggedIn)

            Button(action: performLogin) {
                Group {
                    if isLoading {
                        ProgressView()
                            .tint(.fontButton)
                    } else {
                        Text(AppStrings.login)
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(password.isEmpty || isLoading)
            .accessibilityIdentifier("login-button")
            .accessibleButton(AppStrings.login, hint: LocalizationManager.shared.text("auth.sign_in_to_account"))

            // Recovery options
            VStack(spacing: .spacing3) {
                Button(AppStrings.loginWithRecoveryKey) {
                    onRecoveryKey()
                }
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .accessibleButton(AppStrings.loginWithRecoveryKey, hint: LocalizationManager.shared.text("auth.use_recovery_key_instead"))

                if showTfaField {
                    Button(LocalizationManager.shared.text("auth.use_backup_code")) {
                        onBackupCode()
                    }
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .accessibleButton(
                        LocalizationManager.shared.text("auth.use_backup_code"),
                        hint: LocalizationManager.shared.text("auth.use_backup_code_instead")
                    )
                }
            }
            .padding(.top, .spacing2)
        }
        .onAppear {
            focusedField = .password
        }
    }

    private func performLogin() {
        guard !password.isEmpty else { return }
        isLoading = true
        errorMessage = nil

        Task {
            do {
                try await authManager.loginWithPassword(
                    email: email,
                    password: password,
                    tfaCode: showTfaField ? tfaCode : nil,
                    stayLoggedIn: stayLoggedIn
                )
            } catch AuthError.tfaRequired {
                withAnimation {
                    showTfaField = true
                    focusedField = .tfa
                }
                AccessibilityAnnouncement.announce(LocalizationManager.shared.text("auth.two_factor_required"))
            } catch let error as APIError {
                errorMessage = error.localizedDescription
            } catch {
                errorMessage = LocalizationManager.shared.text("auth.login_failed")
            }
            isLoading = false
        }
    }
}
