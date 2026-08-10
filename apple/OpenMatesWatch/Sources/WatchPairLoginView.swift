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

import SwiftUI

private let watchPairLoginDiagnosticsCategory = "watch_pair_login"

@MainActor
final class WatchPairLoginState: ObservableObject {
    @Published var token: String?
    @Published var activeTokenServerProfile: ServerProfile?
    @Published var pairURLString: String?
    @Published var status: PairLoginStatus = .generating
    @Published var pin = ""
    @Published var errorMessage: String?
    @Published var isSubmitting = false
    @Published var serverProfile = WatchServerProfileStore().currentProfile()
    @Published var customDomain = ""

    var attemptState = WatchPairAttemptState()
    var initiationTask: Task<Void, Never>?
    var pollTask: Task<Void, Never>?

    deinit {
        initiationTask?.cancel()
        pollTask?.cancel()
    }

    @discardableResult
    func beginAttempt(serverProfile: ServerProfile) -> Int {
        initiationTask?.cancel()
        pollTask?.cancel()
        initiationTask = nil
        pollTask = nil
        token = nil
        activeTokenServerProfile = nil
        pairURLString = nil
        status = .generating
        pin = ""
        errorMessage = nil
        isSubmitting = false
        self.serverProfile = serverProfile
        return attemptState.begin(serverProfile: serverProfile)
    }
}

struct WatchPairLoginView: View {
    @ObservedObject var authStore: WatchAuthStore
    @StateObject private var pairState = WatchPairLoginState()
    @StateObject private var phoneBridge = WatchPhoneLoginBridge()
    @State private var showFullScreenQRCode = false
    @State private var showSelfHostedInput = false
    @State private var selfHostedError: String?

    var body: some View {
        ZStack {
            Color.grey100.ignoresSafeArea()

            ScrollView {
                VStack(spacing: .spacing4) {
                    statusView

                    if pairState.status == .waiting,
                       phoneBridge.isPhoneReachable {
                        confirmOnIPhoneView
                    }

                    if pairState.pairURLString != nil {
                        manualFallbackView
                    }

                    selfHostedConnectionView

                    if pairState.status == .ready {
                        pinSection
                    }

                    if pairState.status == .expired || pairState.status == .failed {
                        Button {
                            startPairing(force: true)
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

            if showFullScreenQRCode, let pairURLString = pairState.pairURLString {
                WatchFullScreenQRCodeView(payload: pairURLString) {
                    showFullScreenQRCode = false
                }
                .transition(.opacity)
                .zIndex(2)
            }
        }
        .task {
            phoneBridge.start(onApproval: { approval in handlePhoneApproval(approval) })
            startPairingIfNeeded()
        }
        .onChange(of: phoneBridge.isPhoneReachable) { _, isReachable in
            if isReachable { sendPhoneLoginRequestIfPossible() }
        }
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

    private var confirmOnIPhoneView: some View {
        VStack(spacing: .spacing3) {
            Text(WatchStrings.pairConfirmOnIphone)
                .font(.omSmall)
                .fontWeight(.semibold)
                .foregroundStyle(Color.grey0)
                .multilineTextAlignment(.center)
                .accessibilityIdentifier("watch-pair-confirm-iphone-title")

            Text(WatchStrings.pairConfirmOnIphoneDescription)
                .font(.omXs)
                .foregroundStyle(Color.grey0.opacity(0.72))
                .multilineTextAlignment(.center)
                .accessibilityIdentifier("watch-pair-confirm-iphone-description")

        }
        .padding(.spacing3)
        .background(Color.grey80.opacity(0.55))
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
    }

    private var selfHostedConnectionView: some View {
        VStack(spacing: .spacing2) {
            if showSelfHostedInput {
                TextField(WatchStrings.pairSelfHostedPlaceholder, text: $pairState.customDomain)
                    .font(.omTiny)
                    .foregroundStyle(Color.fontPrimary)
                    .multilineTextAlignment(.center)
                    .padding(.vertical, .spacing2)
                    .padding(.horizontal, .spacing2)
                    .background(Color.grey0)
                    .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                    .accessibilityIdentifier("watch-pair-self-host-input")

                if let selfHostedError {
                    Text(selfHostedError)
                        .font(.omTiny)
                        .foregroundStyle(Color.error)
                        .multilineTextAlignment(.center)
                        .accessibilityIdentifier("watch-pair-self-host-error")
                }

                Button {
                    connectSelfHostedServer()
                } label: {
                    compactButtonLabel(WatchStrings.pairSelfHostedConnect)
                }
                .buttonStyle(.plain)
                .disabled(pairState.customDomain.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .accessibilityIdentifier("watch-pair-self-host-connect-button")

                Button {
                    showSelfHostedInput = false
                    selfHostedError = nil
                } label: {
                    Text(WatchStrings.cancel)
                        .font(.omTiny)
                        .foregroundStyle(Color.grey0.opacity(0.82))
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("watch-pair-self-host-cancel-button")
            } else {
                Button {
                    pairState.customDomain = pairState.serverProfile == .production
                        ? ""
                        : pairState.serverProfile.displayDomain
                    showSelfHostedInput = true
                    selfHostedError = nil
                } label: {
                    compactButtonLabel(WatchStrings.pairSelfHostedEdition)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("watch-pair-self-host-button")

                if pairState.serverProfile != .production {
                    Text(pairState.serverProfile.displayDomain)
                        .font(.omTiny)
                        .foregroundStyle(Color.grey0.opacity(0.72))
                        .multilineTextAlignment(.center)

                    Button {
                        WatchServerProfileStore().resetToProduction()
                        startPairing(serverProfile: .production, force: true)
                    } label: {
                        Text(WatchStrings.pairUseProduction)
                            .font(.omTiny)
                            .foregroundStyle(Color.grey0.opacity(0.82))
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("watch-pair-use-production-button")
                }
            }
        }
        .padding(.spacing2)
        .background(Color.grey80.opacity(0.35))
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
    }

    private func compactButtonLabel(_ title: String) -> some View {
        Text(title)
            .font(.omTiny)
            .fontWeight(.semibold)
            .foregroundStyle(Color.fontButton)
            .multilineTextAlignment(.center)
            .padding(.horizontal, .spacing3)
            .padding(.vertical, .spacing2)
            .background(LinearGradient.primary)
            .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
    }

    private var manualFallbackView: some View {
        VStack(spacing: .spacing3) {
            if let token = pairState.token {
                Text(token)
                    .font(.omH2.monospaced())
                    .fontWeight(.bold)
                    .foregroundStyle(Color.grey0)
                    .multilineTextAlignment(.center)
                    .accessibilityIdentifier("watch-pair-token")
            }

            if let pairURLString = pairState.pairURLString {
                VStack(spacing: .spacing1) {
                    Text(WatchStrings.pairFullURLLabel)
                        .font(.omXs)
                        .foregroundStyle(Color.grey0.opacity(0.72))
                    Text(pairURLString)
                        .font(.omTiny)
                        .foregroundStyle(Color.grey0.opacity(0.82))
                        .multilineTextAlignment(.center)
                        .lineLimit(3)
                        .accessibilityIdentifier("watch-pair-url")
                }
            }

            Button {
                showFullScreenQRCode = true
            } label: {
                Text(WatchStrings.pairShowQRCode)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontButton)
                    .padding(.horizontal, .spacing4)
                    .padding(.vertical, .spacing2)
                    .background(LinearGradient.primary)
                    .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("watch-pair-show-qr-button")
        }
        .padding(.spacing3)
        .background(Color.grey80.opacity(0.55))
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
        .accessibilityIdentifier("watch-pair-manual-fallback")
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

    private func startPairingIfNeeded() {
        NativeDiagnostics.info(
            "phase=view.initiateIfNeeded hasToken=\(pairState.token != nil) status=\(pairState.status)",
            category: watchPairLoginDiagnosticsCategory
        )
        if let token = pairState.token {
            if pairState.status == .waiting, pairState.pollTask == nil {
                startPolling(
                    token: token,
                    serverProfile: pairState.serverProfile,
                    generation: pairState.attemptState.generation
                )
            }
            return
        }
        guard pairState.initiationTask == nil else { return }
        startPairing(force: false)
    }

    private func startPairing(serverProfile: ServerProfile? = nil, force: Bool) {
        if !force, pairState.token != nil || pairState.initiationTask != nil { return }
        let serverProfile = serverProfile ?? pairState.serverProfile
        let generation = pairState.beginAttempt(serverProfile: serverProfile)
        NativeDiagnostics.info(
            "phase=view.initiate.start generation=\(generation) force=\(force) serverKind=\(serverProfile.diagnosticsKind)",
            category: watchPairLoginDiagnosticsCategory
        )

        pairState.initiationTask = Task {
            do {
                let initiation = try await PairLoginRuntime.initiate(serverProfile: serverProfile)
                guard !Task.isCancelled,
                      pairState.attemptState.accept(
                        initiation,
                        generation: generation,
                        serverProfile: serverProfile
                      ) else {
                    NativeDiagnostics.warning(
                        "phase=view.initiate.ignored reason=stale generation=\(generation) serverKind=\(serverProfile.diagnosticsKind)",
                        category: watchPairLoginDiagnosticsCategory
                    )
                    return
                }
                pairState.initiationTask = nil
                pairState.token = initiation.token
                pairState.activeTokenServerProfile = serverProfile
                pairState.pairURLString = initiation.pairURLString
                pairState.status = .waiting
                NativeDiagnostics.info(
                    "phase=view.initiate.success generation=\(generation) serverKind=\(serverProfile.diagnosticsKind)",
                    category: watchPairLoginDiagnosticsCategory
                )
                startPolling(token: initiation.token, serverProfile: serverProfile, generation: generation)
                sendPhoneLoginRequestIfPossible()
            } catch {
                guard !Task.isCancelled,
                      pairState.attemptState.accepts(
                        generation: generation,
                        serverProfile: serverProfile
                      ) else {
                    NativeDiagnostics.warning(
                        "phase=view.initiate.failureIgnored reason=stale generation=\(generation) serverKind=\(serverProfile.diagnosticsKind)",
                        category: watchPairLoginDiagnosticsCategory
                    )
                    return
                }
                pairState.initiationTask = nil
                NativeDiagnostics.error(
                    "phase=view.initiate.failed generation=\(generation) serverKind=\(serverProfile.diagnosticsKind) errorType=\(type(of: error))",
                    category: watchPairLoginDiagnosticsCategory
                )
                pairState.errorMessage = error.localizedDescription
                pairState.status = .failed
            }
        }
    }

    private func startPolling(token: String, serverProfile: ServerProfile, generation: Int) {
        pairState.pollTask?.cancel()
        NativeDiagnostics.info(
            "phase=view.poll.start generation=\(generation) serverKind=\(serverProfile.diagnosticsKind)",
            category: watchPairLoginDiagnosticsCategory
        )
        pairState.pollTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(3))
                if Task.isCancelled { return }

                do {
                    let response = try await PairLoginRuntime.poll(token: token, serverProfile: serverProfile)
                    guard !Task.isCancelled,
                          pairState.attemptState.accepts(generation: generation, serverProfile: serverProfile),
                          pairState.token == token else { return }
                    if response.status == "ready" {
                        pairState.status = .ready
                        NativeDiagnostics.info(
                            "phase=view.poll.ready generation=\(generation) serverKind=\(serverProfile.diagnosticsKind)",
                            category: watchPairLoginDiagnosticsCategory
                        )
                        if pairState.pin.count == 6 { submitPinIfReady() }
                    } else if response.status == "expired" {
                        pairState.status = .expired
                        NativeDiagnostics.warning(
                            "phase=view.poll.expired generation=\(generation) serverKind=\(serverProfile.diagnosticsKind)",
                            category: watchPairLoginDiagnosticsCategory
                        )
                    }
                    if response.status == "ready" || response.status == "expired" { return }
                } catch {
                    guard !Task.isCancelled,
                          pairState.attemptState.accepts(generation: generation, serverProfile: serverProfile),
                          pairState.token == token else { return }
                    NativeDiagnostics.error(
                        "phase=view.poll.failed generation=\(generation) serverKind=\(serverProfile.diagnosticsKind) errorType=\(type(of: error))",
                        category: watchPairLoginDiagnosticsCategory
                    )
                    pairState.errorMessage = error.localizedDescription
                    pairState.status = .failed
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

    private func sendPhoneLoginRequestIfPossible() {
        guard let token = pairState.token,
              let serverProfile = pairState.activeTokenServerProfile,
              serverProfile == pairState.serverProfile,
              let pairURLString = pairState.pairURLString else {
            NativeDiagnostics.debug(
                "phase=view.phoneRequest.skipped hasToken=\(pairState.token != nil) hasActiveProfile=\(pairState.activeTokenServerProfile != nil) hasPairURL=\(pairState.pairURLString != nil)",
                category: watchPairLoginDiagnosticsCategory
            )
            return
        }
        let request = WatchPairLoginRequest(
            token: token,
            pairURLString: pairURLString,
            deviceName: PairLoginRuntime.officialAppDeviceHint,
            serverProfile: serverProfile,
            createdAt: Int(Date().timeIntervalSince1970)
        )
        let sent = phoneBridge.sendLoginRequest(request)
        NativeDiagnostics.info(
            "phase=view.phoneRequest.sent sent=\(sent) serverKind=\(serverProfile.diagnosticsKind) reachable=\(phoneBridge.isPhoneReachable)",
            category: watchPairLoginDiagnosticsCategory
        )
    }

    private func handlePhoneApproval(_ approval: WatchPairLoginApproval) {
        guard approval.token == pairState.token else {
            NativeDiagnostics.warning(
                "phase=view.phoneApproval.ignored reason=tokenMismatch",
                category: watchPairLoginDiagnosticsCategory
            )
            return
        }
        NativeDiagnostics.info(
            "phase=view.phoneApproval.received status=\(pairState.status)",
            category: watchPairLoginDiagnosticsCategory
        )
        pairState.pin = approval.pin
        if pairState.status == .ready { submitPinIfReady() }
    }

    private func connectSelfHostedServer() {
        do {
            let profile = try ServerProfile.validatedSelfHostedURL(pairState.customDomain)
            selfHostedError = nil
            showSelfHostedInput = false
            startPairing(serverProfile: profile, force: true)
        } catch {
            selfHostedError = WatchStrings.pairSelfHostedInvalidURL
        }
    }

    private func submitPinIfReady() {
        guard pairState.status == .ready,
              !pairState.isSubmitting,
              pairState.pin.count == 6,
              let token = pairState.token,
              let serverProfile = pairState.activeTokenServerProfile,
              serverProfile == pairState.serverProfile else { return }
        pairState.isSubmitting = true
        pairState.errorMessage = nil

        Task {
            do {
                let result = try await PairLoginRuntime.complete(
                    token: token,
                    pin: pairState.pin,
                    stayLoggedIn: true,
                    serverProfile: serverProfile
                )
                guard pairState.token == token,
                      pairState.activeTokenServerProfile == serverProfile,
                      pairState.serverProfile == serverProfile else { return }
                try await authStore.completePairLogin(result)
            } catch PairLoginRuntimeError.completeFailed(let kind) {
                guard pairState.token == token,
                      pairState.activeTokenServerProfile == serverProfile,
                      pairState.serverProfile == serverProfile else { return }
                handlePairCompleteFailure(kind)
            } catch {
                guard pairState.token == token,
                      pairState.activeTokenServerProfile == serverProfile,
                      pairState.serverProfile == serverProfile else { return }
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

}

private struct WatchQRCodeView: View {
    let payload: String

    var body: some View {
        let matrix = WatchQRCodeMatrix(payload: payload)
        Canvas { context, size in
            let moduleSize = min(size.width, size.height) / CGFloat(matrix.size)
            for row in 0..<matrix.size {
                for column in 0..<matrix.size where matrix.isDark(row: row, column: column) {
                    let rect = CGRect(
                        x: CGFloat(column) * moduleSize,
                        y: CGFloat(row) * moduleSize,
                        width: moduleSize,
                        height: moduleSize
                    )
                    context.fill(Path(rect), with: .color(.black))
                }
            }
        }
        .background(Color.white)
    }
}

private struct WatchFullScreenQRCodeView: View {
    let payload: String
    let onClose: () -> Void

    var body: some View {
        GeometryReader { geometry in
            let side = max(120, min(geometry.size.width, geometry.size.height) - 18)
            ZStack {
                Color.grey100.ignoresSafeArea()

                VStack(spacing: .spacing3) {
                    WatchQRCodeView(payload: payload)
                        .frame(width: side, height: side)
                        .padding(.spacing3)
                        .background(Color.white)
                        .clipShape(RoundedRectangle(cornerRadius: .radius4))
                        .accessibilityLabel(WatchStrings.scanCode)
                        .accessibilityIdentifier("watch-pair-qr-code")

                    Button(WatchStrings.back) {
                        onClose()
                    }
                    .buttonStyle(.plain)
                    .font(.omSmall)
                    .foregroundStyle(Color.grey0)
                    .accessibilityIdentifier("watch-pair-qr-close-button")
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .accessibilityIdentifier("watch-pair-qr-fullscreen")
    }
}

private struct WatchQRCodeMatrix {
    let size = 33

    private var modules: [Bool]
    private var reserved: [Bool]

    init(payload: String) {
        modules = Array(repeating: false, count: size * size)
        reserved = Array(repeating: false, count: size * size)

        drawFunctionPatterns()
        let dataCodewords = Self.encodeData(payload)
        let errorCodewords = Self.reedSolomonRemainder(dataCodewords, degree: 20)
        drawCodewords(dataCodewords + errorCodewords)
        applyMask0()
        drawFormatBits()
    }

    func isDark(row: Int, column: Int) -> Bool {
        modules[index(row: row, column: column)]
    }

    private func index(row: Int, column: Int) -> Int {
        row * size + column
    }

    private mutating func set(row: Int, column: Int, dark: Bool, reserve: Bool = true) {
        guard row >= 0, row < size, column >= 0, column < size else { return }
        let position = index(row: row, column: column)
        modules[position] = dark
        if reserve { reserved[position] = true }
    }

    private mutating func drawFunctionPatterns() {
        drawFinder(row: 0, column: 0)
        drawFinder(row: 0, column: size - 7)
        drawFinder(row: size - 7, column: 0)
        drawTimingPatterns()
        drawAlignment(row: 26, column: 26)

        set(row: size - 8, column: 8, dark: true)
        reserveFormatAreas()
    }

    private mutating func drawFinder(row: Int, column: Int) {
        for y in -1...7 {
            for x in -1...7 {
                let isInside = x >= 0 && x <= 6 && y >= 0 && y <= 6
                let isBorder = x == 0 || x == 6 || y == 0 || y == 6
                let isCenter = x >= 2 && x <= 4 && y >= 2 && y <= 4
                set(row: row + y, column: column + x, dark: isInside && (isBorder || isCenter))
            }
        }
    }

    private mutating func drawTimingPatterns() {
        for i in 8..<(size - 8) {
            let dark = i.isMultiple(of: 2)
            set(row: 6, column: i, dark: dark)
            set(row: i, column: 6, dark: dark)
        }
    }

    private mutating func drawAlignment(row: Int, column: Int) {
        for y in -2...2 {
            for x in -2...2 {
                let distance = max(abs(x), abs(y))
                set(row: row + y, column: column + x, dark: distance != 1)
            }
        }
    }

    private mutating func reserveFormatAreas() {
        for i in 0..<9 {
            if i != 6 {
                set(row: 8, column: i, dark: false)
                set(row: i, column: 8, dark: false)
            }
        }
        for i in 0..<8 {
            set(row: 8, column: size - 1 - i, dark: false)
            set(row: size - 1 - i, column: 8, dark: false)
        }
    }

    private mutating func drawCodewords(_ codewords: [UInt8]) {
        var bits: [Bool] = []
        for codeword in codewords {
            for shift in stride(from: 7, through: 0, by: -1) {
                bits.append(((codeword >> UInt8(shift)) & 1) == 1)
            }
        }
        var bitIndex = 0
        var upward = true
        var column = size - 1

        while column > 0 {
            if column == 6 { column -= 1 }
            let rowRange = upward ? stride(from: size - 1, through: 0, by: -1) : stride(from: 0, through: size - 1, by: 1)
            for row in rowRange {
                for offset in 0...1 {
                    let currentColumn = column - offset
                    let position = index(row: row, column: currentColumn)
                    if reserved[position] { continue }
                    let dark = bitIndex < bits.count ? bits[bitIndex] : false
                    modules[position] = dark
                    bitIndex += 1
                }
            }
            upward.toggle()
            column -= 2
        }
    }

    private mutating func applyMask0() {
        for row in 0..<size {
            for column in 0..<size where !reserved[index(row: row, column: column)] {
                if (row + column).isMultiple(of: 2) {
                    modules[index(row: row, column: column)].toggle()
                }
            }
        }
    }

    private mutating func drawFormatBits() {
        let bits = Self.formatBits(errorCorrectionBits: 1, mask: 0)
        for i in 0..<15 {
            let dark = ((bits >> i) & 1) == 1
            let first = Self.formatBitCoordinateA(i)
            let second = Self.formatBitCoordinateB(i, size: size)
            set(row: first.row, column: first.column, dark: dark)
            set(row: second.row, column: second.column, dark: dark)
        }
    }

    private static func encodeData(_ payload: String) -> [UInt8] {
        var bits: [Bool] = []
        append(0b0100, bitCount: 4, to: &bits)
        let bytes = Array(payload.utf8.prefix(78))
        append(bytes.count, bitCount: 8, to: &bits)
        for byte in bytes {
            append(Int(byte), bitCount: 8, to: &bits)
        }
        append(0, bitCount: min(4, max(0, 640 - bits.count)), to: &bits)
        while !bits.count.isMultiple(of: 8) { bits.append(false) }

        var codewords = stride(from: 0, to: bits.count, by: 8).map { offset -> UInt8 in
            var value: UInt8 = 0
            for bit in 0..<8 where bits[offset + bit] {
                value |= 1 << UInt8(7 - bit)
            }
            return value
        }
        var pad: UInt8 = 0xEC
        while codewords.count < 80 {
            codewords.append(pad)
            pad = pad == 0xEC ? 0x11 : 0xEC
        }
        return Array(codewords.prefix(80))
    }

    private static func append(_ value: Int, bitCount: Int, to bits: inout [Bool]) {
        guard bitCount > 0 else { return }
        for shift in (0..<bitCount).reversed() {
            bits.append(((value >> shift) & 1) == 1)
        }
    }

    private static func reedSolomonRemainder(_ data: [UInt8], degree: Int) -> [UInt8] {
        let generator = reedSolomonGenerator(degree: degree)
        var result = Array(repeating: UInt8(0), count: degree)
        for byte in data {
            let factor = byte ^ result.removeFirst()
            result.append(0)
            for i in 0..<degree {
                result[i] ^= multiply(generator[i], factor)
            }
        }
        return result
    }

    private static func reedSolomonGenerator(degree: Int) -> [UInt8] {
        var result: [UInt8] = [1]
        for i in 0..<degree {
            result.append(0)
            let root = exp(i)
            for j in stride(from: result.count - 1, through: 1, by: -1) {
                result[j] = result[j - 1] ^ multiply(result[j], root)
            }
            result[0] = multiply(result[0], root)
        }
        return result
    }

    private static func multiply(_ x: UInt8, _ y: UInt8) -> UInt8 {
        if x == 0 || y == 0 { return 0 }
        return exp(log(x) + log(y))
    }

    private static func exp(_ power: Int) -> UInt8 {
        var value = 1
        for _ in 0..<(power % 255) {
            value <<= 1
            if value >= 0x100 { value ^= 0x11D }
        }
        return UInt8(value)
    }

    private static func log(_ value: UInt8) -> Int {
        var current: UInt8 = 1
        for i in 0..<255 {
            if current == value { return i }
            current = multiplyNoLog(current, 2)
        }
        return 0
    }

    private static func multiplyNoLog(_ x: UInt8, _ y: UInt8) -> UInt8 {
        var a = Int(x)
        var b = Int(y)
        var result = 0
        while b > 0 {
            if b & 1 != 0 { result ^= a }
            a <<= 1
            if a & 0x100 != 0 { a ^= 0x11D }
            b >>= 1
        }
        return UInt8(result & 0xFF)
    }

    private static func formatBits(errorCorrectionBits: Int, mask: Int) -> Int {
        let data = (errorCorrectionBits << 3) | mask
        var value = data << 10
        let generator = 0x537
        for shift in stride(from: 14, through: 10, by: -1) {
            if ((value >> shift) & 1) != 0 {
                value ^= generator << (shift - 10)
            }
        }
        return ((data << 10) | value) ^ 0x5412
    }

    private static func formatBitCoordinateA(_ index: Int) -> (row: Int, column: Int) {
        switch index {
        case 0...5: return (8, index)
        case 6: return (8, 7)
        case 7: return (8, 8)
        case 8: return (7, 8)
        default: return (14 - index, 8)
        }
    }

    private static func formatBitCoordinateB(_ index: Int, size: Int) -> (row: Int, column: Int) {
        if index < 8 {
            return (size - 1 - index, 8)
        }
        return (8, size - 15 + index)
    }
}
