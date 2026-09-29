// Native device pairing for Apple apps, CLI authorization, and Apple Watch.
// Uses the v2 client-to-client PAKE approval contract through PairV2Runtime.
// Specification: specifications/features/auth/specification.yml
// Assertions: auth.pair-login.approval-assurance, auth.pair-login.lifecycle

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/security/SettingsSessionsConfirmPair.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct SettingsPairInitiateView: View {
    // Authenticated settings starts approval for a new device. The receiving
    // device initiates pairing from its logged-out login screen or CLI.
    var body: some View { SettingsConfirmPairView() }
}

struct CLIPairAuthorizeView: View {
    let token: String
    @EnvironmentObject private var authManager: AuthManager
    @Environment(\.dismiss) private var dismiss
    @State private var info: PairV2InfoResponse?
    @State private var pin: String?
    @State private var autoLogoutMinutes: Int?
    @State private var stepUpPassword = ""
    @State private var stepUpCode = ""
    @State private var emailCode = ""
    @State private var emailChallenge: PairV2EmailChallenge?
    @State private var stepUpMethods: PairV2StepUpMethods?
    @State private var state: PairingState = .loading
    @State private var errorMessage: String?

    private enum PairingState { case loading, confirm, stepUp, emailVerification, authorizing, pin, completed, failed }

    var body: some View {
        OMSettingsPage(title: AppStrings.authorizeDevice, showsFooter: false) {
            OMSettingsSection {
                VStack(spacing: .spacing6) {
                    Icon(state == .failed ? "warning" : "devices", size: 48)
                        .foregroundStyle(state == .failed ? AnyShapeStyle(Color.error) : AnyShapeStyle(LinearGradient.primary))
                    content
                }
                .frame(maxWidth: .infinity)
                .padding(.spacing8)
            }
        }
        .task { await loadInfo() }
        .onDisappear {
            stepUpPassword = ""
            stepUpCode = ""
            emailCode = ""
            emailChallenge = nil
        }
        .accessibilityIdentifier("settings-pair-authorize-page")
    }

    @ViewBuilder
    private var content: some View {
        switch state {
        case .loading, .authorizing:
            ProgressView().accessibilityLabel(AppStrings.loading)
        case .confirm:
            Text(AppStrings.deviceWantsLogin).font(.omSmall).foregroundStyle(Color.fontSecondary)
            if let info {
                OMSettingsStaticRow(title: AppStrings.device, value: info.deviceName ?? AppStrings.passkeyUnknownDevice)
                if let location = [info.city, info.countryCode].compactMap({ $0 }).joined(separator: ", ").nilIfEmpty {
                    OMSettingsStaticRow(title: AppStrings.location, value: location)
                }
            }
            Picker(AppStrings.pairAutoLogoutLabel, selection: $autoLogoutMinutes) {
                Text(AppStrings.pairAutoLogoutNone).tag(nil as Int?)
                Text(AppStrings.pairAutoLogout30m).tag(30 as Int?)
                Text(AppStrings.pairAutoLogout1h).tag(60 as Int?)
                Text(AppStrings.pairAutoLogout4h).tag(240 as Int?)
                Text(AppStrings.pairAutoLogout8h).tag(480 as Int?)
                Text(AppStrings.pairAutoLogout24h).tag(1440 as Int?)
            }
            .pickerStyle(.menu)
            HStack(spacing: .spacing4) {
                Button(AppStrings.deny) { dismiss() }.buttonStyle(OMSecondaryButtonStyle())
                Button(AppStrings.allow) { authorize() }.buttonStyle(OMPrimaryButtonStyle())
            }
        case .stepUp:
            Text(AppStrings.pairStepUpDescription)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
            if stepUpMethods?.supports(.passkey) == true {
                Button(AppStrings.loginWithPasskey) { Task { await submitPasskeyStepUp() } }
                    .buttonStyle(OMSecondaryButtonStyle())
                    .accessibilityIdentifier("settings-pair-step-up-passkey")
            }
            if stepUpMethods?.supports(.password) == true && stepUpMethods?.supports(.otp) != true {
                SecureField(AppStrings.enterPassword, text: $stepUpPassword)
                    .textFieldStyle(OMTextFieldStyle())
                    .accessibilityIdentifier("settings-pair-step-up-password")
            }
            if stepUpMethods?.supports(.otp) == true {
                TextField(AppStrings.twoFactorCodePlaceholder, text: $stepUpCode)
                    .textFieldStyle(OMTextFieldStyle())
                    #if os(iOS)
                    .keyboardType(.numberPad)
                    #endif
                    .onChange(of: stepUpCode) { _, value in
                        stepUpCode = String(value.filter(\.isNumber).prefix(6))
                    }
                    .accessibilityIdentifier("settings-pair-step-up-code")
            }
            if stepUpMethods?.supports(.password) == true || stepUpMethods?.supports(.otp) == true {
                Button(AppStrings.allow) { Task { await submitStepUp() } }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .disabled(stepUpMethods?.supports(.otp) == true ? stepUpCode.count != 6 : stepUpPassword.isEmpty)
            }
        case .emailVerification:
            Text(AppStrings.pairStepUpDescription)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
            TextField(AppStrings.enterOneTimeCode, text: $emailCode)
                .textFieldStyle(OMTextFieldStyle())
                #if os(iOS)
                .keyboardType(.numberPad)
                #endif
                .onChange(of: emailCode) { _, value in
                    emailCode = String(value.filter(\.isNumber).prefix(6))
                }
                .accessibilityIdentifier("settings-pair-step-up-email-code")
            Button(AppStrings.verifyEmailChangeCode) { Task { await submitEmailCode() } }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(emailCode.count != 6)
                .accessibilityIdentifier("settings-pair-step-up-email-verify")
            Button(AppStrings.retry) {
                emailChallenge = nil
                emailCode = ""
                errorMessage = nil
                state = .stepUp
            }
            .buttonStyle(OMSecondaryButtonStyle())
            if let errorMessage { Text(errorMessage).font(.omSmall).foregroundStyle(Color.error) }
        case .pin:
            Text(AppStrings.enterThisPin).font(.omH3)
            if let pin {
                Text(pin).font(.omH1.monospaced()).foregroundStyle(Color.buttonPrimary).textSelection(.enabled)
            }
            Text(AppStrings.pairPinExpires).font(.omXs).foregroundStyle(Color.fontSecondary)
        case .completed:
            Text(AppStrings.devicePaired).font(.omH3)
            Button(AppStrings.done) { dismiss() }.buttonStyle(OMPrimaryButtonStyle())
        case .failed:
            if let errorMessage { Text(errorMessage).font(.omSmall).foregroundStyle(Color.error) }
            Button(AppStrings.retry) { Task { await loadInfo() } }.buttonStyle(OMSecondaryButtonStyle())
        }
    }

    private func loadInfo() async {
        state = .loading
        emailChallenge = nil
        emailCode = ""
        do {
            let loaded: PairV2InfoResponse = try await APIClient.shared.request(.get, path: "/v1/auth/pair/v2/info/\(token)")
            guard loaded.protocolVersion == 2, loaded.expiresAt > Int(Date().timeIntervalSince1970) else {
                throw PairOpaqueError.invalidExchange
            }
            info = loaded
            stepUpMethods = try await PairV2Runtime.stepUpMethods(serverProfile: ServerProfile.current())
            state = .confirm
        } catch {
            fail(error, operation: "Pair info request")
        }
    }

    private func authorize() {
        state = .authorizing
        Task {
            do {
                guard let user = authManager.currentUser else { throw AccountSecurityError.missingAccountData }
                pin = try await PairLoginRuntime.authorize(
                    token: token,
                    currentUser: user,
                    authorizerDeviceName: deviceName,
                    autoLogoutMinutes: autoLogoutMinutes
                )
                state = .pin
                await pollCompletion()
            } catch APIError.httpError(let status, _) where status == 401 || status == 403 || status == 428 {
                errorMessage = nil
                state = .stepUp
            } catch {
                fail(error, operation: "Pair authorization")
            }
        }
    }

    private func submitStepUp() async {
        guard let user = authManager.currentUser else {
            fail(AccountSecurityError.missingAccountData, operation: "Pair step-up")
            return
        }
        state = .authorizing
        do {
            if !stepUpCode.isEmpty {
                try await PairV2Runtime.stepUp(
                    code: stepUpCode,
                    serverProfile: ServerProfile.current()
                )
            } else {
                emailChallenge = try await PairV2Runtime.requestEmailStepUp(
                    user: user, password: stepUpPassword,
                    serverProfile: ServerProfile.current()
                )
                stepUpPassword = ""
                state = .emailVerification
                return
            }
            stepUpPassword = ""
            stepUpCode = ""
            state = .confirm
            authorize()
        } catch {
            stepUpPassword = ""
            stepUpCode = ""
            fail(error, operation: "Pair step-up")
        }
    }

    private func submitEmailCode() async {
        guard let challenge = emailChallenge else {
            fail(PairOpaqueError.invalidExchange, operation: "Pair email step-up")
            return
        }
        state = .authorizing
        do {
            try await PairV2Runtime.verifyEmailStepUp(
                challenge, code: emailCode, serverProfile: ServerProfile.current()
            )
            emailChallenge = nil
            emailCode = ""
            errorMessage = nil
            state = .confirm
            authorize()
        } catch {
            emailCode = ""
            errorMessage = error.localizedDescription
            state = .emailVerification
        }
    }

    private func submitPasskeyStepUp() async {
        guard let user = authManager.currentUser else {
            fail(AccountSecurityError.missingAccountData, operation: "Pair passkey step-up")
            return
        }
        state = .authorizing
        do {
            try await PasskeyLoginCoordinator.verifyCurrentSessionAssertion(expectedUserID: user.id)
            emailChallenge = nil
            emailCode = ""
            state = .confirm
            authorize()
        } catch {
            fail(error, operation: "Pair passkey step-up")
        }
    }

    private func pollCompletion() async {
        for _ in 0..<100 {
            do {
                try await Task.sleep(for: .seconds(3))
                let value = try await PairV2Runtime.authorizerPoll(token: token, serverProfile: ServerProfile.current())
                if value.status == "acknowledged" { state = .completed; return }
                if ["failed", "cancelled"].contains(value.status) { throw PairOpaqueError.invalidExchange }
            } catch is CancellationError {
                return
            } catch {
                fail(error, operation: "Pair completion polling")
                return
            }
        }
        fail(AccountSecurityError.server(AppStrings.pairExpired), operation: "Pair completion polling")
    }

    private func fail(_ error: Error, operation: String) {
        errorMessage = error.localizedDescription
        state = .failed
        NativeDiagnostics.error("\(operation) failed", category: "settings.security")
    }

    private var deviceName: String {
        #if os(iOS)
        UIDevice.current.name
        #elseif os(macOS)
        Host.current().localizedName ?? AppStrings.passkeyUnknownDevice
        #endif
    }
}

#if os(iOS)
struct AppleWatchPairAuthorizeView: View {
    @ObservedObject var bridge: PhoneWatchLoginBridge
    @EnvironmentObject private var authManager: AuthManager
    let onDone: () -> Void
    @State private var isApproving = false
    @State private var errorMessage: String?
    @State private var needsStepUp = false
    @State private var stepUpPassword = ""
    @State private var stepUpCode = ""
    @State private var emailCode = ""
    @State private var emailChallenge: PairV2EmailChallenge?
    @State private var stepUpMethods: PairV2StepUpMethods?

    var body: some View {
        OMSettingsPage(title: AppStrings.pairConnectAppleWatchTitle, showsFooter: false) {
            OMSettingsSection {
                VStack(spacing: .spacing6) {
                    Icon("watch", size: 48).foregroundStyle(LinearGradient.primary)
                    Text(AppStrings.pairConnectAppleWatchDescription)
                        .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    if let request = bridge.pendingRequest {
                        OMSettingsStaticRow(title: AppStrings.device, value: request.deviceName)
                        Text(request.token).font(.omH2.monospaced()).textSelection(.enabled)
                    }
                    if let errorMessage { Text(errorMessage).font(.omSmall).foregroundStyle(Color.error) }
                    if needsStepUp {
                        Text(AppStrings.pairStepUpDescription)
                            .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        if emailChallenge == nil && stepUpMethods?.supports(.passkey) == true {
                            Button(AppStrings.loginWithPasskey) { Task { await submitPasskeyStepUp() } }
                                .buttonStyle(OMSecondaryButtonStyle())
                                .accessibilityIdentifier("watch-pair-step-up-passkey")
                        }
                        if emailChallenge != nil {
                            TextField(AppStrings.enterOneTimeCode, text: $emailCode)
                                .textFieldStyle(OMTextFieldStyle())
                                .keyboardType(.numberPad)
                                .onChange(of: emailCode) { _, value in
                                    emailCode = String(value.filter(\.isNumber).prefix(6))
                                }
                                .accessibilityIdentifier("watch-pair-step-up-email-code")
                            Button(AppStrings.verifyEmailChangeCode) { Task { await submitEmailCode() } }
                                .buttonStyle(OMPrimaryButtonStyle())
                                .disabled(emailCode.count != 6 || isApproving)
                                .accessibilityIdentifier("watch-pair-step-up-email-verify")
                            Button(AppStrings.retry) {
                                emailChallenge = nil
                                emailCode = ""
                                errorMessage = nil
                            }
                            .buttonStyle(OMSecondaryButtonStyle())
                        } else if stepUpMethods?.supports(.password) == true && stepUpMethods?.supports(.otp) != true {
                            SecureField(AppStrings.enterPassword, text: $stepUpPassword)
                                .textFieldStyle(OMTextFieldStyle())
                                .accessibilityIdentifier("watch-pair-step-up-password")
                        }
                        if emailChallenge == nil && stepUpMethods?.supports(.otp) == true {
                            TextField(AppStrings.twoFactorCodePlaceholder, text: $stepUpCode)
                                .textFieldStyle(OMTextFieldStyle())
                                .keyboardType(.numberPad)
                                .onChange(of: stepUpCode) { _, value in
                                    stepUpCode = String(value.filter(\.isNumber).prefix(6))
                                }
                                .accessibilityIdentifier("watch-pair-step-up-code")
                        }
                        if emailChallenge == nil && (stepUpMethods?.supports(.password) == true || stepUpMethods?.supports(.otp) == true) {
                            Button(AppStrings.allow) { Task { await submitCredentialStepUp() } }
                                .buttonStyle(OMPrimaryButtonStyle())
                                .disabled(stepUpMethods?.supports(.otp) == true ? stepUpCode.count != 6 : stepUpPassword.isEmpty)
                        }
                    }
                    HStack(spacing: .spacing4) {
                        Button(AppStrings.cancel) { bridge.denyPendingRequest(); onDone() }
                            .buttonStyle(OMSecondaryButtonStyle())
                        Button(AppStrings.pairApproveWatchLogin) { approve() }
                            .buttonStyle(OMPrimaryButtonStyle())
                            .disabled(isApproving || needsStepUp || bridge.pendingRequest == nil)
                    }
                }
                .padding(.spacing8)
            }
        }
        .task(id: bridge.pendingRequest?.token) {
            emailChallenge = nil
            emailCode = ""
            stepUpPassword = ""
            stepUpCode = ""
            needsStepUp = false
            guard let profile = bridge.pendingRequest?.serverProfile else { return }
            stepUpMethods = try? await PairV2Runtime.stepUpMethods(serverProfile: profile)
        }
        .onDisappear {
            stepUpPassword = ""
            stepUpCode = ""
            emailCode = ""
            emailChallenge = nil
        }
    }

    private func approve() {
        isApproving = true
        Task {
            do {
                try await bridge.approvePendingRequest(authManager: authManager)
                onDone()
            } catch APIError.httpError(let status, _) where status == 401 || status == 403 || status == 428 {
                needsStepUp = true
                errorMessage = nil
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Watch pair approval failed", category: "settings.security")
            }
            isApproving = false
        }
    }

    private func submitPasskeyStepUp() async {
        guard let user = authManager.currentUser else { return }
        isApproving = true
        do {
            try await PasskeyLoginCoordinator.verifyCurrentSessionAssertion(expectedUserID: user.id)
            emailChallenge = nil
            emailCode = ""
            needsStepUp = false
            isApproving = false
            approve()
            return
        } catch {
            errorMessage = error.localizedDescription
        }
        isApproving = false
    }

    private func submitCredentialStepUp() async {
        guard let user = authManager.currentUser,
              let profile = bridge.pendingRequest?.serverProfile else { return }
        isApproving = true
        do {
            if !stepUpCode.isEmpty {
                try await PairV2Runtime.stepUp(
                    code: stepUpCode,
                    serverProfile: profile
                )
            } else {
                emailChallenge = try await PairV2Runtime.requestEmailStepUp(
                    user: user, password: stepUpPassword,
                    serverProfile: profile
                )
                stepUpPassword = ""
                isApproving = false
                return
            }
            stepUpPassword = ""
            stepUpCode = ""
            needsStepUp = false
            isApproving = false
            approve()
            return
        } catch {
            stepUpPassword = ""
            stepUpCode = ""
            errorMessage = error.localizedDescription
        }
        isApproving = false
    }

    private func submitEmailCode() async {
        guard let challenge = emailChallenge,
              let profile = bridge.pendingRequest?.serverProfile else { return }
        isApproving = true
        do {
            try await PairV2Runtime.verifyEmailStepUp(
                challenge, code: emailCode, serverProfile: profile
            )
            emailChallenge = nil
            emailCode = ""
            errorMessage = nil
            needsStepUp = false
            isApproving = false
            approve()
            return
        } catch {
            emailCode = ""
            errorMessage = error.localizedDescription
        }
        isApproving = false
    }
}
#endif

struct SettingsConfirmPairView: View {
    @State private var token = ""
    @State private var submittedToken: String?

    var body: some View {
        if let submittedToken {
            CLIPairAuthorizeView(token: submittedToken)
        } else {
            OMSettingsPage(title: AppStrings.confirmPairing) {
                OMSettingsSection {
                    VStack(spacing: .spacing5) {
                        TextField(AppStrings.pairingCode, text: $token)
                            .textFieldStyle(OMTextFieldStyle())
                            .autocorrectionDisabled()
                            #if os(iOS)
                            .textInputAutocapitalization(.characters)
                            #endif
                        Button(AppStrings.confirmPairing) {
                            submittedToken = token.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
                        }
                        .buttonStyle(OMPrimaryButtonStyle())
                        .disabled(token.count < 4)
                    }
                    .padding(.spacing6)
                }
            }
        }
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
