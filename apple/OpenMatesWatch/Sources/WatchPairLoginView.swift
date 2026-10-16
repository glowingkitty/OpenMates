// Watch short-URL/PIN pair-login view.
// Presents the OpenMates PAKE Pair Login flow in a compact standalone
// watchOS layout: show a short URL, poll authorization state, then auto-submit a
// sanitized six-character PIN. Runtime logic lives in PairLoginRuntime.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/Login.svelte
//          frontend/packages/ui/src/components/settings/security/SettingsSessionsPairInitiate.svelte
// Backend: backend/core/api/routes/auth_pair.py
// CSS:     frontend/packages/ui/src/styles/auth.css, buttons.css, fields.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.pairing.iphone-first-fallback
// ────────────────────────────────────────────────────────────────────

import SwiftUI

private let watchPairLoginDiagnosticsCategory = "watch_pair_login"

enum WatchPairLoginFixtureState: Equatable {
    case initiating
    case iphoneConfirm
    case cloudShortURL
    case selfHostedShortURL
    case selfHostedDomainEntry
    case pairCodeEntry
    case initiationFailed
    case selfHostedInitiationFailed
    case completionFailed
}

@MainActor
final class WatchPairLoginState: ObservableObject {
    @Published var token: String?
    @Published var activeTokenServerProfile: ServerProfile?
    @Published var pairURLString: String?
    @Published var status: PairLoginStatus = .generating
    @Published var pin = ""
    var receiverExpiresAt: Int?
    var phonePINAccepted = false
    @Published var errorMessage: String?
    @Published var isSubmitting = false
    @Published var showsManualFallback = false
    @Published var manualFallbackSelected = false
    @Published var phoneRequestSent = false
    @Published var phoneApprovalStarted = false
    @Published var phoneApprovalEnded = false
    @Published var serverProfile = WatchServerProfileStore().currentProfile()
    @Published var customDomain = ""

    var attemptState = WatchPairAttemptState()
    var initiationTask: Task<Void, Never>?
    var pollTask: Task<Void, Never>?
    var fallbackTask: Task<Void, Never>?

    deinit {
        initiationTask?.cancel()
        pollTask?.cancel()
        fallbackTask?.cancel()
    }

    func failCompletion(_ error: Error) {
        NativeDiagnostics.error("phase=view.complete.failed errorType=\(type(of: error))",
                                category: watchPairLoginDiagnosticsCategory)
        errorMessage = WatchStrings.pairRestartRequired
        pin = ""
        phonePINAccepted = false
        status = .failed
        isSubmitting = false
    }

    @discardableResult
    func beginAttempt(serverProfile: ServerProfile) -> Int {
        initiationTask?.cancel()
        pollTask?.cancel()
        fallbackTask?.cancel()
        initiationTask = nil
        pollTask = nil
        fallbackTask = nil
        token = nil
        activeTokenServerProfile = nil
        pairURLString = nil
        status = .generating
        pin = ""
        receiverExpiresAt = nil
        phonePINAccepted = false
        errorMessage = nil
        isSubmitting = false
        showsManualFallback = false
        manualFallbackSelected = false
        phoneRequestSent = false
        phoneApprovalStarted = false
        phoneApprovalEnded = false
        self.serverProfile = serverProfile
        return attemptState.begin(serverProfile: serverProfile)
    }
}

struct WatchPairLoginView: View {
    @ObservedObject var authStore: WatchAuthStore
    @StateObject private var pairState: WatchPairLoginState
    @StateObject private var phoneBridge = WatchPhoneLoginBridge.shared
    @State private var showSelfHostedInput = false
    @State private var domainEditorVisible = false
    @State private var pinEditorVisible = false
    @State private var showsReadyShortURL = false
    @FocusState private var domainFieldFocused: Bool
    @FocusState private var pinFieldFocused: Bool
    @State private var selfHostedError: String?
    private let uiTestFixture: WatchPairLoginFixtureState?

    init(authStore: WatchAuthStore, uiTestFixture: WatchPairLoginFixtureState? = nil) {
        self.authStore = authStore
        self.uiTestFixture = uiTestFixture
        let state = WatchPairLoginState()
        if let uiTestFixture {
            // Synthetic Cloud routes must not inherit a previously selected
            // custom server from the simulator's persisted profile store.
            state.serverProfile = .production
            state.token = "WATCH42"
            switch uiTestFixture {
            case .initiating:
                state.token = nil
            case .iphoneConfirm:
                state.pairURLString = "https://openmates.org/#pair=WATCH42"
                state.status = .waiting
                state.phoneRequestSent = true
            case .cloudShortURL:
                state.pairURLString = "https://openmates.org/#pair=WATCH42"
                state.status = .waiting
                state.showsManualFallback = true
            case .selfHostedShortURL:
                state.serverProfile = .custom(domain: "mydomain.org")
                state.pairURLString = "https://mydomain.org/#pair=WATCH42"
                state.status = .waiting
                state.showsManualFallback = true
            case .selfHostedDomainEntry:
                state.pairURLString = "https://openmates.org/#pair=WATCH42"
                state.status = .waiting
            case .pairCodeEntry:
                state.pairURLString = "https://openmates.org/#pair=WATCH42"
                state.status = .ready
            case .completionFailed:
                state.activeTokenServerProfile = state.serverProfile
                state.pin = "ABC346"
                state.phonePINAccepted = true
                state.isSubmitting = true
                state.failCompletion(PairOpaqueError.invalidExchange)
            case .initiationFailed, .selfHostedInitiationFailed:
                state.token = nil
                state.pairURLString = nil
                state.status = .failed
                state.errorMessage = WatchStrings.loginFailed
                state.serverProfile = uiTestFixture == .selfHostedInitiationFailed ? .custom(domain: "mydomain.org") : .production
            }
        }
        _pairState = StateObject(wrappedValue: state)
        _showSelfHostedInput = State(initialValue: uiTestFixture == .selfHostedDomainEntry)
    }

    var body: some View {
        GeometryReader { geometry in
        ZStack {
            WatchWorkspacePalette.background.ignoresSafeArea()

            ScrollView {
                VStack(spacing: .spacing4) {
                    if showSelfHostedInput {
                        selfHostedConnectionView
                    } else if pairState.status == .ready {
                        if showsReadyShortURL {
                            manualFallbackView
                        } else {
                            pinSection
                        }
                    } else {
                        statusView
                        if pairState.status == .waiting,
                           pairState.phoneRequestSent,
                           !pairState.showsManualFallback {
                            confirmOnIPhoneView
                        }
                        if pairState.status == .waiting,
                           pairState.showsManualFallback,
                           pairState.pairURLString != nil {
                            manualFallbackView
                        }
                    }

                    if (pairState.status == .expired || pairState.status == .failed), !showSelfHostedInput {
                        // Server recovery must remain reachable when initiation
                        // fails before the server provides a token or short URL.
                        serverSelectionView
                        Button {
                            if uiTestFixture == .completionFailed {
                                // Exercise the production attempt reset without
                                // making a server request in a synthetic UI run.
                                _ = pairState.beginAttempt(serverProfile: pairState.serverProfile)
                            } else {
                                startPairing(force: true)
                            }
                        } label: {
                            Text(WatchStrings.pairRefresh)
                                .font(.omSmall)
                                .fontWeight(.semibold)
                                .foregroundStyle(WatchWorkspacePalette.foreground)
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
                .padding(.top, .spacing4)
                .padding(.bottom, .spacing8)
            }
            .ignoresSafeArea(edges: .top)
        }
        .frame(width: geometry.size.width, height: geometry.size.height)
        .overlay(alignment: .bottom) {
            if showSelfHostedInput && !domainEditorVisible {
                keyboardEntryButton(identifier: "watch-pair-self-host-keyboard") {
                    domainEditorVisible = true
                    domainFieldFocused = true
                }
                .offset(y: geometry.safeAreaInsets.bottom - .spacing2)
            } else if pairState.status == .ready && !showsReadyShortURL && !pinEditorVisible && pairState.pin.isEmpty {
                keyboardEntryButton(identifier: "watch-pair-pin-keyboard") {
                    pinEditorVisible = true
                    pinFieldFocused = true
                }
                .offset(y: geometry.safeAreaInsets.bottom - .spacing2)
            }
        }
        }
        .task {
            guard uiTestFixture == nil else { return }
            phoneBridge.start(
                onApproval: { approval in handlePhoneApproval(approval) },
                onAcknowledgment: { acknowledgment in handlePhoneAcknowledgment(acknowledgment) }
            )
            startPairingIfNeeded()
        }
        .onChange(of: phoneBridge.isPhoneReachable) { _, isReachable in
            if isReachable { sendPhoneLoginRequestIfPossible() }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("watch-pair-login")
    }

    @ViewBuilder
    private var statusView: some View {
        switch pairState.status {
        case .generating:
            VStack(spacing: .spacing2) {
                ProgressView()
                    .controlSize(.small)
                    .tint(WatchWorkspacePalette.foreground)
                Text(WatchStrings.pairGenerating)
                    .font(.omXs)
                    .foregroundStyle(WatchWorkspacePalette.foreground.opacity(0.82))
                    .multilineTextAlignment(.center)
                    .accessibilityIdentifier("watch-pair-generating-label")
            }
        case .waiting:
            if !pairState.showsManualFallback, !pairState.phoneRequestSent {
                Text(WatchStrings.pairWaiting)
                    .font(.omXs)
                    .foregroundStyle(WatchWorkspacePalette.foreground.opacity(0.82))
                    .multilineTextAlignment(.center)
                    .accessibilityIdentifier("watch-pair-waiting-label")
            }
        case .ready:
            EmptyView()
        case .expired:
            messageBox(text: WatchStrings.pairExpired)
        case .failed:
            messageBox(text: pairState.errorMessage ?? WatchStrings.loginFailed)
        }
    }

    private var pinSection: some View {
        VStack(spacing: .spacing4) {
            pairHeader(WatchStrings.pairShortURLLabel) {
                showsReadyShortURL = true
            }

            Text(WatchStrings.pairEnterCodePrompt)
                .font(.omSmall)
                .fontWeight(.bold)
                .foregroundStyle(WatchWorkspacePalette.foreground)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 145)
                .padding(.top, CGFloat.spacing12 + CGFloat.spacing3)
                .accessibilityIdentifier("watch-pair-code-prompt")

            if pinEditorVisible || !pairState.pin.isEmpty {
                TextField(WatchStrings.pairPinPlaceholder, text: $pairState.pin)
                    .font(.omP)
                    .fontWeight(.bold)
                    .foregroundStyle(WatchWorkspacePalette.foreground)
                    .multilineTextAlignment(.center)
                    .padding(.vertical, .spacing2)
                    .padding(.horizontal, .spacing3)
                    .background(WatchWorkspacePalette.surface)
                    .clipShape(RoundedRectangle(cornerRadius: .radius4))
                    .focused($pinFieldFocused)
                    .onAppear { pinFieldFocused = true }
                    .onChange(of: pairState.pin) { _, newValue in sanitizeAndSubmitPin(newValue) }
                    .disabled(pairState.isSubmitting)
                    .accessibilityIdentifier("watch-pair-pin-input")
            }

            if pairState.isSubmitting {
                Text(WatchStrings.pairLoggingIn)
                    .font(.omXs)
                    .foregroundStyle(WatchWorkspacePalette.foreground.opacity(0.72))
                    .multilineTextAlignment(.center)
            } else if let errorMessage = pairState.errorMessage {
                messageBox(text: errorMessage)
            }
        }
        .frame(maxWidth: .infinity)
    }

    private var confirmOnIPhoneView: some View {
        VStack(spacing: .spacing8) {
            Image("WatchPairLoginIcon")
                .resizable()
                .renderingMode(.original)
                .frame(width: 76, height: 76)
                .accessibilityHidden(true)

            Text(WatchStrings.pairConfirmOnIphone)
                .font(.omSmall)
                .fontWeight(.bold)
                .foregroundStyle(WatchWorkspacePalette.foreground)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 140)
                .accessibilityIdentifier("watch-pair-confirm-iphone-title")

            Button {
                pairState.fallbackTask?.cancel()
                pairState.manualFallbackSelected = true
                pairState.showsManualFallback = true
            } label: {
                Text(WatchStrings.pairTapShortURL)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(WatchWorkspacePalette.foreground.opacity(0.82))
                    .multilineTextAlignment(.center)
            }
            .buttonStyle(.plain)
            .padding(.top, .spacing3)
            .accessibilityIdentifier("watch-pair-login-without-iphone-button")

        }
        .frame(maxWidth: .infinity)
        .padding(.top, .spacing10)
    }

    private var selfHostedConnectionView: some View {
        VStack(spacing: .spacing4) {
            pairHeader(WatchStrings.pairCloudLabel) {
                showSelfHostedInput = false
                domainEditorVisible = false
                selfHostedError = nil
            }

            Text(WatchStrings.pairSelfHostedDomainPrompt)
                .font(.omSmall)
                .fontWeight(.bold)
                .foregroundStyle(WatchWorkspacePalette.foreground)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 150)
                .padding(.top, CGFloat.spacing12 + CGFloat.spacing3)
                .accessibilityIdentifier("watch-pair-self-host-prompt")

            if domainEditorVisible {
                TextField(WatchStrings.pairSelfHostedPlaceholder, text: $pairState.customDomain)
                    .font(.omSmall)
                    .foregroundStyle(WatchWorkspacePalette.foreground)
                    .multilineTextAlignment(.center)
                    .padding(.vertical, .spacing2)
                    .padding(.horizontal, .spacing2)
                    .background(WatchWorkspacePalette.surface)
                    .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                    .focused($domainFieldFocused)
                    .onAppear { domainFieldFocused = true }
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
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func compactButtonLabel(_ title: String) -> some View {
        Text(title)
            .font(.omTiny)
            .fontWeight(.semibold)
            .foregroundStyle(WatchWorkspacePalette.foreground)
            .multilineTextAlignment(.center)
            .padding(.horizontal, .spacing3)
            .padding(.vertical, .spacing2)
            .background(LinearGradient.primary)
            .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
    }

    private var manualFallbackView: some View {
        VStack(spacing: .spacing4) {
            pairHeader(WatchStrings.pairIphoneLabel) {
                if pairState.status == .ready {
                    showsReadyShortURL = false
                } else {
                    pairState.showsManualFallback = false
                    pairState.manualFallbackSelected = false
                    if !pairState.phoneRequestSent,
                       let token = pairState.token,
                       let activeProfile = pairState.activeTokenServerProfile {
                        startFallbackTimer(
                            token: token,
                            serverProfile: activeProfile,
                            generation: pairState.attemptState.generation
                        )
                    }
                }
            }

            if let pairURLString = pairState.pairURLString {
                VStack(spacing: .spacing12) {
                    Text(WatchStrings.pairLoginViaShortURL)
                        .font(.omSmall)
                        .fontWeight(.bold)
                        .foregroundStyle(WatchWorkspacePalette.foreground)

                    (Text(shortPairURLParts(pairURLString).domainAndPath + "\n")
                        .foregroundColor(WatchWorkspacePalette.foreground)
                     + Text(shortPairURLParts(pairURLString).pairCode)
                        .foregroundColor(Color(hex: 0x5A85EB)))
                        .font(.omH3)
                        .fontWeight(.bold)
                        .multilineTextAlignment(.center)
                        .lineLimit(3)
                        .minimumScaleFactor(0.85)
                        .accessibilityIdentifier("watch-pair-url")
                }
                .padding(.top, .spacing4)
            }

            serverSelectionView
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("watch-pair-manual-fallback")
    }

    private func shortPairURLParts(_ urlString: String) -> (domainAndPath: String, pairCode: String) {
        let shortened = urlString.replacingOccurrences(of: "^https?://", with: "", options: .regularExpression)
        guard let fragmentIndex = shortened.range(of: "#pair=", options: .caseInsensitive) else {
            return (shortened, "")
        }
        return (String(shortened[..<fragmentIndex.lowerBound]), String(shortened[fragmentIndex.lowerBound...]))
    }

    private func pairHeader(_ title: String, action: @escaping () -> Void) -> some View {
        HStack {
            Button(action: action) {
                HStack(spacing: .spacing1) {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(WatchWorkspacePalette.background)
                        .frame(width: 20, height: 20)
                        .background(Color(hex: 0x7096EF), in: Circle())
                    Text(title)
                        .font(.system(size: 17, weight: .medium))
                        .foregroundStyle(Color(hex: 0x7096EF))
                }
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("watch-pair-back-button")
            Spacer(minLength: 0)
        }
    }

    private func keyboardEntryButton(identifier: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: "keyboard.fill")
                .font(.system(size: 39))
                .foregroundStyle(Color(hex: 0x5A85EB))
                .frame(maxWidth: .infinity)
                .frame(height: 74)
                .background(WatchWorkspacePalette.surface)
                .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(identifier)
    }

    private func messageBox(text: String) -> some View {
        Text(text)
            .font(.omXs)
            .foregroundStyle(WatchWorkspacePalette.foreground)
            .multilineTextAlignment(.center)
            .padding(.spacing2)
            .frame(maxWidth: .infinity)
            .accessibilityIdentifier("watch-pair-error-message")
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

    @ViewBuilder
    private var serverSelectionView: some View {
        if pairState.serverProfile == .production {
            Button {
                pairState.customDomain = ""
                domainEditorVisible = false
                showSelfHostedInput = true
                selfHostedError = nil
            } label: {
                Text(WatchStrings.pairSelfHostedEdition)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(WatchWorkspacePalette.foreground.opacity(0.72))
                    .multilineTextAlignment(.center)
            }
            .buttonStyle(.plain)
            .padding(.top, .spacing5)
            .accessibilityIdentifier("watch-pair-self-host-button")
        } else {
            Button {
                if uiTestFixture != nil {
                    pairState.serverProfile = .production
                    pairState.token = nil
                    pairState.pairURLString = nil
                    pairState.status = .failed
                } else {
                    WatchServerProfileStore().resetToProduction()
                    startPairing(serverProfile: .production, force: true)
                }
            } label: {
                Text(WatchStrings.pairOfficialCloudEdition)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(WatchWorkspacePalette.foreground.opacity(0.72))
                    .multilineTextAlignment(.center)
            }
            .buttonStyle(.plain)
            .padding(.top, .spacing5)
            .accessibilityIdentifier("watch-pair-use-production-button")
        }
    }

    private func startPairing(serverProfile: ServerProfile? = nil, force: Bool) {
        if !force, pairState.token != nil || pairState.initiationTask != nil { return }
        if let oldToken = pairState.token, let oldProfile = pairState.activeTokenServerProfile {
            Task { await PairV2Runtime.cancel(token: oldToken, serverProfile: oldProfile) }
        }
        let serverProfile = serverProfile ?? pairState.serverProfile
        phoneBridge.clearPairingReceipts()
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
                    await PairV2Runtime.cancel(token: initiation.token, serverProfile: serverProfile)
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
                startFallbackTimer(token: initiation.token, serverProfile: serverProfile, generation: generation)
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
                    pairState.receiverExpiresAt = response.expiresAt
                    if pairState.phonePINAccepted {
                        phoneBridge.rememberAcceptedApproval(
                            WatchPairLoginApproval(token: token, pin: pairState.pin),
                            profile: serverProfile, expiresAt: response.expiresAt)
                    }
                    if response.status == "approved" {
                        pairState.fallbackTask?.cancel()
                        pairState.showsManualFallback = false
                        pairState.status = .ready
                        NativeDiagnostics.info(
                            "phase=view.poll.ready generation=\(generation) serverKind=\(serverProfile.diagnosticsKind)",
                            category: watchPairLoginDiagnosticsCategory
                        )
                        if pairState.pin.count == 6 { submitPinIfReady() }
                    } else if ["failed", "cancelled"].contains(response.status) {
                        phoneBridge.clearPairingReceipts()
                        pairState.pin = ""
                        pairState.phonePINAccepted = false
                        pairState.fallbackTask?.cancel()
                        pairState.status = .expired
                        NativeDiagnostics.warning(
                            "phase=view.poll.expired generation=\(generation) serverKind=\(serverProfile.diagnosticsKind)",
                            category: watchPairLoginDiagnosticsCategory
                        )
                    }
                    if response.status == "approved" || response.status == "failed" || response.status == "cancelled" { return }
                } catch {
                    guard !Task.isCancelled,
                          pairState.attemptState.accepts(generation: generation, serverProfile: serverProfile),
                          pairState.token == token else { return }
                    NativeDiagnostics.error(
                        "phase=view.poll.failed generation=\(generation) serverKind=\(serverProfile.diagnosticsKind) errorType=\(type(of: error))",
                        category: watchPairLoginDiagnosticsCategory
                    )
                    phoneBridge.clearPairingReceipts()
                    pairState.pin = ""
                    pairState.phonePINAccepted = false
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
              pairState.status == .waiting,
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
        if sent { pairState.phoneRequestSent = true }
        NativeDiagnostics.info(
            "phase=view.phoneRequest.sent sent=\(sent) serverKind=\(serverProfile.diagnosticsKind) reachable=\(phoneBridge.isPhoneReachable)",
            category: watchPairLoginDiagnosticsCategory
        )
    }

    private func startFallbackTimer(token: String, serverProfile: ServerProfile, generation: Int) {
        pairState.fallbackTask?.cancel()
        pairState.fallbackTask = Task {
            try? await Task.sleep(for: .seconds(4))
            guard !Task.isCancelled,
                  pairState.attemptState.accepts(generation: generation, serverProfile: serverProfile),
                  pairState.token == token,
                  pairState.status == .waiting,
                  !pairState.phoneApprovalStarted else { return }
            pairState.showsManualFallback = true
            pairState.fallbackTask = nil
        }
    }

    private func handlePhoneAcknowledgment(_ acknowledgment: WatchPairLoginAcknowledgment) {
        guard acknowledgment.token == pairState.token,
              pairState.status == .waiting else { return }
        switch acknowledgment.kind {
        case .offered:
            pairState.phoneRequestSent = true
        case .approvalStarted:
            guard !pairState.phoneApprovalEnded else { return }
            pairState.phoneApprovalStarted = true
            pairState.fallbackTask?.cancel()
            pairState.fallbackTask = nil
            if !pairState.manualFallbackSelected {
                pairState.showsManualFallback = false
            }
        case .denied, .approvalFailed:
            pairState.phoneApprovalEnded = true
            pairState.phoneApprovalStarted = false
            pairState.fallbackTask?.cancel()
            pairState.fallbackTask = nil
            pairState.showsManualFallback = true
        }
    }

    private func handlePhoneApproval(_ approval: WatchPairLoginApproval) -> Bool {
        guard pairState.activeTokenServerProfile == pairState.serverProfile,
              WatchPairLoginConnectivityPayload.canReceiveApproval(
                approval, token: pairState.token, status: pairState.status) else {
            NativeDiagnostics.warning(
                "phase=view.phoneApproval.ignored reason=tokenMismatch",
                category: watchPairLoginDiagnosticsCategory
            )
            return false
        }
        let now = Int(Date().timeIntervalSince1970)
        if let expiresAt = pairState.receiverExpiresAt, expiresAt <= now { return false }
        if pairState.phonePINAccepted && pairState.pin != approval.pin { return false }
        NativeDiagnostics.info(
            "phase=view.phoneApproval.received status=\(pairState.status)",
            category: watchPairLoginDiagnosticsCategory
        )
        pairState.fallbackTask?.cancel()
        pairState.fallbackTask = nil
        pairState.pin = approval.pin
        pairState.phonePINAccepted = true
        // Before the first receiver poll, buffer the PIN without acknowledging
        // receipt. The next poll supplies the actual attempt expiry for replay.
        guard let expiresAt = pairState.receiverExpiresAt else { return false }
        let accepted = phoneBridge.rememberAcceptedApproval(approval,
            profile: pairState.serverProfile, expiresAt: expiresAt)
        if pairState.status == .ready { submitPinIfReady() }
        return accepted
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
                try await authStore.completePairLogin(result) {
                    try await PairLoginRuntime.acknowledge(token: token, serverProfile: serverProfile)
                }
                pairState.pin = ""
            } catch PairLoginRuntimeError.completeFailed(let kind) {
                guard pairState.token == token,
                      pairState.activeTokenServerProfile == serverProfile,
                      pairState.serverProfile == serverProfile else { return }
                phoneBridge.clearPairingReceipts()
                handlePairCompleteFailure(kind)
            } catch {
                guard pairState.token == token,
                      pairState.activeTokenServerProfile == serverProfile,
                      pairState.serverProfile == serverProfile else { return }
                phoneBridge.clearPairingReceipts()
                pairState.failCompletion(error)
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
