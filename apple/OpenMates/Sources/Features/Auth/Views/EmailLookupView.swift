// Email lookup — first step of login. User enters email, we call /v1/auth/lookup
// to discover available login methods. Mirrors EmailLookup.svelte.
// Specification: specifications/features/auth/specification.yml
// Assertions: auth.login.method-convergence

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
    @State private var didAttemptImmediatePasskey = false

    var body: some View {
        EmailLookupForm(email: $email, stayLoggedIn: $stayLoggedIn,
            onPasskeyLogin: onPasskeyLogin, onPairLogin: onPairLogin,
            lookup: { email, stay in
                let response = try await authManager.lookup(email: email, stayLoggedIn: stay)
                onLookupComplete(response.availableLoginMethods, response.tfaEnabled, response.userEmailSalt)
            }, immediatePasskey: attemptImmediatePasskeyLogin)
    }

    @MainActor
    private func attemptImmediatePasskeyLogin() async {
        #if DEBUG
        guard !ProcessInfo.processInfo.arguments.contains("--ui-test-prefer-password-login") else { return }
        #endif
        guard !didAttemptImmediatePasskey else { return }
        didAttemptImmediatePasskey = true
        do {
            try await PasskeyLoginCoordinator.login(authManager: authManager,
                stayLoggedIn: stayLoggedIn, preferImmediatelyAvailableCredentials: true)
        } catch is CancellationError {
            // SwiftUI cancels this task on navigation; the coordinator drains OS UI.
        } catch PasskeyError.cancelled {
            // Absence or dismissal of an immediately available OS credential is normal.
        } catch {
            NativeDiagnostics.info("phase=immediatePasskey.skipped", category: "auth")
        }
    }
}

// Shared production form. No environment account, network, or passkey dependency.
struct EmailLookupForm: View {
    @Binding var email: String
    @Binding var stayLoggedIn: Bool
    let onPasskeyLogin: () -> Void
    let onPairLogin: () -> Void
    let lookup: @MainActor (String, Bool) async throws -> Void
    var immediatePasskey: (@MainActor () async -> Void)? = nil

    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var showEmailWarning = false
    @FocusState private var emailFocused: Bool

    private var hasValidEmail: Bool {
        validationMessage(for: email) == nil
    }

    var body: some View {
        VStack(spacing: 0) {
            stayLoggedInControl
                // EmailLookup.svelte .toggle-group has 15px vertical margins.
                .padding(.vertical, 15)

            loginOption(
                icon: "passkey",
                title: AppStrings.authPasskeyOption,
                action: onPasskeyLogin
            )
            .accessibilityIdentifier("login-passkey-option")
            .padding(.top, .spacing8)
            .padding(.bottom, .spacing8)

            loginOption(
                icon: "phone",
                title: AppStrings.authPairOption,
                action: onPairLogin
            )
            .accessibilityIdentifier("login-pair-option")
            .padding(.top, -CGFloat.spacing4)
            .padding(.bottom, .spacing8)

            divider
                .padding(.vertical, .spacing8)

            emailInput

            if let errorMessage {
                Text(errorMessage)
                    .accessibilityIdentifier("lookup-error")
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
                        Text(AppStrings.authContinue)
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(AuthPrimaryButtonStyle())
            .disabled(!hasValidEmail || isLoading)
            .padding(.top, .spacing10)
            .accessibilityIdentifier("continue-button")
            .help(Text(AppStrings.authContinue))
            .accessibilityLabel(AppStrings.authContinue)
            .accessibilityHint(LocalizationManager.shared.text("auth.lookup_login_methods"))
        }
        .frame(maxWidth: .infinity)
        .onChange(of: email) { _, newValue in
            email = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
            if showEmailWarning || !newValue.isEmpty {
                errorMessage = validationMessage(for: email)
                showEmailWarning = errorMessage != nil
            }
        }
        .task {
            guard let immediatePasskey else { return }
            await immediatePasskey()
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
                        .fill(Color.grey0)
                        .frame(width: 24, height: 24)
                        .shadow(color: .black.opacity(0.2), radius: 2, x: 0, y: 1)
                        .padding(.horizontal, 4)
                }

                Text(AppStrings.stayLoggedIn)
                    .font(.omP)
                    .foregroundStyle(Color.fontSecondary)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: 350, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("stay-logged-in-toggle")
        .accessibilityLabel(AppStrings.stayLoggedIn)
        .accessibleToggle(AppStrings.stayLoggedIn, isOn: stayLoggedIn)
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
        .help(Text(title))
        .accessibilityLabel(title)
    }

    private var divider: some View {
        HStack(spacing: .spacing6) {
            Rectangle()
                .fill(Color.grey30)
                .frame(height: 1)
            Text(AppStrings.authOr)
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

            TextField(AppStrings.emailPlaceholder, text: $email)
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
                .accessibilityLabel(AppStrings.emailPlaceholder)
        }
        .padding(.horizontal, .spacing8)
        .frame(height: 48)
        .frame(maxWidth: 350)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
        .overlay(
            RoundedRectangle(cornerRadius: .radiusFull)
                .stroke(errorMessage == nil ? (emailFocused ? Color.buttonPrimary : Color.grey0) : Color.error, lineWidth: 2)
        )
        .shadow(color: emailFocused ? Color.buttonPrimary.opacity(0.22) : .clear, radius: 3)
        .shadow(color: .black.opacity(0.08), radius: 6, x: 0, y: 4)
        .tint(Color.buttonPrimary)
    }

    private func performLookup() {
        guard !email.isEmpty, !isLoading else { return }
        if let validationError = validationMessage(for: email) {
            errorMessage = validationError
            showEmailWarning = true
            AccessibilityAnnouncement.announce(validationError)
            return
        }

        isLoading = true
        errorMessage = nil

        Task {
            do {
                try await lookup(email, stayLoggedIn)
            } catch let error as APIError {
                errorMessage = error.localizedDescription
            } catch {
                errorMessage = LocalizationManager.shared.text("login.cant_connect_to_server")
            }
            isLoading = false
        }
    }

    private func validationMessage(for value: String) -> String? {
        guard !value.isEmpty else { return AppStrings.emailPlaceholder }
        guard value.contains("@") else { return AppStrings.atMissing }
        guard value.range(of: #"\.[A-Za-z]{2,}$"#, options: .regularExpression) != nil else {
            return AppStrings.domainEndingMissing
        }
        return nil
    }

}
