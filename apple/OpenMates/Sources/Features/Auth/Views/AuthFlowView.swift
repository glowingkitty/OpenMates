// Auth flow container — manages step transitions for the login flow.
// Mirrors Login.svelte's step-based navigation between email lookup,
// password entry, passkey, recovery key, and backup code screens.
// VoiceOver: screen change announcements on step transitions, combined header group.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/Login.svelte
//          frontend/packages/ui/src/components/LoginMethodSelector.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct AuthFlowView: View {
    let onBackToDemo: () -> Void

    @EnvironmentObject var authManager: AuthManager
    @State private var currentStep: AuthStep = .emailLookup
    @State private var authMode: AuthMode = .signup
    @State private var email = ""
    @State private var availableMethods: [LoginMethod] = []
    @State private var tfaEnabled = false
    @State private var stayLoggedIn = false
    @State private var userEmailSalt: String?

    enum AuthMode {
        case login
        case signup
    }

    enum AuthStep {
        case emailLookup
        case passwordLogin
        case passkeyLogin
        case recoveryKey
        case backupCode
        case pairInitiate
    }

    var body: some View {
        ZStack {
            Color.grey20.ignoresSafeArea()
            AuthIconGridBackground()
                .opacity(0.16)
                .ignoresSafeArea()

            ScrollView {
                VStack(spacing: .spacing4) {
                    demoBackButton

                    VStack(spacing: .spacing6) {
                        authTabs

                        if authMode == .login {
                            Text(LocalizationManager.shared.text("login.login"))
                                .font(.omH1)
                                .fontWeight(.bold)
                                .foregroundStyle(LinearGradient.primary)

                            Text("\(LocalizationManager.shared.text("login.to_chat_to_your"))\n\(LocalizationManager.shared.text("login.digital_team_mates"))")
                                .font(.omH3)
                                .fontWeight(.bold)
                                .multilineTextAlignment(.center)
                                .foregroundStyle(Color.fontPrimary)
                        }

                        if authMode == .login {
                            loginContent
                        } else {
                            SignupFlowView()
                        }
                    }
                    .padding(.horizontal, .spacing6)
                    .padding(.vertical, .spacing6)
                    .frame(maxWidth: 430)
                    .background(Color.grey0)
                    .clipShape(RoundedRectangle(cornerRadius: 18))
                    .shadow(color: .black.opacity(0.14), radius: 20, x: 0, y: 8)
                }
                .frame(maxWidth: .infinity)
                .padding(.horizontal, .spacing5)
                .padding(.top, .spacing6)
                .padding(.bottom, .spacing10)
            }
        }
    }

    // MARK: - Subviews

    private var demoBackButton: some View {
        HStack {
            Button(action: onBackToDemo) {
                HStack(spacing: .spacing2) {
                    Icon("back", size: 18)
                    Text(LocalizationManager.shared.text("login.demo"))
                        .font(.omSmall)
                        .fontWeight(.semibold)
                }
                .foregroundStyle(Color.fontSecondary)
            }
            .buttonStyle(.plain)
            Spacer()
        }
        .frame(maxWidth: 430)
        .padding(.horizontal, .spacing2)
    }

    private var authTabs: some View {
        HStack(spacing: .spacing2) {
            authTab(LocalizationManager.shared.text("login.login"), mode: .login)
            authTab(LocalizationManager.shared.text("signup.sign_up"), mode: .signup)
        }
        .padding(.spacing1)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius5))
        .shadow(color: .black.opacity(0.05), radius: 8, x: 0, y: 2)
    }

    private func authTab(_ title: String, mode: AuthMode) -> some View {
        Button {
            authMode = mode
            if mode == .login {
                currentStep = .emailLookup
            }
        } label: {
            Text(title)
                .font(.omP)
                .fontWeight(.semibold)
                .foregroundStyle(authMode == mode ? Color.fontButton : Color.fontSecondary)
                .padding(.horizontal, .spacing5)
                .padding(.vertical, .spacing3)
                .frame(maxWidth: .infinity)
                .background {
                    if authMode == mode {
                        LinearGradient.primary
                    } else {
                        Color.clear
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private var loginContent: some View {
        switch currentStep {
        case .emailLookup:
            EmailLookupView(
                email: $email,
                stayLoggedIn: $stayLoggedIn,
                onPasskeyLogin: { currentStep = .passkeyLogin },
                onPairLogin: { currentStep = .pairInitiate },
                onLookupComplete: handleLookupComplete
            )

        case .passwordLogin:
            PasswordLoginView(
                email: email,
                userEmailSalt: userEmailSalt,
                tfaEnabled: tfaEnabled,
                stayLoggedIn: $stayLoggedIn,
                onRecoveryKey: { currentStep = .recoveryKey },
                onBackupCode: { currentStep = .backupCode }
            )

        case .passkeyLogin:
            PasskeyLoginView(email: email)

        case .recoveryKey:
            RecoveryKeyView(email: email, userEmailSalt: userEmailSalt)

        case .backupCode:
            BackupCodeView(email: email, userEmailSalt: userEmailSalt)

        case .pairInitiate:
            SettingsPairInitiateView()
        }
    }

    // MARK: - Navigation bar (back button for non-email steps)

    private var showBackButton: Bool {
        currentStep != .emailLookup
    }

    // MARK: - Actions

    private func handleLookupComplete(methods: [LoginMethod], tfa: Bool, userEmailSalt: String?) {
        availableMethods = methods
        tfaEnabled = tfa
        self.userEmailSalt = userEmailSalt

        if methods.contains(.passkey) {
            currentStep = .passkeyLogin
            AccessibilityAnnouncement.screenChanged(LocalizationManager.shared.text("auth.passkey_login_screen"))
        } else {
            currentStep = .passwordLogin
            AccessibilityAnnouncement.screenChanged(LocalizationManager.shared.text("auth.password_login_screen"))
        }
    }

}

private struct AuthIconGridBackground: View {
    private let icons = ["ai", "coding", "web", "book", "money", "travel", "heart", "calendar", "maps"]

    var body: some View {
        GeometryReader { geo in
            let columns = max(5, Int(geo.size.width / 52))
            let rows = max(10, Int(geo.size.height / 52))
            VStack(spacing: 2) {
                ForEach(0..<rows, id: \.self) { row in
                    HStack(spacing: 2) {
                        ForEach(0..<columns, id: \.self) { column in
                            Icon(icons[(row + column) % icons.count], size: 24)
                                .foregroundStyle(LinearGradient.primary)
                                .frame(width: 48, height: 48)
                                .opacity((row + column).isMultiple(of: 3) ? 0.7 : 0.32)
                        }
                    }
                    .offset(x: row.isMultiple(of: 2) ? 0 : 10)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}
