// Email lookup — first step of login. User enters email, we call /v1/auth/lookup
// to discover available login methods. Mirrors EmailLookup.svelte.

import SwiftUI

struct EmailLookupView: View {
    @EnvironmentObject var authManager: AuthManager
    @Binding var email: String
    let onLookupComplete: ([LoginMethod], Bool) -> Void

    @State private var isLoading = false
    @State private var errorMessage: String?
    @FocusState private var emailFocused: Bool

    var body: some View {
        VStack(spacing: .spacing6) {
            Text(LocalizationManager.shared.text("auth.welcome_back"))
                .font(.omH3)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)

            Text(LocalizationManager.shared.text("auth.enter_email_to_continue"))
                .font(.omP)
                .foregroundStyle(Color.fontSecondary)

            VStack(spacing: .spacing4) {
                TextField(LocalizationManager.shared.text("auth.email_address"), text: $email)
                    .textFieldStyle(OMTextFieldStyle())
                    .textContentType(.emailAddress)
                    #if os(iOS)
                    .keyboardType(.emailAddress)
                    #endif
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
                    .focused($emailFocused)
                    .onSubmit { performLookup() }
                    .accessibilityIdentifier("email-input")
                    .accessibilityLabel(LocalizationManager.shared.text("auth.email_address"))
                    .accessibilityHint(LocalizationManager.shared.text("auth.enter_account_email"))

                if let errorMessage {
                    Text(errorMessage)
                        .font(.omXs)
                        .foregroundStyle(Color.error)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }

            Button(action: performLookup) {
                Group {
                    if isLoading {
                        ProgressView()
                            .tint(.fontButton)
                    } else {
                        Text(LocalizationManager.shared.text("common.continue"))
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(email.isEmpty || isLoading)
            .accessibilityIdentifier("continue-button")
            .accessibilityLabel(LocalizationManager.shared.text("common.continue"))
            .accessibilityHint(LocalizationManager.shared.text("auth.lookup_login_methods"))
        }
        .onAppear {
            emailFocused = true
        }
    }

    private func performLookup() {
        guard !email.isEmpty else { return }
        isLoading = true
        errorMessage = nil

        Task {
            do {
                let response = try await authManager.lookup(email: email)
                onLookupComplete(response.availableLoginMethods, response.tfaEnabled)
            } catch let error as APIError {
                errorMessage = error.localizedDescription
            } catch {
                errorMessage = LocalizationManager.shared.text("auth.connection_failed")
            }
            isLoading = false
        }
    }
}
