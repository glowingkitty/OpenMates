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
        if configuration.component == .signup {
            DevSignupFlowFixture(configuration: configuration)
        } else {
            GeometryReader { geometry in
                ScrollView {
                    VStack(spacing: 16) {
                        if let destination {
                            Text(destination).accessibilityIdentifier("fixture-auth-destination")
                            Text("This fixture stops before opening an external service or system authentication.")
                                .font(.omSmall)
                            Button(AppStrings.back) { self.destination = nil }
                                .accessibilityIdentifier("fixture-auth-return")
                        } else {
                            AuthLoginHeading(compact: geometry.size.width <= 730)
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
                    .frame(maxWidth: geometry.size.width <= 730 ? 300 : 440)
                    .padding(.vertical, 20).padding(.horizontal, 12)
                    .frame(maxWidth: .infinity)
                }
                .background(Color.grey20)
            }
        }
    }
}
#endif
