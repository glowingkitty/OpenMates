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
                .accessibilityHidden(true)

            Text(LocalizationManager.shared.text("auth.account_recovery"))
                .font(.omH3)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)

            Text(LocalizationManager.shared.text("auth.enter_recovery_key_description"))
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)

            VStack(spacing: .spacing4) {
                TextField(LocalizationManager.shared.text("auth.recovery_key_placeholder"), text: $recoveryKey)
                    .textFieldStyle(OMTextFieldStyle())
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
                    .focused($isFocused)
                    .onSubmit { performLogin() }
                    .accessibleInput(
                        LocalizationManager.shared.text("auth.recovery_key"),
                        hint: LocalizationManager.shared.text("auth.enter_24_char_recovery_key")
                    )

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
                        Text(LocalizationManager.shared.text("auth.recover_account"))
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(recoveryKey.count < 20 || isLoading)
            .accessibleButton(
                LocalizationManager.shared.text("auth.recover_account"),
                hint: LocalizationManager.shared.text("auth.sign_in_with_recovery_key")
            )
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
                AccessibilityAnnouncement.announce(error.localizedDescription)
            } catch {
                let msg = LocalizationManager.shared.text("auth.recovery_failed")
                errorMessage = msg
                AccessibilityAnnouncement.announce(msg)
            }
            isLoading = false
        }
    }
}
