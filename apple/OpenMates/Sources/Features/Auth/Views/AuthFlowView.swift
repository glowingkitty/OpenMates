// Auth flow container — manages step transitions for the login flow.
// Mirrors Login.svelte's step-based navigation between email lookup,
// password entry, passkey, recovery key, and backup code screens.
// VoiceOver: screen change announcements on step transitions, combined header group.

import SwiftUI

struct AuthFlowView: View {
    @EnvironmentObject var authManager: AuthManager
    @State private var currentStep: AuthStep = .emailLookup
    @State private var email = ""
    @State private var availableMethods: [LoginMethod] = []
    @State private var tfaEnabled = false
    @State private var stayLoggedIn = false

    enum AuthStep {
        case emailLookup
        case passwordLogin
        case passkeyLogin
        case recoveryKey
        case backupCode
    }

    var body: some View {
        ZStack {
            Color.grey0.ignoresSafeArea()

            VStack(spacing: 0) {
                authHeader

                ScrollView {
                    VStack(spacing: .spacing8) {
                        switch currentStep {
                        case .emailLookup:
                            EmailLookupView(
                                email: $email,
                                onLookupComplete: handleLookupComplete
                            )

                        case .passwordLogin:
                            PasswordLoginView(
                                email: email,
                                tfaEnabled: tfaEnabled,
                                stayLoggedIn: $stayLoggedIn,
                                onRecoveryKey: { currentStep = .recoveryKey },
                                onBackupCode: { currentStep = .backupCode }
                            )

                        case .passkeyLogin:
                            PasskeyLoginView(email: email)

                        case .recoveryKey:
                            RecoveryKeyView(email: email)

                        case .backupCode:
                            BackupCodeView(email: email)
                        }
                    }
                    .padding(.horizontal, .spacing8)
                    .padding(.top, .spacing10)
                }

                signupFooter
            }
        }
    }

    // MARK: - Subviews

    private var authHeader: some View {
        VStack(spacing: .spacing4) {
            Image.iconOpenmates
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(width: 48, height: 48)
                .accessibilityHidden(true)

            Text("OpenMates")
                .font(.omH2)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontPrimary)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("OpenMates")
        .padding(.top, .spacing16)
        .padding(.bottom, .spacing6)
    }

    private var signupFooter: some View {
        VStack(spacing: .spacing4) {
            Divider()
            HStack(spacing: .spacing2) {
                Text(LocalizationManager.shared.text("auth.dont_have_account"))
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                Button(AppStrings.signup) {
                    openSignup()
                }
                .font(.omSmall)
                .fontWeight(.semibold)
                .foregroundStyle(Color.buttonPrimary)
                .accessibleButton(AppStrings.signup, hint: LocalizationManager.shared.text("auth.opens_signup_in_browser"))
            }
            .accessibilityElement(children: .combine)
            .padding(.vertical, .spacing4)
        }
    }

    // MARK: - Navigation bar (back button for non-email steps)

    private var showBackButton: Bool {
        currentStep != .emailLookup
    }

    // MARK: - Actions

    private func handleLookupComplete(methods: [LoginMethod], tfa: Bool) {
        availableMethods = methods
        tfaEnabled = tfa

        if methods.contains(.passkey) {
            currentStep = .passkeyLogin
            AccessibilityAnnouncement.screenChanged(LocalizationManager.shared.text("auth.passkey_login_screen"))
        } else {
            currentStep = .passwordLogin
            AccessibilityAnnouncement.screenChanged(LocalizationManager.shared.text("auth.password_login_screen"))
        }
    }

    private func openSignup() {
        Task {
            let url = await APIClient.shared.webAppURL.appendingPathComponent("signup")
            #if os(iOS)
            await UIApplication.shared.open(url)
            #elseif os(macOS)
            NSWorkspace.shared.open(url)
            #endif
        }
    }
}
