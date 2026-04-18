// Account recovery — reset access via recovery key or backup code when locked out.
// Mirrors the web app's AccountRecovery.svelte: enter email, choose recovery method
// (recovery key or backup code), verify, reset password.

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
                .keyboardType(.emailAddress).autocorrectionDisabled()
                #if os(iOS)
                .textInputAutocapitalization(.never)
                #endif
                .textFieldStyle(.roundedBorder)

            Button(LocalizationManager.shared.text("common.continue")) { step = .chooseMethod }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                .disabled(email.isEmpty)
        }
    }

    private var methodStep: some View {
        VStack(spacing: .spacing6) {
            Text(LocalizationManager.shared.text("auth.choose_recovery_method"))
                .font(.omH3).fontWeight(.bold)

            Button {
                step = .enterRecoveryKey
            } label: {
                HStack {
                    Image(systemName: "key.horizontal").font(.title2)
                    VStack(alignment: .leading) {
                        Text(AppStrings.recoveryKey).font(.omSmall).fontWeight(.medium)
                        Text(LocalizationManager.shared.text("auth.recovery_key_hint"))
                            .font(.omXs).foregroundStyle(Color.fontSecondary)
                    }
                    Spacer()
                    Image(systemName: "chevron.right")
                }
                .padding().background(Color.grey10).clipShape(RoundedRectangle(cornerRadius: .radius4))
            }
            .buttonStyle(.plain)

            Button {
                step = .enterBackupCode
            } label: {
                HStack {
                    Image(systemName: "number").font(.title2)
                    VStack(alignment: .leading) {
                        Text(LocalizationManager.shared.text("auth.backup_code")).font(.omSmall).fontWeight(.medium)
                        Text(LocalizationManager.shared.text("auth.backup_code_hint"))
                            .font(.omXs).foregroundStyle(Color.fontSecondary)
                    }
                    Spacer()
                    Image(systemName: "chevron.right")
                }
                .padding().background(Color.grey10).clipShape(RoundedRectangle(cornerRadius: .radius4))
            }
            .buttonStyle(.plain)
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

            Button(LocalizationManager.shared.text("auth.verify")) { verifyRecoveryKey() }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                .disabled(recoveryKey.isEmpty || isLoading)
        }
    }

    private var backupCodeStep: some View {
        VStack(spacing: .spacing6) {
            Text(LocalizationManager.shared.text("auth.enter_backup_code"))
                .font(.omH3).fontWeight(.bold)

            TextField(LocalizationManager.shared.text("auth.backup_code"), text: $backupCode)
                .font(.system(.body, design: .monospaced)).autocorrectionDisabled()
                .textFieldStyle(.roundedBorder)

            Button(LocalizationManager.shared.text("auth.verify")) { verifyBackupCode() }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                .disabled(backupCode.isEmpty || isLoading)
        }
    }

    private var resetPasswordStep: some View {
        VStack(spacing: .spacing6) {
            Text(LocalizationManager.shared.text("auth.set_new_password"))
                .font(.omH3).fontWeight(.bold)

            SecureField(LocalizationManager.shared.text("auth.password_min_chars"), text: $newPassword)
                .textContentType(.newPassword).textFieldStyle(.roundedBorder)

            SecureField(LocalizationManager.shared.text("auth.confirm_password"), text: $confirmPassword)
                .textContentType(.newPassword).textFieldStyle(.roundedBorder)

            if !confirmPassword.isEmpty && newPassword != confirmPassword {
                Text(LocalizationManager.shared.text("auth.passwords_dont_match")).font(.omXs).foregroundStyle(Color.error)
            }

            Button(LocalizationManager.shared.text("auth.reset_password")) { resetPassword() }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                .disabled(newPassword.count < 8 || newPassword != confirmPassword || isLoading)
        }
    }

    private var completeStep: some View {
        VStack(spacing: .spacing6) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 48)).foregroundStyle(.green)
            Text(LocalizationManager.shared.text("auth.account_recovered")).font(.omH2).fontWeight(.bold)
            Text(LocalizationManager.shared.text("auth.password_reset_success"))
                .font(.omSmall).foregroundStyle(Color.fontSecondary).multilineTextAlignment(.center)
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
            } catch { self.error = error.localizedDescription }
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
            } catch { self.error = error.localizedDescription }
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
            } catch { self.error = error.localizedDescription }
            isLoading = false
        }
    }
}
