// Phone / PC login — initiating device flow for Magic Pair Login.
// Auto-generates the QR code, polls until the other device authorizes,
// then decrypts the pair bundle with the 6-character PIN and logs in.
// This is intentionally separate from the settings authorizer screen.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/Login.svelte
//          frontend/packages/ui/src/components/settings/SettingsSessionsPairInitiate.svelte
// Backend: backend/core/api/routes/auth_pair.py
// CSS:     frontend/packages/ui/src/styles/auth.css, buttons.css, fields.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import CryptoKit
import CoreImage.CIFilterBuiltins

#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct PhonePairLoginView: View {
    @EnvironmentObject private var authManager: AuthManager
    @Binding var stayLoggedIn: Bool

    @State private var token: String?
    @State private var pairURLString: String?
    @State private var qrImage: Image?
    @State private var status: PairStatus = .generating
    @State private var pin = ""
    @State private var errorMessage: String?
    @State private var isSubmitting = false
    @State private var pollTask: Task<Void, Never>?
    @FocusState private var isPinFocused: Bool

    private enum PairStatus: Equatable {
        case generating
        case waiting
        case ready
        case expired
        case failed
    }

    var body: some View {
        VStack(spacing: .spacing6) {
            statusView

            if qrImage != nil {
                VStack(spacing: .spacing5) {
                    qrSection
                    pinSection
                    urlSection
                }
                .transition(.opacity.combined(with: .move(edge: .top)))
            }

            if status == .expired || status == .failed {
                Button(AppStrings.pairRefresh) {
                    Task { await initiatePairing() }
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .accessibilityIdentifier("pair-refresh-button")
                .accessibleButton(AppStrings.pairRefresh, hint: AppStrings.pairRefresh)
            }
        }
        .task { await initiatePairing() }
        .onDisappear {
            pollTask?.cancel()
            pollTask = nil
        }
    }

    @ViewBuilder
    private var statusView: some View {
        switch status {
        case .generating:
            VStack(spacing: .spacing3) {
                ProgressView()
                    .tint(Color.buttonPrimary)
                Text(AppStrings.pairGenerating)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
            }
        case .waiting:
            Text(AppStrings.pairWaiting)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)
        case .ready:
            EmptyView()
        case .expired:
            messageBox(text: AppStrings.pairExpired, isError: true)
        case .failed:
            messageBox(text: errorMessage ?? AppStrings.loginFailed, isError: true)
        }
    }

    private var qrSection: some View {
        VStack(spacing: .spacing3) {
            HStack(spacing: .spacing2) {
                Icon("camera", size: 18)
                    .foregroundStyle(Color.fontPrimary)
                Text(AppStrings.pairScanCode)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
            }
            .frame(maxWidth: .infinity)

            if let qrImage {
                qrImage
                    .interpolation(.none)
                    .resizable()
                    .scaledToFit()
                    .frame(width: 200, height: 200)
                    .padding(.spacing3)
                    .background(Color.white)
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
                    .overlay(
                        RoundedRectangle(cornerRadius: .radius5)
                            .stroke(Color.grey25, lineWidth: 1)
                    )
                    .accessibilityLabel(AppStrings.localized("settings.sessions.pair_code_label"))
            }
        }
    }

    private var pinSection: some View {
        VStack(spacing: .spacing3) {
            Text(AppStrings.pairEnterPinTitle)
                .font(.omH4)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)

            Text(AppStrings.pairEnterPinDescription)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)

            TextField(AppStrings.pairPinPlaceholder, text: $pin)
                .textFieldStyle(PairPinFieldStyle())
                #if os(iOS)
                .keyboardType(.asciiCapable)
                .textInputAutocapitalization(.characters)
                #endif
                .autocorrectionDisabled(true)
                .focused($isPinFocused)
                .onChange(of: pin) { _, newValue in
                    sanitizeAndSubmitPin(newValue)
                }
                .disabled(status != .ready || isSubmitting)
                .accessibilityIdentifier("pair-pin-input")
                .accessibleInput(AppStrings.pairEnterPinTitle, hint: AppStrings.pairEnterPinDescription)

            if isSubmitting {
                Text(AppStrings.pairLoggingIn)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
            } else if let errorMessage {
                messageBox(text: errorMessage, isError: true)
            }
        }
    }

    @ViewBuilder
    private var urlSection: some View {
        if let pairURLString {
            VStack(alignment: .leading, spacing: .spacing3) {
                Text(AppStrings.pairUrlLabel)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                    .frame(maxWidth: .infinity, alignment: .center)

                HStack(spacing: .spacing3) {
                    Text(pairURLString)
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity)

                    Button(AppStrings.pairCopyLink) {
                        CopyMessageFormatter.copyToClipboard(pairURLString)
                        ToastManager.shared.show(AppStrings.pairCopied, type: .success)
                        AccessibilityAnnouncement.announce(AppStrings.pairCopied)
                    }
                    .buttonStyle(OMSecondaryButtonStyle())
                    .accessibilityIdentifier("pair-copy-link-button")
                    .accessibleButton(AppStrings.pairCopyLink, hint: AppStrings.pairCopyLink)
                }
            }
            .padding(.spacing4)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius4))
            .overlay(
                RoundedRectangle(cornerRadius: .radius4)
                    .stroke(Color.grey25, lineWidth: 1)
            )
        }
    }

    private func messageBox(text: String, isError: Bool) -> some View {
        Text(text)
            .font(.omSmall)
            .foregroundStyle(isError ? Color.error : Color.fontPrimary)
            .multilineTextAlignment(.center)
            .padding(.spacing3)
            .frame(maxWidth: .infinity)
            .background(isError ? Color.error.opacity(0.12) : Color.buttonPrimary.opacity(0.12))
            .clipShape(RoundedRectangle(cornerRadius: .radius3))
            .overlay(
                RoundedRectangle(cornerRadius: .radius3)
                    .stroke(isError ? Color.error.opacity(0.35) : Color.buttonPrimary.opacity(0.35), lineWidth: 1)
            )
    }

    private func initiatePairing() async {
        pollTask?.cancel()
        pollTask = nil
        token = nil
        pairURLString = nil
        qrImage = nil
        pin = ""
        errorMessage = nil
        isSubmitting = false
        status = .generating

        do {
            let response: PairInitiateResponse = try await APIClient.shared.request(
                .post,
                path: "/v1/auth/pair/initiate",
                body: PairInitiateRequest(deviceHint: officialAppDeviceHint)
            )
            let upperToken = response.token.uppercased()
            token = upperToken
            let pairURL = await buildPairURL(token: upperToken)
            pairURLString = pairURL
            qrImage = generateQRCode(from: pairURL)
            status = .waiting
            startPolling(token: upperToken)
        } catch {
            errorMessage = error.localizedDescription
            status = .failed
        }
    }

    private func startPolling(token: String) {
        pollTask?.cancel()
        pollTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(3))
                if Task.isCancelled { return }

                do {
                    let response: PairPollResponse = try await APIClient.shared.request(
                        .get,
                        path: "/v1/auth/pair/poll/\(token)"
                    )

                    await MainActor.run {
                        if response.status == "ready" {
                            status = .ready
                            isPinFocused = true
                            if pin.count == 6 {
                                submitPinIfReady()
                            }
                        } else if response.status == "expired" {
                            status = .expired
                        }
                    }

                    if response.status == "ready" || response.status == "expired" {
                        return
                    }
                } catch {
                    await MainActor.run {
                        errorMessage = error.localizedDescription
                        status = .failed
                    }
                    return
                }
            }
        }
    }

    private func sanitizeAndSubmitPin(_ rawValue: String) {
        let sanitized = String(
            rawValue
                .uppercased()
                .filter { $0.isLetter || $0.isNumber }
                .prefix(6)
        )
        if sanitized != rawValue {
            pin = sanitized
            return
        }
        errorMessage = nil
        if sanitized.count == 6 {
            submitPinIfReady()
        }
    }

    private func submitPinIfReady() {
        guard status == .ready, !isSubmitting, pin.count == 6, let token else { return }
        isSubmitting = true
        errorMessage = nil

        Task {
            do {
                let completeResponse: PairCompleteResponse = try await APIClient.shared.request(
                    .post,
                    path: "/v1/auth/pair/complete/\(token)",
                    body: PairCompleteRequest(pin: pin)
                )

                guard completeResponse.success else {
                    handlePairCompleteFailure(completeResponse.message)
                    return
                }

                let (bundle, masterKey) = try await decryptLoginBundle(from: completeResponse, token: token, pin: pin)
                let loginResponse: LoginResponse = try await APIClient.shared.request(
                    .post,
                    path: "/v1/auth/login",
                    body: LoginRequest(
                        hashedEmail: bundle.hashedEmail,
                        lookupHash: bundle.lookupHash,
                        loginMethod: "pair",
                        tfaCode: nil,
                        codeType: nil,
                        emailEncryptionKey: nil,
                        stayLoggedIn: stayLoggedIn,
                        sessionId: AuthManager.nativeSessionId,
                        deviceInfo: AuthManager.makeNativeDeviceInfo()
                    )
                )

                try await authManager.completePairLogin(response: loginResponse, masterKey: masterKey)
            } catch {
                errorMessage = error.localizedDescription
                isSubmitting = false
            }
        }
    }

    private func handlePairCompleteFailure(_ message: String?) {
        isSubmitting = false
        pin = ""

        if message == "too_many_attempts" {
            errorMessage = AppStrings.pairPinLocked
            status = .expired
            return
        }

        if let message, message.hasPrefix("invalid_pin:") {
            let attempts = message.split(separator: ":").last.map(String.init) ?? "0"
            errorMessage = AppStrings.pairPinError(attempts: attempts)
            return
        }

        if message == "expired" {
            status = .expired
            errorMessage = AppStrings.pairExpired
            return
        }

        errorMessage = AppStrings.loginFailed
    }

    private func decryptLoginBundle(
        from response: PairCompleteResponse,
        token: String,
        pin: String
    ) async throws -> (PairLoginBundle, SymmetricKey) {
        guard let encryptedBundle = response.encryptedBundle,
              let iv = response.iv,
              let encryptedData = Data(base64Encoded: encryptedBundle),
              let ivData = Data(base64Encoded: iv) else {
            throw AuthError.missingAuthData
        }

        let pairKey = await CryptoManager.shared.derivePairLoginKey(pin: pin, token: token)
        let plaintext = try await CryptoManager.shared.decryptAESGCM(
            ciphertext: encryptedData,
            iv: ivData,
            key: pairKey
        )
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let bundle = try decoder.decode(PairLoginBundle.self, from: plaintext)
        guard let masterKeyData = Data(base64Encoded: bundle.masterKeyExported) else {
            throw AuthError.missingAuthData
        }
        return (bundle, SymmetricKey(data: masterKeyData))
    }

    private func buildPairURL(token: String) async -> String {
        let webURL = await APIClient.shared.webAppURL
        if let scheme = webURL.scheme, let host = webURL.host {
            return "\(scheme)://\(host)/#pair=\(token)"
        }
        return "\(webURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")))/#pair=\(token)"
    }

    private var officialAppDeviceHint: String {
        #if os(iOS)
        if UIDevice.current.userInterfaceIdiom == .pad {
            return "OpenMates iPadOS app"
        }
        return "OpenMates iOS app"
        #elseif os(macOS)
        return "OpenMates macOS app"
        #else
        return "OpenMates Apple app"
        #endif
    }

    private func generateQRCode(from string: String) -> Image? {
        let context = CIContext()
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(string.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage else { return nil }
        let scaled = output.transformed(by: CGAffineTransform(scaleX: 10, y: 10))
        guard let cgImage = context.createCGImage(scaled, from: scaled.extent) else { return nil }

        #if os(iOS)
        return Image(uiImage: UIImage(cgImage: cgImage))
        #elseif os(macOS)
        return Image(nsImage: NSImage(cgImage: cgImage, size: NSSize(width: 200, height: 200)))
        #endif
    }
}

private struct PairPinFieldStyle: TextFieldStyle {
    func _body(configuration: TextField<Self._Label>) -> some View {
        configuration
            .font(.omH3.monospaced())
            .fontWeight(.bold)
            .foregroundStyle(Color.fontPrimary)
            .multilineTextAlignment(.center)
            .padding(.vertical, .spacing3)
            .padding(.horizontal, .spacing4)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius4))
            .overlay(
                RoundedRectangle(cornerRadius: .radius4)
                    .stroke(Color.grey30, lineWidth: 1)
            )
    }
}
