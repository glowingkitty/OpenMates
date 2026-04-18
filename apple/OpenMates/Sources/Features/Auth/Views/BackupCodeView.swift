// Backup code login — fallback when authenticator app is unavailable.
// Mirrors EnterBackupCode.svelte. Accepts XXXX-XXXX-XXXX format code.

import SwiftUI

struct BackupCodeView: View {
    @EnvironmentObject var authManager: AuthManager
    let email: String

    @State private var password = ""
    @State private var backupCode = ""
    @State private var isLoading = false
    @State private var errorMessage: String?
    @FocusState private var focusedField: Field?

    enum Field {
        case password, backupCode
    }

    var body: some View {
        VStack(spacing: .spacing6) {
            Image(systemName: "number.square.fill")
                .font(.system(size: 36))
                .foregroundStyle(Color.fontSecondary)

            Text(LocalizationManager.shared.text("auth.use_backup_code"))
                .font(.omH3)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)

            Text(LocalizationManager.shared.text("auth.enter_password_and_backup_code"))
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)

            VStack(spacing: .spacing4) {
                SecureField(AppStrings.password, text: $password)
                    .textFieldStyle(OMTextFieldStyle())
                    .textContentType(.password)
                    .focused($focusedField, equals: .password)
                    .onSubmit { focusedField = .backupCode }

                TextField(LocalizationManager.shared.text("auth.backup_code_format"), text: $backupCode)
                    .textFieldStyle(OMTextFieldStyle())
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
                    .focused($focusedField, equals: .backupCode)
                    .onSubmit { performLogin() }

                if let errorMessage {
                    Text(errorMessage)
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
                        Text(LocalizationManager.shared.text("auth.login_with_backup_code"))
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(password.isEmpty || backupCode.isEmpty || isLoading)
        }
        .onAppear { focusedField = .password }
    }

    private func performLogin() {
        guard !password.isEmpty, !backupCode.isEmpty else { return }
        isLoading = true
        errorMessage = nil

        Task {
            do {
                try await authManager.loginWithBackupCode(
                    email: email, password: password, backupCode: backupCode
                )
            } catch let error as APIError {
                errorMessage = error.localizedDescription
            } catch {
                errorMessage = LocalizationManager.shared.text("auth.login_failed_check_credentials")
            }
            isLoading = false
        }
    }
}
