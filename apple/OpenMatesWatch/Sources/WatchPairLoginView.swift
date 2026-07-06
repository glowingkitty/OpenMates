// Watch QR/PIN pair-login view.
// Presents the existing OpenMates Magic Pair Login flow in a compact standalone
// watchOS layout: generate QR code, poll authorization state, then auto-submit a
// sanitized six-character PIN. Runtime logic lives in PairLoginRuntime.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/Login.svelte
//          frontend/packages/ui/src/components/settings/SettingsSessionsPairInitiate.svelte
// Backend: backend/core/api/routes/auth_pair.py
// CSS:     frontend/packages/ui/src/styles/auth.css, buttons.css, fields.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import CoreImage.CIFilterBuiltins
import SwiftUI

@MainActor
final class WatchPairLoginState: ObservableObject {
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

struct WatchPairLoginView: View {
    @ObservedObject var authStore: WatchAuthStore
    @StateObject private var pairState = WatchPairLoginState()

    var body: some View {
        ZStack {
            Color.grey100.ignoresSafeArea()

            ScrollView {
                VStack(spacing: .spacing4) {
                    statusView

                    if let qrImage = pairState.qrImage {
                        qrImage
                            .interpolation(.none)
                            .resizable()
                            .scaledToFit()
                            .frame(width: 118, height: 118)
                            .padding(.spacing2)
                            .background(Color.white)
                            .clipShape(RoundedRectangle(cornerRadius: .radius4))
                            .accessibilityLabel(WatchStrings.scanCode)
                            .accessibilityIdentifier("watch-pair-qr-code")
                    }

                    if pairState.status == .ready {
                        pinSection
                    }

                    if pairState.status == .expired || pairState.status == .failed {
                        Button {
                            Task { await initiatePairing(force: true) }
                        } label: {
                            Text(WatchStrings.pairRefresh)
                                .font(.omSmall)
                                .fontWeight(.semibold)
                                .foregroundStyle(Color.fontButton)
                                .padding(.horizontal, .spacing4)
                                .padding(.vertical, .spacing2)
                                .background(LinearGradient.primary)
                                .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("watch-pair-refresh-button")
                    }
                }
                .padding(.horizontal, .spacing3)
                .padding(.vertical, .spacing4)
            }
        }
        .task { await initiatePairingIfNeeded() }
        .accessibilityIdentifier("watch-pair-login")
    }

    @ViewBuilder
    private var statusView: some View {
        switch pairState.status {
        case .generating:
            VStack(spacing: .spacing2) {
                ProgressView()
                    .controlSize(.small)
                    .tint(Color.grey0)
                Text(WatchStrings.pairGenerating)
                    .font(.omXs)
                    .foregroundStyle(Color.grey0.opacity(0.82))
                    .multilineTextAlignment(.center)
            }
        case .waiting:
            Text(WatchStrings.pairWaiting)
                .font(.omXs)
                .foregroundStyle(Color.grey0.opacity(0.82))
                .multilineTextAlignment(.center)
                .accessibilityIdentifier("watch-pair-waiting-label")
        case .ready:
            EmptyView()
        case .expired:
            messageBox(text: WatchStrings.pairExpired)
        case .failed:
            messageBox(text: pairState.errorMessage ?? WatchStrings.loginFailed)
        }
    }

    private var pinSection: some View {
        VStack(spacing: .spacing2) {
            Text(WatchStrings.pairEnterPinTitle)
                .font(.omSmall)
                .fontWeight(.semibold)
                .foregroundStyle(Color.grey0)
                .multilineTextAlignment(.center)

            Text(WatchStrings.pairEnterPinDescription)
                .font(.omXs)
                .foregroundStyle(Color.grey0.opacity(0.72))
                .multilineTextAlignment(.center)

            TextField(WatchStrings.pairPinPlaceholder, text: $pairState.pin)
                .font(.omP.monospaced())
                .fontWeight(.bold)
                .foregroundStyle(Color.fontPrimary)
                .multilineTextAlignment(.center)
                .padding(.vertical, .spacing2)
                .padding(.horizontal, .spacing3)
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: .radius4))
                .onChange(of: pairState.pin) { _, newValue in sanitizeAndSubmitPin(newValue) }
                .disabled(pairState.isSubmitting)
                .accessibilityIdentifier("watch-pair-pin-input")

            if pairState.isSubmitting {
                Text(WatchStrings.pairLoggingIn)
                    .font(.omXs)
                    .foregroundStyle(Color.grey0.opacity(0.72))
                    .multilineTextAlignment(.center)
            } else if let errorMessage = pairState.errorMessage {
                messageBox(text: errorMessage)
            }
        }
    }

    private func messageBox(text: String) -> some View {
        Text(text)
            .font(.omXs)
            .foregroundStyle(Color.grey0)
            .multilineTextAlignment(.center)
            .padding(.spacing2)
            .frame(maxWidth: .infinity)
            .background(Color.error.opacity(0.35))
            .clipShape(RoundedRectangle(cornerRadius: .radius4))
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
        if !force, pairState.token != nil { return }
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
                            if pairState.pin.count == 6 { submitPinIfReady() }
                        } else if response.status == "expired" {
                            pairState.status = .expired
                        }
                    }
                    if response.status == "ready" || response.status == "expired" { return }
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
        if sanitized.count == 6 { submitPinIfReady() }
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
                let result = try await PairLoginRuntime.complete(token: token, pin: pairState.pin, stayLoggedIn: true)
                try await authStore.completePairLogin(result)
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
        switch kind {
        case .tooManyAttempts:
            pairState.errorMessage = WatchStrings.pairPinLocked
            pairState.status = .expired
        case .invalidPIN(let attempts):
            pairState.errorMessage = WatchStrings.pairPinError(attempts: attempts)
        case .expired:
            pairState.status = .expired
            pairState.errorMessage = WatchStrings.pairExpired
        case .generic:
            pairState.errorMessage = WatchStrings.loginFailed
        }
    }

    private func generateQRCode(from string: String) -> Image? {
        let context = CIContext()
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(string.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage else { return nil }
        let scaled = output.transformed(by: CGAffineTransform(scaleX: 8, y: 8))
        guard let cgImage = context.createCGImage(scaled, from: scaled.extent) else { return nil }
        return Image(decorative: cgImage, scale: 1, orientation: .up)
    }
}
