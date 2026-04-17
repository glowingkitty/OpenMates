// Password + optional 2FA login screen. Mirrors PasswordAndTfaOtp.svelte.
// Shows password field first; if server returns tfaRequired, shows OTP field.

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
            Text("Enter your password")
                .font(.omH3)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)

            Text(email)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)

            VStack(spacing: .spacing4) {
                SecureField("Password", text: $password)
                    .textFieldStyle(OMTextFieldStyle())
                    .textContentType(.password)
                    .focused($focusedField, equals: .password)
                    .onSubmit {
                        if showTfaField { focusedField = .tfa }
                        else { performLogin() }
                    }

                if showTfaField {
                    TextField("Authenticator code", text: $tfaCode)
                        .textFieldStyle(OMTextFieldStyle())
                        .keyboardType(.numberPad)
                        .focused($focusedField, equals: .tfa)
                        .onSubmit { performLogin() }
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                if let errorMessage {
                    Text(errorMessage)
                        .font(.omXs)
                        .foregroundStyle(Color.error)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }

            Toggle("Stay logged in", isOn: $stayLoggedIn)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .tint(Color.buttonPrimary)

            Button(action: performLogin) {
                Group {
                    if isLoading {
                        ProgressView()
                            .tint(.fontButton)
                    } else {
                        Text("Log in")
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(password.isEmpty || isLoading)

            // Recovery options
            VStack(spacing: .spacing3) {
                Button("Use recovery key") {
                    onRecoveryKey()
                }
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)

                if showTfaField {
                    Button("Use backup code") {
                        onBackupCode()
                    }
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
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
            } catch let error as APIError {
                errorMessage = error.localizedDescription
            } catch {
                errorMessage = "Login failed. Please try again."
            }
            isLoading = false
        }
    }
}
