// OpenMates Watch root view.
// Owns the top-level auth routing for the standalone watchOS client. Pair login
// is implemented natively on Watch and authenticated users enter the Watch chat
// shell backed by direct backend refresh plus local offline cache.
// The view deliberately avoids stock navigation/list chrome.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/Header.svelte
// CSS:     frontend/packages/ui/src/styles/header.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.registration.lifecycle, apple-notifications.action.routing-coherent,
//             apple-notifications.delivery.idempotent-visible
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.tasks.edit-private, apple-watch.workflows.compact-editor,
//             apple-watch.pairing.iphone-first-fallback, apple-watch.hub.compact-navigation,
//             apple-watch.guest.compact-workspace, apple-watch.guest.account-isolation,
//             apple-watch.pairing.explicit-entry-back, apple-watch.chats.input-actions,
//             apple-watch.chats.local-transcription
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.skill-integration, video-call.chat.fixed-binding, video-call.privacy

import SwiftUI

struct WatchRootView: View {
    @StateObject private var authStore = WatchAuthStore()
    @StateObject private var phoneBridge = WatchPhoneLoginBridge.shared
    @StateObject private var push = WatchPushNotificationManager.shared
    @Environment(\.scenePhase) private var scenePhase
    @State private var chatRuntime: WatchChatRuntime?
    @State private var callFactory: NativeVoiceCallWatchFactory?
    @StateObject private var callConsent = WatchVoiceCallConsent()
    @StateObject private var callTools = WatchVoiceCallToolCoordinator()
    @StateObject private var callMemory = WatchVoiceCallMemoryPermission()
    @State private var showsHardwareProbe = false
    @State private var runtimeRevision = UUID()
    @State private var runtimeAccountID: String?
    @State private var runtimeToken: String?
    @State private var runtimeAccountGeneration: UInt64?
    @State private var runtimeServerScope: String?
    @State private var backgroundSyncOwner: String?

    var body: some View {
        ZStack {
            WatchWorkspacePalette.background
                .ignoresSafeArea()

            switch authStore.state {
            case .initializing:
                loadingView
            case .unauthenticated:
                WatchGuestEntryView(authStore: authStore, publicProfile: ServerProfile.current(), onSettings: {
                    phoneBridge.sendPublicSettingsOpenRequest()
                })
            case .authenticated:
                if let chatRuntime {
                    authenticatedWorkspace(chatRuntime)
                } else {
                    loadingView
                }
            }
        }
        .overlay {
            if callConsent.isPresented { WatchVoiceCallConsentView(consent: callConsent) }
            WatchVoiceCallToolStatusView(coordinator: callTools)
            WatchVoiceCallMemoryPermissionView(permission: callMemory)
        }
        .onDisappear { releaseWorkspace() }
        .task {
            push.attach(authStore)
            push.isActive = scenePhase == .active
            await authStore.checkSession()
            configureChatRuntime()
            await push.refresh()
        }
        .onChange(of: authStore.state) { _, state in
            if state == .authenticated { phoneBridge.startAuthenticatedTransport() }
            else { phoneBridge.clearPairingReceipts() }
            configureChatRuntime()
        }
        .onChange(of: authStore.currentUser?.id) { old, current in
            if old != nil && old != current { phoneBridge.clearPairingReceipts() }
            configureChatRuntime()
        }
        .onChange(of: authStore.webSocketToken) { _, _ in configureChatRuntime() }
        .onChange(of: scenePhase) { _, phase in
            push.isActive = phase == .active
            if let chatRuntime {
                Task {
                    guard scenePhase == phase, self.chatRuntime === chatRuntime else { return }
                    await chatRuntime.setForeground(phase == .active)
                }
            }
            if phase == .active {
                Task {
                    await authStore.checkSession()
                    await push.refresh()
                }
            }
        }
        .onReceive(Timer.publish(every: 25, on: .main, in: .common).autoconnect()) { _ in
            guard scenePhase == .active else { return }
            configureChatRuntime()
            guard let chatRuntime else { return }
            Task {
                guard scenePhase == .active, self.chatRuntime === chatRuntime else { return }
                await chatRuntime.foregroundHeartbeat()
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("watch-root")
    }


    @ViewBuilder
    private func authenticatedWorkspace(_ chatRuntime: WatchChatRuntime) -> some View {
        if showsHardwareProbe, authStore.state == .authenticated, ServerProfile.current() == .development {
            WatchVoiceHardwareProbeView(auth: authStore, runtime: chatRuntime, consent: callConsent, close: { showsHardwareProbe = false })
        } else {
            hubWorkspace(chatRuntime)
        }

    }
    private func hubWorkspace(_ chatRuntime: WatchChatRuntime) -> some View {
        WatchHubView(
            chatRuntime: chatRuntime,
            currentUserId: authStore.currentUser?.id,
            currentUsername: authStore.currentUser?.username,
            currentAccountID: {
                guard authStore.state == .authenticated else { return nil }
                return authStore.currentUser?.id
            },
            writesAllowed: { authStore.state == .authenticated && authStore.isVerifiedOnline },
            notificationRoute: push.pendingRoute.flatMap { push.permitsOpen($0) ? $0 : nil },
            onNavigationBusyChange: { busy in
                chatRuntime.setForegroundNavigationBusy(busy)
            },
            onOpenItem: { request in
                _ = phoneBridge.sendItemOpenRequest(request)
            },
            onOpenSettings: {
                _ = phoneBridge.sendSettingsOpenRequest()
            },
            onHardwareProbe: authStore.state == .authenticated && ServerProfile.current() == .development
                ? { showsHardwareProbe = true } : nil,
            onCreate: { section in
                switch section {
                case .tasks: _ = phoneBridge.sendCollectionOpenRequest(kind: .task)
                case .workflows: _ = phoneBridge.sendCollectionOpenRequest(kind: .workflow)
                case .chat: break
                }
            }
        )
        .environment(\.watchEmbedAccountID, authStore.currentUser?.id)
        .id("\(authStore.currentUser?.id ?? ""):\(WatchChatAccountLifecycle.generation):\(ServerProfile.current().apiBaseURL.absoluteString):\(runtimeRevision)")
        .task { phoneBridge.startAuthenticatedTransport() }
    }
    private func installCallFactory(for runtime: WatchChatRuntime) {
        // Source-bound physical route evidence is still pending. Neither a
        // launch argument nor a Simulator probe may change this admission gate.
        let factory = NativeVoiceCallWatchFactory(auth: authStore, runtime: runtime,
            physicalRouteVerified: false, consent: { [weak callConsent] in
                await callConsent?.request() ?? false
            }, event: { [weak callTools] event in await callTools?.receive(event) })
        factory.bindTools(to: callTools, memory: callMemory)
        factory.install()
        callFactory = factory
    }
    private func releaseCallFactory() {
        callTools.invalidateOwner(); callMemory.invalidate()
        callConsent.cancel()
        let departed = callFactory
        callFactory = nil
        Task { await departed?.stop() }
    }

    private func releaseWorkspace() {
        if let backgroundSyncOwner { WatchBackgroundOfflineSync.shared.unregister(.chats, owner: backgroundSyncOwner) }
        backgroundSyncOwner = nil
        releaseCallFactory()
        chatRuntime?.stopRealtimeSync()
        chatRuntime = nil
        runtimeAccountID = nil
        runtimeToken = nil
        runtimeAccountGeneration = nil
        runtimeServerScope = nil
    }

    private func configureChatRuntime() {
        guard authStore.state == .authenticated, let accountID = authStore.currentUser?.id else {
            releaseWorkspace()
            return
        }
        let generation = WatchChatAccountLifecycle.generation
        let scope = WatchChatRuntime.currentServerScope
        let token = authStore.webSocketToken
        if let chatRuntime, runtimeAccountID == accountID,
           runtimeAccountGeneration == generation, runtimeServerScope == scope {
            if callFactory == nil { installCallFactory(for: chatRuntime) }
            if runtimeToken != token {
                chatRuntime.updateWebSocketToken(token)
                runtimeToken = token
            }
            return
        }
        if let backgroundSyncOwner { WatchBackgroundOfflineSync.shared.unregister(.chats, owner: backgroundSyncOwner) }
        releaseCallFactory()
        chatRuntime?.stopRealtimeSync()
        let runtime = WatchChatRuntime(currentUserId: accountID,
            syncSession: WatchSyncSession(sessionId: WatchCompatibleSession.nativeSessionId, token: token),
            recordingTranscriber: WhistleRecordingDraftTranscriber())
        installCallFactory(for: runtime)
        chatRuntime = runtime
        runtimeRevision = UUID()
        runtimeAccountID = accountID
        runtimeToken = token
        runtimeAccountGeneration = generation
        runtimeServerScope = scope
        let owner = "\(accountID):\(scope):\(generation)"
        backgroundSyncOwner = owner
        WatchBackgroundOfflineSync.shared.register(.chats, owner: owner) { [weak runtime] in
            await runtime?.performBackgroundOfflineSync()
        }
        Task {
            await runtime.loadCachedSnapshot()
            guard self.chatRuntime === runtime, !runtime.isStopped else { return }
            await runtime.setForeground(scenePhase == .active)
            await runtime.startRealtimeSync()
        }
    }

    private var loadingView: some View {
        VStack(spacing: .spacing3) {
            Circle()
                .fill(Color.buttonPrimary)
                .frame(width: .iconSizeXl, height: .iconSizeXl)
                .overlay {
                    Circle()
                        .stroke(WatchWorkspacePalette.foreground.opacity(0.82), lineWidth: 2)
                        .padding(.spacing2)
                }
                .accessibilityHidden(true)

            ProgressView()
                .controlSize(.small)
                .tint(WatchWorkspacePalette.foreground)
                .accessibilityIdentifier("watch-root-loading-indicator")
        }
    }
}

#Preview {
    WatchRootView()
}

// Compact rendering of actual integration state from voiceCallTools.ts. The
// Watch uses the same localized terminal-error and processing copy as web.
struct WatchVoiceCallToolStatusView: View {
    @ObservedObject var coordinator: WatchVoiceCallToolCoordinator
    var body: some View {
        if let error = coordinator.integrationError {
            VStack(spacing: .spacing3) {
                Text(WatchLocalization.text(error == .invalidResponse ? "voicecall.invalid_response" : "voicecall.call_unavailable"))
                    .font(.omSmall)
                Button { coordinator.dismissError() } label: {
                    Text(WatchLocalization.text("voicecall.close")).font(.omSmall.weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: .spacing8)
                        .background(LinearGradient.primary, in: Capsule())
                }.buttonStyle(.plain).accessibilityIdentifier("watch-voice-tool-error-close")
            }.padding(.spacing3)
                .foregroundStyle(WatchWorkspacePalette.foreground)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(WatchWorkspacePalette.background.ignoresSafeArea())
                .accessibilityIdentifier("watch-voice-tool-error")
        } else if coordinator.toolWorking {
            VStack {
                Text(WatchLocalization.text("voicecall.working")).font(.omXs)
                    .padding(.spacing2).background(WatchWorkspacePalette.background, in: Capsule())
                    .accessibilityIdentifier("watch-voice-tool-working")
                Spacer()
            }.allowsHitTesting(false)
        }
    }
}
