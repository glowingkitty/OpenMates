// Account recovery — reset access via recovery key or backup code when locked out.
// Mirrors the web app's AccountRecovery.svelte: enter email, choose recovery method
// (recovery key or backup code), verify, reset password.
// VoiceOver: step change announcements, grouped method rows, accessible inputs.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/AccountRecovery.svelte
// CSS:     frontend/packages/ui/src/styles/auth.css
//          frontend/packages/ui/src/styles/fields.css (inputs)
//          frontend/packages/ui/src/styles/buttons.css (action buttons)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct AccountRecoveryView: View {
    @State private var step: RecoveryStep = .enterEmail
    @State private var email = ""
    @State private var recoveryKey = ""
    @State private var backupCode = ""
    @State private var newPassword = ""
    @State private var confirmPassword = ""
    @State private var isLoading = false
    @State private var error: String?

    enum RecoveryStep {
        case enterEmail
        case chooseMethod
        case enterRecoveryKey
        case enterBackupCode
        case resetPassword
        case complete
    }

    var body: some View {
        ScrollView {
            VStack(spacing: .spacing6) {
                switch step {
                case .enterEmail:
                    emailStep
                case .chooseMethod:
                    methodStep
                case .enterRecoveryKey:
                    recoveryKeyStep
                case .enterBackupCode:
                    backupCodeStep
                case .resetPassword:
                    resetPasswordStep
                case .complete:
                    completeStep
                }

                if let error {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                }
            }
            .padding(.spacing8)
        }
        .navigationTitle(LocalizationManager.shared.text("auth.account_recovery"))
    }

    // MARK: - Steps

    private var emailStep: some View {
        VStack(spacing: .spacing6) {
            Image(systemName: "person.crop.circle.badge.questionmark")
                .font(.system(size: 48)).foregroundStyle(Color.buttonPrimary)

            Text(LocalizationManager.shared.text("auth.recover_your_account"))
                .font(.omH2).fontWeight(.bold)

            Text(LocalizationManager.shared.text("auth.enter_email_for_recovery"))
                .font(.omSmall).foregroundStyle(Color.fontSecondary).multilineTextAlignment(.center)

            TextField(LocalizationManager.shared.text("auth.email"), text: $email)
                #if os(iOS)
                .keyboardType(.emailAddress)
                #endif
                .autocorrectionDisabled()
                #if os(iOS)
                .textInputAutocapitalization(.never)
                #endif
                .textFieldStyle(.roundedBorder)
                .accessibleInput(
                    LocalizationManager.shared.text("auth.email"),
                    hint: LocalizationManager.shared.text("auth.enter_account_email")
                )

            Button(LocalizationManager.shared.text("common.continue")) {
                step = .chooseMethod
                AccessibilityAnnouncement.screenChanged(LocalizationManager.shared.text("auth.choose_recovery_method"))
            }
            .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
            .disabled(email.isEmpty)
            .accessibleButton(LocalizationManager.shared.text("common.continue"), hint: LocalizationManager.shared.text("auth.proceed_to_recovery_method"))
        }
    }

    private var methodStep: some View {
        VStack(spacing: .spacing6) {
            Text(LocalizationManager.shared.text("auth.choose_recovery_method"))
                .font(.omH3).fontWeight(.bold)

            Button {
                step = .enterRecoveryKey
                AccessibilityAnnouncement.screenChanged(LocalizationManager.shared.text("auth.enter_recovery_key"))
            } label: {
                HStack {
                    Image(systemName: "key.horizontal").font(.title2).accessibilityHidden(true)
                    VStack(alignment: .leading) {
                        Text(AppStrings.recoveryKey).font(.omSmall).fontWeight(.medium)
                        Text(LocalizationManager.shared.text("auth.recovery_key_hint"))
                            .font(.omXs).foregroundStyle(Color.fontSecondary)
                    }
                    Spacer()
                    Image(systemName: "chevron.right").accessibilityHidden(true)
                }
                .padding().background(Color.grey10).clipShape(RoundedRectangle(cornerRadius: .radius4))
            }
            .buttonStyle(.plain)
            .accessibilityElement(children: .combine)
            .accessibleButton(AppStrings.recoveryKey, hint: LocalizationManager.shared.text("auth.recovery_key_hint"))

            Button {
                step = .enterBackupCode
                AccessibilityAnnouncement.screenChanged(LocalizationManager.shared.text("auth.enter_backup_code"))
            } label: {
                HStack {
                    Image(systemName: "number").font(.title2).accessibilityHidden(true)
                    VStack(alignment: .leading) {
                        Text(LocalizationManager.shared.text("auth.backup_code")).font(.omSmall).fontWeight(.medium)
                        Text(LocalizationManager.shared.text("auth.backup_code_hint"))
                            .font(.omXs).foregroundStyle(Color.fontSecondary)
                    }
                    Spacer()
                    Image(systemName: "chevron.right").accessibilityHidden(true)
                }
                .padding().background(Color.grey10).clipShape(RoundedRectangle(cornerRadius: .radius4))
            }
            .buttonStyle(.plain)
            .accessibilityElement(children: .combine)
            .accessibleButton(
                LocalizationManager.shared.text("auth.backup_code"),
                hint: LocalizationManager.shared.text("auth.backup_code_hint")
            )
        }
    }

    private var recoveryKeyStep: some View {
        VStack(spacing: .spacing6) {
            Text(LocalizationManager.shared.text("auth.enter_recovery_key"))
                .font(.omH3).fontWeight(.bold)

            TextEditor(text: $recoveryKey)
                .font(.system(.body, design: .monospaced))
                .frame(minHeight: 100)
                .padding(.spacing3).background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
                .accessibilityLabel(LocalizationManager.shared.text("auth.recovery_key"))
                .accessibilityHint(LocalizationManager.shared.text("auth.paste_recovery_key_here"))

            Button(LocalizationManager.shared.text("auth.verify")) { verifyRecoveryKey() }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                .disabled(recoveryKey.isEmpty || isLoading)
                .accessibleButton(LocalizationManager.shared.text("auth.verify"), hint: LocalizationManager.shared.text("auth.verify_recovery_key_hint"))
        }
    }

    private var backupCodeStep: some View {
        VStack(spacing: .spacing6) {
            Text(LocalizationManager.shared.text("auth.enter_backup_code"))
                .font(.omH3).fontWeight(.bold)

            TextField(LocalizationManager.shared.text("auth.backup_code"), text: $backupCode)
                .font(.system(.body, design: .monospaced)).autocorrectionDisabled()
                .textFieldStyle(.roundedBorder)
                .accessibleInput(
                    LocalizationManager.shared.text("auth.backup_code"),
                    hint: LocalizationManager.shared.text("auth.backup_code_format_hint")
                )

            Button(LocalizationManager.shared.text("auth.verify")) { verifyBackupCode() }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                .disabled(backupCode.isEmpty || isLoading)
                .accessibleButton(LocalizationManager.shared.text("auth.verify"), hint: LocalizationManager.shared.text("auth.verify_backup_code_hint"))
        }
    }

    private var resetPasswordStep: some View {
        VStack(spacing: .spacing6) {
            Text(LocalizationManager.shared.text("auth.set_new_password"))
                .font(.omH3).fontWeight(.bold)

            SecureField(LocalizationManager.shared.text("auth.password_min_chars"), text: $newPassword)
                .textContentType(.newPassword).textFieldStyle(.roundedBorder)
                .accessibleInput(LocalizationManager.shared.text("auth.new_password"), hint: LocalizationManager.shared.text("auth.password_min_chars_hint"))

            SecureField(LocalizationManager.shared.text("auth.confirm_password"), text: $confirmPassword)
                .textContentType(.newPassword).textFieldStyle(.roundedBorder)
                .accessibleInput(LocalizationManager.shared.text("auth.confirm_password"), hint: LocalizationManager.shared.text("auth.retype_new_password"))

            if !confirmPassword.isEmpty && newPassword != confirmPassword {
                Text(LocalizationManager.shared.text("auth.passwords_dont_match")).font(.omXs).foregroundStyle(Color.error)
                    .accessibilityLabel(LocalizationManager.shared.text("auth.passwords_dont_match"))
            }

            Button(LocalizationManager.shared.text("auth.reset_password")) { resetPassword() }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                .disabled(newPassword.count < 8 || newPassword != confirmPassword || isLoading)
                .accessibleButton(LocalizationManager.shared.text("auth.reset_password"), hint: LocalizationManager.shared.text("auth.save_new_password_hint"))
        }
    }

    private var completeStep: some View {
        VStack(spacing: .spacing6) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 48)).foregroundStyle(.green)
                .accessibilityHidden(true)
            Text(LocalizationManager.shared.text("auth.account_recovered")).font(.omH2).fontWeight(.bold)
            Text(LocalizationManager.shared.text("auth.password_reset_success"))
                .font(.omSmall).foregroundStyle(Color.fontSecondary).multilineTextAlignment(.center)
        }
        .accessibilityElement(children: .combine)
        .onAppear {
            AccessibilityAnnouncement.announce(LocalizationManager.shared.text("auth.account_recovered"))
        }
    }

    // MARK: - API calls

    private func verifyRecoveryKey() {
        isLoading = true; error = nil
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/auth/recover/verify-recovery-key",
                    body: ["email": email, "recovery_key": recoveryKey]
                )
                step = .resetPassword
                AccessibilityAnnouncement.screenChanged(LocalizationManager.shared.text("auth.set_new_password"))
            } catch {
                self.error = error.localizedDescription
                AccessibilityAnnouncement.announce(error.localizedDescription)
            }
            isLoading = false
        }
    }

    private func verifyBackupCode() {
        isLoading = true; error = nil
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/auth/recover/verify-backup-code",
                    body: ["email": email, "backup_code": backupCode]
                )
                step = .resetPassword
                AccessibilityAnnouncement.screenChanged(LocalizationManager.shared.text("auth.set_new_password"))
            } catch {
                self.error = error.localizedDescription
                AccessibilityAnnouncement.announce(error.localizedDescription)
            }
            isLoading = false
        }
    }

    private func resetPassword() {
        isLoading = true; error = nil
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/auth/recover/reset-password",
                    body: ["email": email, "new_password": newPassword]
                )
                step = .complete
            } catch {
                self.error = error.localizedDescription
                AccessibilityAnnouncement.announce(error.localizedDescription)
            }
            isLoading = false
        }
    }
}
