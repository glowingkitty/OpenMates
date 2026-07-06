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
import CoreImage.CIFilterBuiltins

#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

@MainActor
final class PhonePairLoginState: ObservableObject {
    @Published var token: String?
    @Published var pairURLString: String?
    @Published var qrImage: Image?
    @Published var status: PairLoginStatus = .generating
    @Published var pin = ""
    @Published var errorMessage: String?
    @Published var isSubmitting = false

    var pollTask: Task<Void, Never>?

    deinit {
        pollTask?.cancel()
    }

    func reset() {
        pollTask?.cancel()
        pollTask = nil
        token = nil
        pairURLString = nil
        qrImage = nil
        status = .generating
        pin = ""
        errorMessage = nil
        isSubmitting = false
    }
}

struct PhonePairLoginView: View {
    @EnvironmentObject private var authManager: AuthManager
    @Binding var stayLoggedIn: Bool
    @ObservedObject var pairState: PhonePairLoginState
    @FocusState private var isPinFocused: Bool

    var body: some View {
        VStack(spacing: .spacing6) {
            statusView

            if pairState.qrImage != nil {
                VStack(spacing: .spacing5) {
                    qrSection
                    pinSection
                    urlSection
                }
                .transition(.opacity.combined(with: .move(edge: .top)))
            }

            if pairState.status == .expired || pairState.status == .failed {
                Button(AppStrings.pairRefresh) {
                    Task { await initiatePairing(force: true) }
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .accessibilityIdentifier("pair-refresh-button")
                .accessibleButton(AppStrings.pairRefresh, hint: AppStrings.pairRefresh)
            }
        }
        .task { await initiatePairingIfNeeded() }
    }

    @ViewBuilder
    private var statusView: some View {
        switch pairState.status {
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
            messageBox(text: pairState.errorMessage ?? AppStrings.loginFailed, isError: true)
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

            if let qrImage = pairState.qrImage {
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

            TextField(AppStrings.pairPinPlaceholder, text: $pairState.pin)
                .textFieldStyle(PairPinFieldStyle())
                #if os(iOS)
                .keyboardType(.asciiCapable)
                .textInputAutocapitalization(.characters)
                #endif
                .autocorrectionDisabled(true)
                .focused($isPinFocused)
                .onChange(of: pairState.pin) { _, newValue in
                    sanitizeAndSubmitPin(newValue)
                }
                .disabled(pairState.status != .ready || pairState.isSubmitting)
                .accessibilityIdentifier("pair-pin-input")
                .accessibleInput(AppStrings.pairEnterPinTitle, hint: AppStrings.pairEnterPinDescription)

            if pairState.isSubmitting {
                Text(AppStrings.pairLoggingIn)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
            } else if let errorMessage = pairState.errorMessage {
                messageBox(text: errorMessage, isError: true)
            }
        }
    }

    @ViewBuilder
    private var urlSection: some View {
        if let pairURLString = pairState.pairURLString {
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

    private func initiatePairingIfNeeded() async {
        if let token = pairState.token {
            if pairState.status == .waiting, pairState.pollTask == nil {
                startPolling(token: token)
            }
            return
        }
        await initiatePairing(force: false)
    }

    private func initiatePairing(force: Bool) async {
        if !force, pairState.token != nil {
            return
        }
        pairState.reset()

        do {
            let initiation = try await PairLoginRuntime.initiate()
            pairState.token = initiation.token
            pairState.pairURLString = initiation.pairURLString
            pairState.qrImage = generateQRCode(from: initiation.pairURLString)
            pairState.status = .waiting
            startPolling(token: initiation.token)
        } catch {
            pairState.errorMessage = error.localizedDescription
            pairState.status = .failed
        }
    }

    private func startPolling(token: String) {
        pairState.pollTask?.cancel()
        pairState.pollTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(3))
                if Task.isCancelled { return }

                do {
                    let response = try await PairLoginRuntime.poll(token: token)

                    await MainActor.run {
                        if response.status == "ready" {
                            pairState.status = .ready
                            isPinFocused = true
                            if pairState.pin.count == 6 {
                                submitPinIfReady()
                            }
                        } else if response.status == "expired" {
                            pairState.status = .expired
                        }
                    }

                    if response.status == "ready" || response.status == "expired" {
                        return
                    }
                } catch {
                    await MainActor.run {
                        pairState.errorMessage = error.localizedDescription
                        pairState.status = .failed
                    }
                    return
                }
            }
        }
    }

    private func sanitizeAndSubmitPin(_ rawValue: String) {
        let sanitized = PairLoginRuntime.normalizedPIN(rawValue)
        if sanitized != rawValue {
            pairState.pin = sanitized
            return
        }
        pairState.errorMessage = nil
        if sanitized.count == 6 {
            submitPinIfReady()
        }
    }

    private func submitPinIfReady() {
        guard pairState.status == .ready,
              !pairState.isSubmitting,
              pairState.pin.count == 6,
              let token = pairState.token else { return }
        pairState.isSubmitting = true
        pairState.errorMessage = nil

        Task {
            do {
                let result = try await PairLoginRuntime.complete(token: token, pin: pairState.pin, stayLoggedIn: stayLoggedIn)
                try await authManager.completePairLogin(response: result.loginResponse, masterKey: result.masterKey)
            } catch PairLoginRuntimeError.completeFailed(let kind) {
                handlePairCompleteFailure(kind)
            } catch {
                pairState.errorMessage = error.localizedDescription
                pairState.isSubmitting = false
            }
        }
    }

    private func handlePairCompleteFailure(_ kind: PairLoginCompleteFailureKind) {
        pairState.isSubmitting = false
        pairState.pin = ""

        if kind == .tooManyAttempts {
            pairState.errorMessage = AppStrings.pairPinLocked
            pairState.status = .expired
            return
        }

        if case .invalidPIN(let attempts) = kind {
            pairState.errorMessage = AppStrings.pairPinError(attempts: attempts)
            return
        }

        if kind == .expired {
            pairState.status = .expired
            pairState.errorMessage = AppStrings.pairExpired
            return
        }

        pairState.errorMessage = AppStrings.loginFailed
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
