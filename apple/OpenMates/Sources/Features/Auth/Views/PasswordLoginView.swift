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
    let userEmailSalt: String?
    let tfaEnabled: Bool
    @Binding var stayLoggedIn: Bool
    let onRecoveryKey: () -> Void
    let onAnotherAccount: () -> Void
    let onAccountRecovery: () -> Void

    var body: some View {
        PasswordLoginForm(email: email, tfaEnabled: tfaEnabled,
            onRecoveryKey: onRecoveryKey, onAnotherAccount: onAnotherAccount,
            onAccountRecovery: onAccountRecovery, login: { password, code, codeType in
                try await authManager.loginWithPassword(email: email, password: password,
                    userEmailSalt: userEmailSalt, tfaCode: code, codeType: codeType,
                    stayLoggedIn: stayLoggedIn)
            })
    }
}

// Required callback preserves the existing password/OTP/backup state machine.
// The live wrapper is the only place that accesses AuthManager or credentials.
struct PasswordLoginForm: View {
    enum InitialStep { case password, otp }
    let email: String
    let tfaEnabled: Bool
    let onRecoveryKey: () -> Void
    let onAnotherAccount: () -> Void
    let onAccountRecovery: () -> Void
    let login: @MainActor (String, String?, String?) async throws -> Void
    var initialStep: InitialStep = .password

    @State private var password = ""
    @State private var tfaCode = ""
    @State private var showTfaField = false
    @State private var isBackupMode = false
    @State private var isLoading = false
    @State private var errorMessage: String?
    @FocusState private var focusedField: Field?

    enum Field {
        case password, tfa
    }

    private var isFormValid: Bool {
        guard !password.isEmpty else { return false }
        guard showTfaField else { return true }
        return isBackupMode ? tfaCode.count == 14 : tfaCode.count == 6
    }

    var body: some View {
        VStack(spacing: .spacing6) {
            Text(email)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .textSelection(.enabled)

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
                    .accessibleInput(AppStrings.password, hint: AppStrings.passwordPlaceholder)

                if showTfaField {
                    VStack(spacing: .spacing3) {
                        if !isBackupMode {
                            Text(AppStrings.checkYourTfaApp)
                                .font(.omSmall)
                                .foregroundStyle(Color.fontSecondary)
                                .multilineTextAlignment(.center)
                        } else {
                            Text(AppStrings.backupCodeIsSingleUse)
                                .font(.omSmall)
                                .foregroundStyle(Color.fontSecondary)
                                .multilineTextAlignment(.center)
                        }

                        TextField(tfaPlaceholder, text: $tfaCode)
                            .textFieldStyle(OMTextFieldStyle())
                            #if os(iOS)
                            .keyboardType(isBackupMode ? .asciiCapable : .numberPad)
                            .textInputAutocapitalization(.characters)
                            #endif
                            .autocorrectionDisabled(true)
                            .focused($focusedField, equals: .tfa)
                            .onChange(of: tfaCode) { _, newValue in
                                sanitizeTfaCode(newValue)
                            }
                            .onSubmit { performLogin() }
                            .transition(.move(edge: .top).combined(with: .opacity))
                            .accessibilityIdentifier("tfa-code-input")
                            .accessibleInput(tfaPlaceholder, hint: isBackupMode ? AppStrings.backupCodeIsSingleUse : AppStrings.checkYourTfaApp)
                    }
                }

                if let errorMessage {
                    Text(errorMessage)
                        .accessibilityIdentifier("password-login-error")
                        .font(.omXs)
                        .foregroundStyle(Color.error)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }

            Button(action: performLogin) {
                Group {
                    if isLoading {
                        ProgressView()
                            .tint(.fontButton)
                    } else {
                        Text(AppStrings.loginButton)
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(!isFormValid || isLoading)
            .accessibilityIdentifier("login-button")
            .accessibleButton(AppStrings.login, hint: LocalizationManager.shared.text("login.login_button"))

            loginOptionsContainer
                .padding(.top, .spacing3)
        }
        .onAppear {
            if initialStep == .otp { showTfaField = true }
            focusedField = .password
        }
    }

    private var loginOptionsContainer: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            loginOption(icon: "user", title: AppStrings.loginWithAnotherAccount, action: onAnotherAccount)
                .accessibilityIdentifier("login-another-account")

            if showTfaField {
                loginOption(
                    icon: isBackupMode ? "2fa" : "text",
                    title: isBackupMode ? AppStrings.loginWithTfaApp : AppStrings.loginWithBackupCode
                ) {
                    isBackupMode.toggle()
                    tfaCode = ""
                    focusedField = .tfa
                }
                .accessibilityIdentifier("login-code-mode")
            }

            loginOption(icon: "warning", title: AppStrings.loginWithRecoveryKey, action: onRecoveryKey)
                .accessibilityIdentifier("login-recovery-key")

            Rectangle()
                .fill(Color.grey30)
                .frame(height: 1)
                .padding(.top, .spacing2)
                .padding(.bottom, .spacing2)

            loginOption(icon: "warning", title: AppStrings.cantLogin, action: onAccountRecovery)
                .accessibilityIdentifier("login-account-recovery")
        }
        .fixedSize(horizontal: true, vertical: false)
        .frame(maxWidth: .infinity, alignment: .center)
    }

    private func loginOption(icon: String, title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: .spacing4) {
                Icon(icon, size: 22)
                    .foregroundStyle(LinearGradient.primary)
                Text(title)
                    .font(.omP)
                    .fontWeight(.medium)
                    .foregroundStyle(LinearGradient.primary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibleButton(title, hint: title)
    }

    private func performLogin() {
        guard isFormValid, !isLoading else { return }
        isLoading = true
        errorMessage = nil

        Task {
            do {
                try await login(password, showTfaField ? tfaCode : nil,
                    showTfaField ? (isBackupMode ? "backup" : "otp") : nil)
            } catch AuthError.tfaRequired {
                NativeDiagnostics.info("phase=passwordLogin.revealTFA", category: "auth")
                revealTfaField(passwordError: nil)
            } catch AuthError.invalidTwoFactorCode {
                errorMessage = AppStrings.codeWrong
                tfaCode = ""
                focusedField = .tfa
                AccessibilityAnnouncement.announce(AppStrings.codeWrong)
            } catch AuthError.invalidCredentials {
                NativeDiagnostics.warning("phase=passwordLogin.failed errorType=invalidCredentials", category: "auth")
                handlePasswordAuthFailure()
            } catch let error as APIError {
                NativeDiagnostics.warning("phase=passwordLogin.failed errorType=APIError", category: "auth")
                handlePasswordAuthFailure(fallback: error.localizedDescription)
            } catch {
                NativeDiagnostics.warning(
                    "phase=passwordLogin.failed errorType=\(type(of: error))",
                    category: "auth"
                )
                // Local unlock/storage failures are not an invalid password and
                // must not send the user into an unrelated OTP retry loop.
                errorMessage = error.localizedDescription
                AccessibilityAnnouncement.announce(errorMessage ?? AppStrings.loginFailed)
            }
            isLoading = false
        }
    }

    private var tfaPlaceholder: String {
        isBackupMode ? AppStrings.enterBackupCode : AppStrings.enterOneTimeCode
    }

    private func sanitizeTfaCode(_ rawValue: String) {
        let filtered = PasswordLoginInputPolicy.sanitizedCode(rawValue, backup: isBackupMode)
        if filtered != rawValue {
            tfaCode = filtered
        }
    }

    private func handlePasswordAuthFailure(fallback: String = AppStrings.emailOrPasswordWrong) {
        if showTfaField || tfaEnabled {
            // Mirrors PasswordAndTfaOtp.svelte anti-enumeration branch:
            // failed auth with/after a 2FA-required response keeps the OTP field visible.
            revealTfaField(passwordError: AppStrings.emailOrPasswordWrong)
        } else {
            errorMessage = fallback
        }
    }

    private func revealTfaField(passwordError: String?) {
        withAnimation {
            showTfaField = true
            errorMessage = passwordError
            focusedField = .tfa
        }
        AccessibilityAnnouncement.announce(AppStrings.checkYourTfaApp)
    }
}
