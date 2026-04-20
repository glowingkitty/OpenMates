// Hidden chats — password-protected chat section.
// Mirrors HiddenChatUnlock.svelte: unlock modal, password setup/verify.

import SwiftUI

struct HiddenChatsUnlockView: View {
    @Binding var isUnlocked: Bool
    @State private var password = ""
    @State private var confirmPassword = ""
    @State private var isFirstSetup = true
    @State private var isLoading = false
    @State private var error: String?
    @State private var failedAttempts = 0
    @FocusState private var isFocused: Bool

    private let maxAttempts = 5

    var body: some View {
        VStack(spacing: .spacing6) {
            Icon("lock", size: 48)
                .foregroundStyle(Color.buttonPrimary)

            Text(isFirstSetup ? "Set Up Hidden Chats" : "Unlock Hidden Chats")
                .font(.omH3).fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)

            Text(isFirstSetup
                ? "Create a password to protect your hidden chats."
                : "Enter your password to view hidden chats."
            )
            .font(.omSmall).foregroundStyle(Color.fontSecondary)
            .multilineTextAlignment(.center)

            VStack(spacing: .spacing4) {
                SecureField("Password (4-30 characters)", text: $password)
                    .textFieldStyle(OMTextFieldStyle())
                    .focused($isFocused)
                    .onSubmit {
                        if isFirstSetup && confirmPassword.isEmpty { return }
                        unlock()
                    }

                if isFirstSetup {
                    SecureField("Confirm password", text: $confirmPassword)
                        .textFieldStyle(OMTextFieldStyle())
                        .onSubmit { unlock() }
                }

                if let error {
                    Text(error)
                        .font(.omXs).foregroundStyle(Color.error)
                }

                if failedAttempts > 0 {
                    Text("\(maxAttempts - failedAttempts) attempts remaining")
                        .font(.omXs).foregroundStyle(Color.warning)
                }
            }

            Button(action: unlock) {
                Group {
                    if isLoading {
                        ProgressView().tint(.fontButton)
                    } else {
                        Text(isFirstSetup ? "Set Password" : "Unlock")
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(password.count < 4 || password.count > 30 || isLoading ||
                      (isFirstSetup && password != confirmPassword) ||
                      failedAttempts >= maxAttempts)
        }
        .padding(.spacing8)
        .onAppear { isFocused = true }
    }

    private func unlock() {
        guard password.count >= 4 else { return }
        if isFirstSetup && password != confirmPassword {
            error = "Passwords don't match"
            return
        }

        isLoading = true
        error = nil

        Task {
            do {
                if isFirstSetup {
                    let _: Data = try await APIClient.shared.request(
                        .post, path: "/v1/chats/hidden/setup",
                        body: ["password": password]
                    )
                } else {
                    let _: Data = try await APIClient.shared.request(
                        .post, path: "/v1/chats/hidden/unlock",
                        body: ["password": password]
                    )
                }
                isUnlocked = true
            } catch {
                failedAttempts += 1
                self.error = failedAttempts >= maxAttempts
                    ? "Too many failed attempts. Try again later."
                    : "Incorrect password"
            }
            isLoading = false
        }
    }
}
