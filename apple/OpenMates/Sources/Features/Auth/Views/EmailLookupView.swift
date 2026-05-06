// Email lookup — first step of login. User enters email, we call /v1/auth/lookup
// to discover available login methods. Mirrors EmailLookup.svelte.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/EmailLookup.svelte
// CSS:     frontend/packages/ui/src/styles/auth.css
//          .login-container, .login-content
//          frontend/packages/ui/src/styles/fields.css (inputs)
//          frontend/packages/ui/src/styles/buttons.css (continue button)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct EmailLookupView: View {
    @EnvironmentObject var authManager: AuthManager
    @Binding var email: String
    @Binding var stayLoggedIn: Bool
    let onPasskeyLogin: () -> Void
    let onPairLogin: () -> Void
    let onLookupComplete: ([LoginMethod], Bool, String?) -> Void

    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var didAttemptImmediatePasskey = false
    @FocusState private var emailFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            stayLoggedInControl

            loginOption(
                icon: "passkey",
                title: LocalizationManager.shared.text("login.login_with_passkey"),
                action: onPasskeyLogin
            )
            .padding(.top, .spacing4)

            loginOption(
                icon: "phone",
                title: LocalizationManager.shared.text("login.login_with_phone_or_pc"),
                action: onPairLogin
            )
            .padding(.top, .spacing2)

            divider
                .padding(.vertical, .spacing4)

            emailInput

            if let errorMessage {
                Text(errorMessage)
                    .font(.omXs)
                    .foregroundStyle(Color.error)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.top, .spacing2)
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
            .padding(.top, .spacing4)
            .accessibilityIdentifier("continue-button")
            .accessibilityLabel(LocalizationManager.shared.text("common.continue"))
            .accessibilityHint(LocalizationManager.shared.text("auth.lookup_login_methods"))
        }
        .frame(maxWidth: .infinity)
        .task {
            guard !didAttemptImmediatePasskey else { return }
            didAttemptImmediatePasskey = true
            await attemptImmediatePasskeyLogin()
        }
    }

    private var stayLoggedInControl: some View {
        Button {
            stayLoggedIn.toggle()
        } label: {
            HStack(spacing: .spacing6) {
                ZStack(alignment: stayLoggedIn ? .trailing : .leading) {
                    Capsule()
                        .fill(stayLoggedIn ? AnyShapeStyle(LinearGradient.primary) : AnyShapeStyle(Color.grey30))
                        .frame(width: 52, height: 32)
                        .shadow(color: .black.opacity(0.18), radius: 2, x: 0, y: 1)

                    Circle()
                        .fill(Color.white)
                        .frame(width: 24, height: 24)
                        .shadow(color: .black.opacity(0.2), radius: 2, x: 0, y: 1)
                        .padding(.horizontal, 4)
                }

                Text(LocalizationManager.shared.text("login.stay_logged_in"))
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: 350, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("stay-logged-in-toggle")
        .accessibilityLabel(LocalizationManager.shared.text("login.stay_logged_in"))
        .accessibleToggle(LocalizationManager.shared.text("login.stay_logged_in"), isOn: stayLoggedIn)
    }

    private func loginOption(icon: String, title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: .spacing4) {
                Icon(icon, size: 20)
                    .foregroundStyle(LinearGradient.primary)
                Text(title)
                    .font(.omP)
                    .fontWeight(.medium)
                    .foregroundStyle(LinearGradient.primary)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, .spacing4)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
    }

    private var divider: some View {
        HStack(spacing: .spacing6) {
            Rectangle()
                .fill(Color.grey30)
                .frame(height: 1)
            Text(LocalizationManager.shared.text("login.or"))
                .font(.omSmall)
                .foregroundStyle(Color.grey60)
            Rectangle()
                .fill(Color.grey30)
                .frame(height: 1)
        }
    }

    private var emailInput: some View {
        HStack(spacing: .spacing4) {
            Icon("mail", size: 20)
                .foregroundStyle(LinearGradient.primary)

            TextField(LocalizationManager.shared.text("login.email_placeholder"), text: $email)
                .font(.omP)
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
                .accessibilityLabel(LocalizationManager.shared.text("login.email_placeholder"))
        }
        .padding(.horizontal, .spacing6)
        .frame(height: 48)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
        .overlay(
            RoundedRectangle(cornerRadius: .radiusFull)
                .stroke(emailFocused ? Color.buttonPrimary : Color.grey30, lineWidth: 2)
        )
    }

    private func performLookup() {
        guard !email.isEmpty else { return }
        isLoading = true
        errorMessage = nil

        Task {
            do {
                let response = try await authManager.lookup(email: email, stayLoggedIn: stayLoggedIn)
                onLookupComplete(response.availableLoginMethods, response.tfaEnabled, response.userEmailSalt)
            } catch let error as APIError {
                errorMessage = error.localizedDescription
            } catch {
                errorMessage = LocalizationManager.shared.text("login.cant_connect_to_server")
            }
            isLoading = false
        }
    }

    @MainActor
    private func attemptImmediatePasskeyLogin() async {
        do {
            try await PasskeyLoginCoordinator.login(
                authManager: authManager,
                stayLoggedIn: stayLoggedIn,
                preferImmediatelyAvailableCredentials: true
            )
        } catch PasskeyError.cancelled {
            // No immediately available passkey or user dismissed the OS prompt.
        } catch {
            print("[Auth] Immediate passkey login skipped: \(error)")
        }
    }
}
