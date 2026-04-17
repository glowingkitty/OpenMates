// Recovery key login — emergency access when password and 2FA are unavailable.
// Mirrors EnterRecoveryKey.svelte. Accepts the 24-character recovery key.

import SwiftUI

struct RecoveryKeyView: View {
    @EnvironmentObject var authManager: AuthManager
    let email: String

    @State private var recoveryKey = ""
    @State private var isLoading = false
    @State private var errorMessage: String?
    @FocusState private var isFocused: Bool

    var body: some View {
        VStack(spacing: .spacing6) {
            Image(systemName: "key.fill")
                .font(.system(size: 36))
                .foregroundStyle(Color.warning)

            Text("Account Recovery")
                .font(.omH3)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)

            Text("Enter your recovery key to regain access to your account.")
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)

            VStack(spacing: .spacing4) {
                TextField("Recovery key (24 characters)", text: $recoveryKey)
                    .textFieldStyle(OMTextFieldStyle())
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
                    .focused($isFocused)
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
                        Text("Recover Account")
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(recoveryKey.count < 20 || isLoading)
        }
        .onAppear { isFocused = true }
    }

    private func performLogin() {
        guard !recoveryKey.isEmpty else { return }
        isLoading = true
        errorMessage = nil

        Task {
            do {
                try await authManager.loginWithRecoveryKey(email: email, recoveryKey: recoveryKey)
            } catch let error as APIError {
                errorMessage = error.localizedDescription
            } catch {
                errorMessage = "Recovery failed. Please check your key and try again."
            }
            isLoading = false
        }
    }
}
