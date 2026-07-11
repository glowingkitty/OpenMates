// Native device pairing for Apple apps, CLI authorization, and Apple Watch.
// Uses the real pair initiate/info/authorize/poll/complete contracts and the
// shared PairLoginRuntime encryption implementation without browser fallbacks.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/security/SettingsSessionsPairInitiate.svelte
//          frontend/packages/ui/src/components/settings/security/SettingsSessionsConfirmPair.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import CoreImage.CIFilterBuiltins
import SwiftUI

struct SettingsPairInitiateView: View {
    @State private var response: PairInitiateResponse?
    @State private var qrImage: Image?
    @State private var state: PairingState = .idle
    @State private var errorMessage: String?

    private enum PairingState: Equatable { case idle, generating, waiting, completed, expired }

    var body: some View {
        OMSettingsPage(title: AppStrings.pairNewDevice) {
            OMSettingsSection(AppStrings.pairNewDevice, icon: "devices") {
                VStack(spacing: .spacing6) {
                    Text(AppStrings.pairScanDescription)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                        .multilineTextAlignment(.center)

                    if let qrImage {
                        qrImage
                            .interpolation(.none)
                            .resizable()
                            .scaledToFit()
                            .frame(width: 200, height: 200)
                            .padding(.spacing4)
                            .background(Color.white)
                            .clipShape(RoundedRectangle(cornerRadius: .radius4))
                            .accessibilityLabel(AppStrings.pairingQRCode)
                    }

                    if let response {
                        Text(response.token)
                            .font(.omH2.monospaced())
                            .fontWeight(.bold)
                            .foregroundStyle(Color.buttonPrimary)
                            .textSelection(.enabled)
                        Button(AppStrings.pairCopyLink) { copyPairLink(response.token) }
                            .buttonStyle(OMSecondaryButtonStyle())
                            .accessibilityIdentifier("settings-pair-copy-link")
                    }

                    stateView
                    if let errorMessage { Text(errorMessage).font(.omSmall).foregroundStyle(Color.error) }
                }
                .frame(maxWidth: .infinity)
                .padding(.spacing8)
            }
        }
        .accessibilityIdentifier("settings-pair-initiate-page")
    }

    @ViewBuilder
    private var stateView: some View {
        switch state {
        case .idle, .expired:
            Button(state == .expired ? AppStrings.pairRefresh : AppStrings.pairGenerating) { generate() }
                .buttonStyle(OMPrimaryButtonStyle())
                .accessibilityIdentifier("settings-pair-generate")
        case .generating:
            ProgressView().accessibilityLabel(AppStrings.pairGenerating)
        case .waiting:
            Text(AppStrings.pairWaiting).font(.omSmall).foregroundStyle(Color.fontSecondary)
        case .completed:
            Text(AppStrings.devicePaired).font(.omSmall).foregroundStyle(Color.buttonPrimary)
        }
    }

    private func generate() {
        state = .generating
        errorMessage = nil
        Task {
            do {
                let result: PairInitiateResponse = try await APIClient.shared.request(
                    .post,
                    path: "/v1/auth/pair/initiate",
                    body: PairInitiateRequest(deviceHint: deviceHint)
                )
                response = result
                let link = await pairLink(token: result.token)
                qrImage = qrCode(link.absoluteString)
                state = .waiting
                await poll(token: result.token, attempts: max(1, result.expiresIn / 3))
            } catch is CancellationError {
                return
            } catch {
                errorMessage = error.localizedDescription
                state = .idle
                NativeDiagnostics.error("Pair initiation failed", category: "settings.security")
            }
        }
    }

    private func poll(token: String, attempts: Int) async {
        for _ in 0..<attempts {
            do {
                try await Task.sleep(for: .seconds(3))
                let value: PairPollResponse = try await APIClient.shared.request(
                    .get,
                    path: "/v1/auth/pair/poll/\(token)"
                )
                if value.status == "completed" { state = .completed; return }
            } catch is CancellationError {
                return
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Pair polling failed", category: "settings.security")
                return
            }
        }
        state = .expired
    }

    private func copyPairLink(_ token: String) {
        Task {
            let link = await pairLink(token: token)
            CopyMessageFormatter.copyToClipboard(link.absoluteString)
            ToastManager.shared.show(AppStrings.pairCopied, type: .success)
        }
    }

    private func pairLink(token: String) async -> URL {
        (await APIClient.shared.webAppURL)
            .appendingPathComponent("pair")
            .appending(queryItems: [URLQueryItem(name: "code", value: token)])
    }

    private func qrCode(_ value: String) -> Image? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(value.utf8)
        guard let output = filter.outputImage else { return nil }
        let scaled = output.transformed(by: CGAffineTransform(scaleX: 10, y: 10))
        guard let image = CIContext().createCGImage(scaled, from: scaled.extent) else { return nil }
        #if os(iOS)
        return Image(uiImage: UIImage(cgImage: image))
        #elseif os(macOS)
        return Image(nsImage: NSImage(cgImage: image, size: NSSize(width: 200, height: 200)))
        #endif
    }

    private var deviceHint: String {
        #if os(iOS)
        UIDevice.current.userInterfaceIdiom == .pad ? "OpenMates iPadOS" : "OpenMates iOS"
        #elseif os(macOS)
        "OpenMates macOS"
        #endif
    }
}

struct CLIPairAuthorizeView: View {
    let token: String
    @EnvironmentObject private var authManager: AuthManager
    @Environment(\.dismiss) private var dismiss
    @State private var info: PairInfoResponse?
    @State private var pin: String?
    @State private var state: State = .loading
    @State private var errorMessage: String?

    private enum State { case loading, confirm, authorizing, pin, completed, failed }

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
            HStack(spacing: .spacing4) {
                Button(AppStrings.deny) { dismiss() }.buttonStyle(OMSecondaryButtonStyle())
                Button(AppStrings.allow) { authorize() }.buttonStyle(OMPrimaryButtonStyle())
            }
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
        do {
            let loaded: PairInfoResponse = try await APIClient.shared.request(.get, path: "/v1/auth/pair/info/\(token)")
            guard loaded.valid else { throw AccountSecurityError.server(loaded.reason) }
            info = loaded
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
                    authorizerDeviceName: deviceName
                )
                state = .pin
                await pollCompletion()
            } catch {
                fail(error, operation: "Pair authorization")
            }
        }
    }

    private func pollCompletion() async {
        for _ in 0..<100 {
            do {
                try await Task.sleep(for: .seconds(3))
                let value: PairPollResponse = try await APIClient.shared.request(.get, path: "/v1/auth/pair/poll/\(token)")
                if value.status == "completed" { state = .completed; return }
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
                    HStack(spacing: .spacing4) {
                        Button(AppStrings.cancel) { bridge.denyPendingRequest(); onDone() }
                            .buttonStyle(OMSecondaryButtonStyle())
                        Button(AppStrings.pairApproveWatchLogin) { approve() }
                            .buttonStyle(OMPrimaryButtonStyle())
                            .disabled(isApproving || bridge.pendingRequest == nil)
                    }
                }
                .padding(.spacing8)
            }
        }
    }

    private func approve() {
        isApproving = true
        Task {
            do {
                try await bridge.approvePendingRequest(authManager: authManager)
                onDone()
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Watch pair approval failed", category: "settings.security")
            }
            isApproving = false
        }
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
