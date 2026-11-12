// Device verification — shown when logging in from a new device.
// Supports 2FA OTP verification (VerifyDevice2FA.svelte) and passkey
// verification, both answered by the Rust core (`AuthManager`); Swift runs
// only the system passkey ceremony.
// Specification: specifications/features/auth/specification.yml
// Assertions: auth.session.risk-reauth, auth.login.method-convergence

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/Login.svelte
//          (device verification / 2FA OTP step in login flow)
// CSS:     frontend/packages/ui/src/styles/auth.css
//          frontend/packages/ui/src/styles/fields.css (OTP input)
//          frontend/packages/ui/src/styles/buttons.css (verify button)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

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
                    .accessibilityHidden(true)

                Text(LocalizationManager.shared.text("auth.verify_this_device"))
                    .font(.omH3)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)

                Text(LocalizationManager.shared.text(isPasskey
                    ? "login.verify_device_passkey_prompt" : "auth.verify_device_description"))
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.center)

                if isPasskey { passkeyControls } else { codeControls }
            }
            .padding(.horizontal, .spacing8)
        }
        .onAppear { isFocused = !isPasskey }
    }

    private var isPasskey: Bool { verificationType == "passkey" }

    private var passkeyControls: some View {
        VStack(spacing: .spacing4) {
            if let errorMessage {
                Text(errorMessage)
                    .font(.omXs)
                    .foregroundStyle(Color.error)
            }
            Button(action: verifyWithPasskey) {
                Group {
                    if isLoading {
                        ProgressView()
                            .tint(.fontButton)
                    } else {
                        Text(LocalizationManager.shared.text("login.verify_device_passkey_button"))
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(isLoading)
            .accessibleButton(
                LocalizationManager.shared.text("login.verify_device_passkey_button"),
                hint: LocalizationManager.shared.text("auth.verify_device_hint")
            )
        }
    }

    private var codeControls: some View {
        VStack(spacing: .spacing6) {
            VStack(spacing: .spacing4) {
                TextField(LocalizationManager.shared.text("auth.six_digit_code"), text: $code)
                    .textFieldStyle(OMTextFieldStyle())
                    #if os(iOS)
                    .keyboardType(.numberPad)
                    #endif
                    .focused($isFocused)
                    .onSubmit { verify() }
                    .onChange(of: code) { _, newValue in
                        if newValue.count == 6 { verify() }
                    }
                    .accessibleInput(
                        LocalizationManager.shared.text("auth.six_digit_code"),
                        hint: LocalizationManager.shared.text("auth.enter_6_digit_code_auto_submit")
                    )

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
            .accessibleButton(
                LocalizationManager.shared.text("auth.verify"),
                hint: LocalizationManager.shared.text("auth.verify_device_hint")
            )
        }
    }

    private func verifyWithPasskey() {
        isLoading = true
        errorMessage = nil
        Task {
            do {
                try await PasskeyLoginCoordinator.verifyDevice(authManager: authManager)
            } catch is CancellationError {
                // The view went away; the coordinator already forgot the request.
            } catch PasskeyError.cancelled {
                // Dismissing the system sheet is no error; the button stays.
            } catch {
                let msg = LocalizationManager.shared.text("login.verify_device_passkey_error")
                errorMessage = msg
                AccessibilityAnnouncement.announce(msg)
            }
            isLoading = false
        }
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
                AccessibilityAnnouncement.announce(error.localizedDescription)
            } catch {
                let msg = LocalizationManager.shared.text("auth.verification_failed")
                errorMessage = msg
                code = ""
                AccessibilityAnnouncement.announce(msg)
            }
            isLoading = false
        }
    }
}
