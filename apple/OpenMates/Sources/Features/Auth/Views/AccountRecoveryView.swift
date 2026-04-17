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
        .navigationTitle("Account Recovery")
    }

    // MARK: - Steps

    private var emailStep: some View {
        VStack(spacing: .spacing6) {
            Image(systemName: "person.crop.circle.badge.questionmark")
                .font(.system(size: 48)).foregroundStyle(Color.buttonPrimary)

            Text("Recover Your Account")
                .font(.omH2).fontWeight(.bold)

            Text("Enter the email address associated with your account.")
                .font(.omSmall).foregroundStyle(Color.fontSecondary).multilineTextAlignment(.center)

            TextField("Email", text: $email)
                .keyboardType(.emailAddress).autocorrectionDisabled()
                #if os(iOS)
                .textInputAutocapitalization(.never)
                #endif
                .textFieldStyle(.roundedBorder)

            Button("Continue") { step = .chooseMethod }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                .disabled(email.isEmpty)
        }
    }

    private var methodStep: some View {
        VStack(spacing: .spacing6) {
            Text("Choose Recovery Method")
                .font(.omH3).fontWeight(.bold)

            Button {
                step = .enterRecoveryKey
            } label: {
                HStack {
                    Image(systemName: "key.horizontal").font(.title2)
                    VStack(alignment: .leading) {
                        Text("Recovery Key").font(.omSmall).fontWeight(.medium)
                        Text("The 24-word key you saved during signup")
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
                        Text("Backup Code").font(.omSmall).fontWeight(.medium)
                        Text("One of the one-time codes you saved")
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
            Text("Enter Recovery Key")
                .font(.omH3).fontWeight(.bold)

            TextEditor(text: $recoveryKey)
                .font(.system(.body, design: .monospaced))
                .frame(minHeight: 100)
                .padding(.spacing3).background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius3))

            Button("Verify") { verifyRecoveryKey() }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                .disabled(recoveryKey.isEmpty || isLoading)
        }
    }

    private var backupCodeStep: some View {
        VStack(spacing: .spacing6) {
            Text("Enter Backup Code")
                .font(.omH3).fontWeight(.bold)

            TextField("Backup code", text: $backupCode)
                .font(.system(.body, design: .monospaced)).autocorrectionDisabled()
                .textFieldStyle(.roundedBorder)

            Button("Verify") { verifyBackupCode() }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                .disabled(backupCode.isEmpty || isLoading)
        }
    }

    private var resetPasswordStep: some View {
        VStack(spacing: .spacing6) {
            Text("Set New Password")
                .font(.omH3).fontWeight(.bold)

            SecureField("New password (min 8 characters)", text: $newPassword)
                .textContentType(.newPassword).textFieldStyle(.roundedBorder)

            SecureField("Confirm password", text: $confirmPassword)
                .textContentType(.newPassword).textFieldStyle(.roundedBorder)

            if !confirmPassword.isEmpty && newPassword != confirmPassword {
                Text("Passwords don't match").font(.omXs).foregroundStyle(Color.error)
            }

            Button("Reset Password") { resetPassword() }
                .buttonStyle(.borderedProminent).tint(Color.buttonPrimary)
                .disabled(newPassword.count < 8 || newPassword != confirmPassword || isLoading)
        }
    }

    private var completeStep: some View {
        VStack(spacing: .spacing6) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 48)).foregroundStyle(.green)
            Text("Account Recovered").font(.omH2).fontWeight(.bold)
            Text("Your password has been reset. You can now log in.")
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
