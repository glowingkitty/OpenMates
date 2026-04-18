// Device verification — shown when logging in from a new device.
// Supports 2FA OTP verification. Mirrors VerifyDevice2FA.svelte.

import SwiftUI

struct DeviceVerificationView: View {
    @EnvironmentObject var authManager: AuthManager
    let verificationType: String

    @State private var code = ""
    @State private var isLoading = false
    @State private var errorMessage: String?
    @FocusState private var isFocused: Bool

    var body: some View {
        ZStack {
            Color.grey0.ignoresSafeArea()

            VStack(spacing: .spacing6) {
                Image(systemName: "shield.checkered")
                    .font(.system(size: 48))
                    .foregroundStyle(Color.buttonPrimary)

                Text(LocalizationManager.shared.text("auth.verify_this_device"))
                    .font(.omH3)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)

                Text(LocalizationManager.shared.text("auth.verify_device_description"))
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.center)

                VStack(spacing: .spacing4) {
                    TextField(LocalizationManager.shared.text("auth.six_digit_code"), text: $code)
                        .textFieldStyle(OMTextFieldStyle())
                        .keyboardType(.numberPad)
                        .focused($isFocused)
                        .onSubmit { verify() }
                        .onChange(of: code) { _, newValue in
                            if newValue.count == 6 { verify() }
                        }

                    if let errorMessage {
                        Text(errorMessage)
                            .font(.omXs)
                            .foregroundStyle(Color.error)
                    }
                }

                Button(action: verify) {
                    Group {
                        if isLoading {
                            ProgressView()
                                .tint(.fontButton)
                        } else {
                            Text(LocalizationManager.shared.text("auth.verify"))
                        }
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(code.count != 6 || isLoading)
            }
            .padding(.horizontal, .spacing8)
        }
        .onAppear { isFocused = true }
    }

    private func verify() {
        guard code.count == 6 else { return }
        isLoading = true
        errorMessage = nil

        Task {
            do {
                try await authManager.verifyDeviceWith2FA(code: code)
            } catch let error as APIError {
                errorMessage = error.localizedDescription
                code = ""
            } catch {
                errorMessage = LocalizationManager.shared.text("auth.verification_failed")
                code = ""
            }
            isLoading = false
        }
    }
}
