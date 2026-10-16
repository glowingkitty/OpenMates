// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/Login.svelte
//         frontend/packages/ui/src/components/EmailLookup.svelte
//         frontend/packages/ui/src/components/PasswordAndTfaOtp.svelte
// CSS: frontend/packages/ui/src/styles/auth.css
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
#if DEBUG
import SwiftUI

// Fixtures exercise the production form bodies. Every nonlocal capability is an
// explicit destination notice with a return action; no silent/no-op auth button.
struct DevAuthFormFixture: View {
    let configuration: DevPreviewLaunchConfiguration
    @State private var email = ""
    @State private var stay = false
    @State private var passwordStep = false
    @State private var complete = false
    @State private var destination: String?

    init(configuration: DevPreviewLaunchConfiguration) {
        self.configuration = configuration
        _email = State(initialValue: ["password", "otp", "password-error"].contains(configuration.variant)
            ? "fixture@example.test" : "")
        _passwordStep = State(initialValue: ["password", "otp", "password-error"].contains(configuration.variant))
    }

    var body: some View {
        if ["mobile-header", "wide-header"].contains(configuration.variant) {
            DevAuthHeaderFixture(initialMode: configuration.component == .signup ? .signup : .login)
        } else if configuration.component == .signup {
            DevSignupFlowFixture(configuration: configuration)
        } else if configuration.variant == "watch-pair-approval" {
            #if os(iOS)
            DevWatchPairApprovalFixture()
            #else
            Text("This synthetic iPhone approval preview requires iOS.").font(.omSmall)
            #endif
        } else if configuration.variant == "passkey-lifecycle" {
            DevPasskeyLifecycleFixture()
        } else {
            GeometryReader { geometry in
                ScrollView {
                    VStack(spacing: 0) {
                        if let destination {
                            Text(destination).accessibilityIdentifier("fixture-auth-destination")
                            Text("This fixture stops before opening an external service or system authentication.")
                                .font(.omSmall)
                            Button(AppStrings.back) { self.destination = nil }
                                .accessibilityIdentifier("fixture-auth-return")
                        } else {
                            AuthLoginHeading(compact: geometry.size.width <= 730)
                                .padding(.bottom, .spacing24)
                            if complete {
                                Text("Local login flow complete").accessibilityIdentifier("fixture-login-complete")
                                Text("No account session was created.").font(.omSmall)
                            } else if passwordStep {
                                PasswordLoginForm(email: email, tfaEnabled: true,
                                    onRecoveryKey: { destination = "recovery-key" },
                                    onAnotherAccount: { email = ""; passwordStep = false },
                                    onAccountRecovery: { destination = "account-recovery" },
                                    login: { _, code, codeType in
                                        if configuration.variant == "password-error" { throw AuthError.invalidCredentials }
                                        guard let code else { throw AuthError.tfaRequired }
                                        guard (codeType == "otp" && code == "123456") ||
                                              (codeType == "backup" && code == "ABCD-EFGH-1234") else {
                                            throw AuthError.invalidTwoFactorCode
                                        }
                                        complete = true
                                    }, initialStep: configuration.variant == "otp" ? .otp : .password)
                            } else {
                                EmailLookupForm(email: $email, stayLoggedIn: $stay,
                                    onPasskeyLogin: { destination = "passkey" },
                                    onPairLogin: { destination = "device-pairing" },
                                    lookup: { _, _ in
                                        if ["error", "lookup-error"].contains(configuration.variant) {
                                            throw AuthFormError.rejected
                                        }
                                        passwordStep = true
                                    })
                            }
                        }
                    }
                    .frame(maxWidth: 440)
                    .padding(.vertical, .spacing10).padding(.horizontal, .spacing10)
                    .frame(maxWidth: .infinity)
                }
                .background(Color.grey20)
            }
        }
    }
}

// This variant includes the production header and actual entry forms. Transport
// remains local; screenshots contain only synthetic input and no account session.
private struct DevAuthHeaderFixture: View {
    @State private var mode: AuthFlowState.AuthMode
    @State private var email = ""
    @State private var stay = false
    @State private var destination: String?
    @StateObject private var signup: SignupViewModel

    init(initialMode: AuthFlowState.AuthMode) {
        _mode = State(initialValue: initialMode)
        _signup = StateObject(wrappedValue: SignupViewModel(
            runtime: PreviewNativeSignupRuntime(variant: "basics"),
            configuration: .init(inviteCode: nil, language: "en", darkmode: false)))
    }

    var body: some View {
        GeometryReader { geometry in
            ScrollView {
                AuthEntryLayout(viewport: geometry.size) {
                    VStack(spacing: 0) {
                        AuthEntryHeader(mobile: geometry.size.width <= 600, mode: mode,
                            onBackToDemo: { destination = "demo" }, onSelectMode: { mode = $0 })
                        if let destination {
                            Text(destination).accessibilityIdentifier("fixture-auth-destination")
                            Button(AppStrings.back) { self.destination = nil }
                                .accessibilityIdentifier("fixture-auth-return")
                        } else if mode == .login {
                            AuthLoginHeading(compact: geometry.size.width <= 730)
                            EmailLookupForm(email: $email, stayLoggedIn: $stay,
                                onPasskeyLogin: { destination = "passkey" },
                                onPairLogin: { destination = "device-pairing" },
                                lookup: { _, _ in destination = "local-email-lookup" })
                                .padding(.top, .spacing24)
                        } else {
                            SignupBasicsFormView(model: signup.basicsModel, compact: geometry.size.width <= 730,
                                onOpenURL: { destination = $0.absoluteString },
                                onCodeRequested: { _ in destination = "local-email-code-requested" })
                        }
                    }
                }
            }
            .background(Color.grey20)
        }
        .task {
            await signup.loadRequirements()
            signup.continueFromDisclaimer()
        }
        .onDisappear { signup.cancel() }
    }
}
#endif
