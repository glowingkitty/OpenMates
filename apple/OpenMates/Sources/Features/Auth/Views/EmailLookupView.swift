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
            Text("Welcome back")
                .font(.omH3)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)

            Text("Enter your email to continue")
                .font(.omP)
                .foregroundStyle(Color.fontSecondary)

            VStack(spacing: .spacing4) {
                TextField("Email address", text: $email)
                    .textFieldStyle(OMTextFieldStyle())
                    .textContentType(.emailAddress)
                    .keyboardType(.emailAddress)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
                    .focused($emailFocused)
                    .onSubmit { performLookup() }

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
                        Text("Continue")
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(email.isEmpty || isLoading)
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
                errorMessage = "Connection failed. Please try again."
            }
            isLoading = false
        }
    }
}
