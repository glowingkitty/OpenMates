// Main app shell after authentication.
// Uses NavigationSplitView for adaptive layout across iPhone, iPad, and Mac.
// Sidebar shows chat list; detail shows active chat or empty state.
// Manages WebSocket connection and phased sync lifecycle.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/apps/web_app/src/routes/+page.svelte  (top-level layout)
//          frontend/packages/ui/src/components/ChatHistory.svelte (sidebar)
//          frontend/packages/ui/src/components/Header.svelte (top nav)
// Default: Opens demo-for-everyone chat on cold-boot for unauthenticated users,
//          matching +page.svelte logic (activeChatStore.setActiveChat('demo-for-everyone'))
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import WidgetKit
import CoreSpotlight
import LucideIcons
import CryptoKit
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct MainAppView: View {
    let launchCommand: AppWindowLaunchCommand?

    private enum ShellSwipeTarget {
        case openChats
        case closeChats
        case openSettings
        case closeSettings
    }

    @EnvironmentObject var authManager: AuthManager
    @EnvironmentObject var themeManager: ThemeManager
    @EnvironmentObject var pushManager: PushNotificationManager
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var appSession = AppSessionCoordinator.shared
    @StateObject private var chatStore = AppSessionCoordinator.shared.chatStore
    @StateObject private var wsManager = AppSessionCoordinator.shared.webSocketManager
    @StateObject private var deepLinkHandler = DeepLinkHandler()
    @StateObject private var incognitoManager = IncognitoManager()
    @StateObject private var handoffManager = HandoffManager()
    @StateObject private var authFlowState = AuthFlowState()
    @State private var syncBridge: OfflineSyncBridge?
    @State private var selectedChatId: String?
    @State private var isChatsPanelOpen = false
    @State private var showSettings = false
    @State private var showNewChat = false
    @State private var showExplore = false
    @State private var showSearch = false
    @State private var showShareChat = false
    @State private var showHiddenChats = false
    @State private var hiddenChatsUnlocked = false
    @State private var showPairAuthorize = false
    @State private var pairToken: String?
    @State private var searchText = ""
    @State private var dailyInspirations: [DailyInspirationBanner.DailyInspiration] = []
    @State private var syncedNewChatSuggestions: [NewChatSuggestionsView.ChatSuggestion] = []
    @State private var totalChatCount = 0
    @State private var isLoadingMore = false
    @State private var showRenameAlert = false
    @State private var renameChatId: String?
    @State private var renameChatTitle = ""
    @State private var showAuthSheet = false
    @State private var actionChat: Chat?
    @State private var didBootstrapAuthenticatedSession = false
    @State private var didApplyLaunchCommand = false
    @State private var shellSwipeTarget: ShellSwipeTarget?
    @State private var shellDragOffset: CGFloat = 0
    @State private var visibleUserChatLimit = Self.initialUserChatLimit
    @State private var syncProcessingTask: Task<Void, Never>?
    @State private var backgroundSyncFlushTask: Task<Void, Never>?
    @State private var isBackgroundSyncFlushInProgress = false
    @State private var pendingBackgroundSyncContent = PendingSyncedContent()
    @State private var lastForegroundInteractionAt = Date.distantPast
    @State private var queuedNotificationReplies: [NotificationReplyRequest] = []

    init(launchCommand: AppWindowLaunchCommand? = nil) {
        self.launchCommand = launchCommand
    }

    /// Whether the user is currently authenticated
    private var isAuthenticated: Bool {
        authManager.state == .authenticated
    }

    private var filteredPinnedChats: [Chat] {
        let pinned = chatStore.pinnedChats.filter { self.publicChatGroup(for: $0.id) == nil }
        guard !searchText.isEmpty else { return pinned }
        return pinned.filter { $0.displayTitle.localizedCaseInsensitiveContains(searchText) }
    }

    private var filteredUnpinnedChats: [Chat] {
        let unpinned = chatStore.unpinnedChats.filter { self.publicChatGroup(for: $0.id) == nil }
        let filtered = searchText.isEmpty
            ? unpinned
            : unpinned.filter { $0.displayTitle.localizedCaseInsensitiveContains(searchText) }
        return orderedWithSubChats(filtered)
    }

    private func orderedWithSubChats(_ chats: [Chat]) -> [Chat] {
        let childrenByParent = Dictionary(grouping: chats.filter { $0.parentId != nil }) { $0.parentId ?? "" }
        var emitted = Set<String>()
        var ordered: [Chat] = []

        func appendChat(_ chat: Chat) {
            guard emitted.insert(chat.id).inserted else { return }
            ordered.append(chat)
            for child in childrenByParent[chat.id] ?? [] {
                appendChat(child)
            }
        }

        for chat in chats where chat.parentId == nil || !chats.contains(where: { $0.id == chat.parentId }) {
            appendChat(chat)
        }
        for chat in chats {
            appendChat(chat)
        }
        return ordered
    }

    private var visibleFilteredUnpinnedChats: [Chat] {
        guard isAuthenticated, searchText.isEmpty else { return filteredUnpinnedChats }
        return Array(filteredUnpinnedChats.prefix(visibleUserChatLimit))
    }

    private var userChatCountForDisplayLimit: Int {
        filteredUnpinnedChats.count
    }

    private var shouldShowMoreUserChats: Bool {
        guard isAuthenticated, searchText.isEmpty else { return false }
        return userChatCountForDisplayLimit > visibleUserChatLimit || totalChatCount > (filteredPinnedChats.count + filteredUnpinnedChats.count)
    }

    private var isCompactShell: Bool {
        horizontalSizeClass == .compact
    }

    private var isUITestShellMetricsEnabled: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-test-shell-metrics")
            || ProcessInfo.processInfo.environment["UI_TEST_SHELL_METRICS"] == "1"
    }

    private func isSettingsSideBySide(width: CGFloat) -> Bool {
        width > 1100
    }

    private var platformScreenWidth: CGFloat {
        #if os(iOS)
        UIScreen.main.bounds.width
        #elseif os(macOS)
        NSScreen.main?.visibleFrame.width ?? 390
        #endif
    }

    // Web `.active-chat-container`: border-radius: 17px.
    private let activeChatContainerRadius: CGFloat = 17
    private static let desktopChatsPanelWidth: CGFloat = 325
    private static let initialUserChatLimit = 11
    private static let showMoreUserChatIncrement = 20
    private static let backgroundSyncFlushDelayNs: UInt64 = 450_000_000
    private static let backgroundSyncFlushChunkSize = 4
    private static let backgroundSyncMaxEmbedsPerChunk = 120
    private static let backgroundSyncInterChunkPauseNs: UInt64 = 40_000_000
    private static let backgroundSyncForegroundPauseNs: UInt64 = 180_000_000
    private static let foregroundInteractionGraceSeconds: TimeInterval = 2.0

    private var currentDailyInspiration: DailyInspirationBanner.DailyInspiration? {
        dailyInspirations.first
    }

    private var currentWindowTitle: String {
        if let selectedChatId,
           let chatTitle = chatStore.chat(for: selectedChatId)?.displayTitle.trimmingCharacters(in: .whitespacesAndNewlines),
           !chatTitle.isEmpty {
            return chatTitle
        }
        return selectedChatId == nil || showNewChat ? AppStrings.newChat : AppStrings.openMatesName
    }

    private enum PublicChatGroup {
        case intro
        case examples
        case announcements
        case legal
    }

    private let publicChatOrder: [String: Int] = [
        "demo-for-everyone": 0,
        "demo-for-developers": 1,
        "demo-who-develops-openmates": 2,
        "example-gigantic-airplanes": 10,
        "example-artemis-ii-mission": 11,
        "example-beautiful-single-page-html": 12,
        "example-flights-berlin-bangkok": 13,
        "example-eu-chat-control-law": 14,
        "example-creativity-drawing-meetups-berlin": 15,
        "announcements-introducing-openmates-v09": 20,
        "legal-privacy": 30,
        "legal-terms": 31,
        "legal-imprint": 32
    ]

    var body: some View {
        shellWithOverlays
        .onOpenURL { url in
            deepLinkHandler.handle(url: url)
        }
        // Handoff: continue a chat from another Apple device
        .onContinueUserActivity(HandoffManager.viewChatActivityType) { activity in
            handleViewChatActivity(activity)
        }
        .onContinueUserActivity(HandoffManager.browseChatsActivityType) { _ in
            // Just bring the app to the chat list — no specific action needed
        }
        // Spotlight: open a chat from system search results
        .onContinueUserActivity(CSSearchableItemActionType) { activity in
            handleSpotlightActivity(activity)
        }
        // Global keyboard shortcuts (iPad + Mac)
        .appKeyboardShortcuts(
            onNewChat: openNewChatScreen,
            onSearch: openSearchOverlay,
            onSettings: { showSettings = true }
        )
        .modifier(externalEventHandlers)
        .onChange(of: deepLinkHandler.pendingChatId, pendingDeepLinkChatDidChange)
        .onChange(of: deepLinkHandler.pendingPairToken, pendingPairTokenDidChange)
        .onChange(of: deepLinkHandler.pendingInspirationId, pendingInspirationDidChange)
        .onReceive(NotificationCenter.default.publisher(for: .newChat)) { _ in
            openNewChatScreen()
        }
        .onReceive(NotificationCenter.default.publisher(for: .toggleIncognito)) { _ in
            incognitoManager.toggle()
            ToastManager.shared.show(
                incognitoManager.isEnabled ? AppStrings.incognitoModeOn : AppStrings.incognitoModeOff,
                type: .info
            )
        }
        .onReceive(NotificationCenter.default.publisher(for: .openAuth)) { _ in
            showAuthSheet = true
        }
        #if os(iOS)
        .onReceive(NotificationCenter.default.publisher(for: .handoffChatReceived)) { notification in
            if let chatId = notification.userInfo?["chatId"] as? String {
                selectedChatId = chatId
                showNewChat = false
            }
        }
        #endif
        .task {
            await runStartupTask()
        }
        .onReceive(NotificationCenter.default.publisher(for: .wsMessageReceived)) { notification in
            handleChatUpdate(notification)
        }
        .onReceive(NotificationCenter.default.publisher(for: .wsEmbedUpdate)) { notification in
            handleEmbedUpdate(notification)
        }
        .onReceive(NotificationCenter.default.publisher(for: .wsSyncEvent)) { notification in
            handleSyncEvent(notification)
        }
        .onReceive(NotificationCenter.default.publisher(for: .wsHistoryRequested)) { notification in
            handleHistoryRequest(notification)
        }
        .onReceive(NotificationCenter.default.publisher(for: .pendingDeferredSendRequested)) { notification in
            handlePendingDeferredSend(notification)
        }
        .onReceive(NotificationCenter.default.publisher(for: .wsForceLogout)) { notification in
            let reason = notification.userInfo?["reason"] as? String ?? "session_revoked"
            Task {
                await authManager.forceLocalLogout(reason: reason)
            }
        }
        .onChange(of: authManager.state, authStateDidChange)
        .onChange(of: pushManager.pendingChatId, pendingPushChatDidChange)
        .onChange(of: pushManager.pendingReplyRequest, pendingPushReplyDidChange)
        .onChange(of: selectedChatId, selectedChatDidChange)
        .onChange(of: showNewChat, showNewChatDidChange)
        .onChange(of: showSettings, showSettingsDidChange)
        .onChange(of: scenePhase, scenePhaseDidChange)
    }

    private var shellWithOverlays: some View {
        rootShell
        #if os(macOS)
        .focusedSceneValue(\.newChatCommand) {
            openNewChatScreen()
        }
        .background {
            MacWindowTitleUpdater(title: currentWindowTitle)
                .frame(width: 0, height: 0)
        }
        #endif
        .overlay {
            ToastOverlay()
        }
        .overlay {
            if let actionChat {
                chatActionsOverlay(for: actionChat)
            }
        }
        .overlay {
            appOverlays
        }
        .overlay(alignment: .top) {
            topStatusOverlay
                .allowsHitTesting(false)
        }
    }

    private var externalEventHandlers: MainAppExternalEventModifier {
        MainAppExternalEventModifier(
            deepLinkHandler: deepLinkHandler,
            onDeepLink: { url in
                deepLinkHandler.handle(url: url)
            },
            onQuickAction: { action in
                handleQuickAction(action)
                AppQuickActionCenter.shared.clearPendingAction(action)
            },
            onNewChatDeepLink: {
                openNewChatScreen()
                deepLinkHandler.pendingNewChat = false
            },
            onSearchDeepLink: {
                openSearchOverlay()
                deepLinkHandler.pendingSearch = false
            }
        )
    }

    private func pendingDeepLinkChatDidChange(_ oldValue: String?, _ chatId: String?) {
        if let chatId {
            selectedChatId = chatId
            showNewChat = false
            deepLinkHandler.clearPending()
        }
    }

    private func pendingPairTokenDidChange(_ oldValue: String?, _ token: String?) {
        if let token {
            pairToken = token
            showPairAuthorize = true
            deepLinkHandler.pendingPairToken = nil
        }
    }

    private func pendingInspirationDidChange(_ oldValue: String?, _ inspirationId: String?) {
        if inspirationId != nil {
            selectedChatId = nil
            showNewChat = true
            deepLinkHandler.pendingInspirationId = nil
        }
    }

    private var rootShell: some View {
        GeometryReader { geo in
            let viewportWidth = geo.size.width
            let compactPanelWidth = min(viewportWidth - 10, 390)
            let chatsPanelOffset = isCompactShell
                ? (isChatsPanelOpen ? max(0, compactPanelWidth + shellDragOffset) : max(0, shellDragOffset))
                : 0

            Group {
                if isCompactShell {
                    ZStack(alignment: .leading) {
                        activeAppChrome(viewportWidth: viewportWidth)
                            .offset(x: chatsPanelOffset)

                        chatsPanel
                            .frame(width: compactPanelWidth)
                            .offset(x: isChatsPanelOpen ? min(0, shellDragOffset) : -compactPanelWidth + max(0, shellDragOffset))
                            .allowsHitTesting(isChatsPanelOpen || shellDragOffset > 0)
                            .accessibilityHidden(!isChatsPanelOpen)
                            .zIndex(1)
                    }
                } else {
                    HStack(spacing: isChatsPanelOpen ? .spacing5 : 0) {
                        if isChatsPanelOpen {
                            chatsPanel
                                .frame(width: Self.desktopChatsPanelWidth)
                                .transition(.move(edge: .leading).combined(with: .opacity))
                        }

                        activeAppChrome(viewportWidth: regularMainWidth(for: viewportWidth))
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .clipped()
            .contentShape(Rectangle())
            .simultaneousGesture(shellSwipeGesture(viewportWidth: viewportWidth))
            .animation(.easeInOut(duration: 0.24), value: isChatsPanelOpen)
            .overlay(alignment: .bottomLeading) {
                shellMetricsProbe(viewportWidth: viewportWidth, compactPanelWidth: compactPanelWidth)
            }
        }
        .background(Color.grey0)
    }

    @ViewBuilder
    private func shellMetricsProbe(viewportWidth: CGFloat, compactPanelWidth: CGFloat) -> some View {
        if isUITestShellMetricsEnabled {
            let metrics = shellMetricsLabel(viewportWidth: viewportWidth, compactPanelWidth: compactPanelWidth)
            Text(metrics)
                .font(.omMicro)
                .foregroundStyle(Color.fontTertiary)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, .spacing5)
                .padding(.vertical, .spacing1)
                .background(Color.grey0.opacity(0.86))
                .accessibilityIdentifier("shell-responsive-metrics")
                .accessibilityLabel(metrics)
        }
    }

    private func shellMetricsLabel(viewportWidth: CGFloat, compactPanelWidth: CGFloat) -> String {
        let shellMode = isCompactShell ? "compact" : "regular"
        let panelMode = isCompactShell ? "drawer" : "side-by-side"
        let activeMainWidth = isCompactShell ? viewportWidth : regularMainWidth(for: viewportWidth)
        return [
            "shell-width=\(Int(viewportWidth.rounded()))",
            "shell-mode=\(shellMode)",
            "panel-mode=\(panelMode)",
            "chat-panel-open=\(isChatsPanelOpen)",
            "chat-panel-visible=\(isChatsPanelOpen)",
            "active-chat-visible=true",
            "chat-panel-width=\(Int(compactPanelWidth.rounded()))",
            "active-main-width=\(Int(activeMainWidth.rounded()))"
        ].joined(separator: "; ")
    }

    private func regularMainWidth(for viewportWidth: CGFloat) -> CGFloat {
        guard !isCompactShell, isChatsPanelOpen else { return viewportWidth }
        return max(0, viewportWidth - Self.desktopChatsPanelWidth - .spacing5)
    }

    private func selectedChatDidChange(_ oldValue: String?, _ chatId: String?) {
        if chatId != nil {
            lastForegroundInteractionAt = Date()
        }
        Task { await announceActiveChat(chatId) }
    }

    private func authStateDidChange(_ oldValue: AuthManager.AuthState, _ newState: AuthManager.AuthState) {
        if newState == .authenticated {
            showAuthSheet = false
            authFlowState.reset()
            Task {
                await bootstrapAuthenticatedSession()
                await flushQueuedNotificationReplies()
            }
        } else if newState == .unauthenticated {
            resetToUnauthenticatedSession()
        }
    }

    private func pendingPushChatDidChange(_ oldValue: String?, _ chatId: String?) {
        if let chatId {
            selectedChatId = chatId
            showNewChat = false
            pushManager.pendingChatId = nil
        }
    }

    private func pendingPushReplyDidChange(_ oldValue: NotificationReplyRequest?, _ request: NotificationReplyRequest?) {
        guard let request else { return }
        pushManager.pendingReplyRequest = nil
        Task { await sendNotificationReply(request) }
    }

    private func showNewChatDidChange(_ oldValue: Bool, _ isOpen: Bool) {
        if isOpen {
            Task { await announceActiveChat(nil) }
        }
    }

    private func showSettingsDidChange(_ oldValue: Bool, _ isOpen: Bool) {
        if isOpen {
            lastForegroundInteractionAt = Date()
        }
    }

    private func scenePhaseDidChange(_ oldValue: ScenePhase, _ newValue: ScenePhase) {
        guard newValue == .active, isAuthenticated, didBootstrapAuthenticatedSession else { return }
        switch wsManager.connectionState {
        case .connected, .connecting, .reconnecting:
            break
        case .disconnected:
            connectWebSocket()
        }
    }

    private func sendNotificationReply(_ request: NotificationReplyRequest) async {
        guard isAuthenticated, didBootstrapAuthenticatedSession else {
            if !queuedNotificationReplies.contains(request) {
                queuedNotificationReplies.append(request)
            }
            return
        }
        let content = request.content.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty else { return }

        if chatStore.chat(for: request.chatId) == nil {
            await loadInitialData()
        }

        guard let chat = chatStore.chat(for: request.chatId) else {
            print("[MainApp] Notification reply dropped; chat \(request.chatId.prefix(8)) is not available locally")
            return
        }

        do {
            _ = try await ChatSendPipeline().sendUserMessage(
                content: content,
                in: chat,
                existingMessages: chatStore.messages(for: request.chatId),
                wsManager: wsManager,
                chatStore: chatStore,
                activateChat: false
            )
        } catch {
            print("[MainApp] Failed to send notification reply for chat \(request.chatId.prefix(8)): \(error)")
        }
    }

    private func flushQueuedNotificationReplies() async {
        guard isAuthenticated, didBootstrapAuthenticatedSession, !queuedNotificationReplies.isEmpty else { return }
        let replies = queuedNotificationReplies
        queuedNotificationReplies.removeAll()
        for reply in replies {
            await sendNotificationReply(reply)
        }
    }

    private func openNewChatScreen() {
        selectedChatId = nil
        showNewChat = true
        showAuthSheet = false
        showSearch = false
        showExplore = false
        showShareChat = false
        showHiddenChats = false
        actionChat = nil
    }

    private func openSearchOverlay() {
        showSearch = true
        lastForegroundInteractionAt = Date()
    }

    private func handleQuickAction(_ action: AppQuickAction) {
        switch action {
        case .newChat:
            openNewChatScreen()
        case .search:
            openSearchOverlay()
        }
    }

    private func resetToUnauthenticatedSession() {
        didBootstrapAuthenticatedSession = false
        syncProcessingTask?.cancel()
        syncProcessingTask = nil
        backgroundSyncFlushTask?.cancel()
        backgroundSyncFlushTask = nil
        isBackgroundSyncFlushInProgress = false
        pendingBackgroundSyncContent = PendingSyncedContent()
        appSession.resetTransientRuntime()
        totalChatCount = 0
        selectedChatId = nil
        showNewChat = false
        visibleUserChatLimit = Self.initialUserChatLimit
        loadDemoChats(selectDefault: false)
    }

    private func applyLaunchCommandIfNeeded() {
        guard !didApplyLaunchCommand else { return }
        didApplyLaunchCommand = true

        if launchCommand?.action == .newChat {
            openNewChatScreen()
        }
    }

    private func runStartupTask() async {
        if isAuthenticated {
            await bootstrapAuthenticatedSession()
        } else {
            // Unauthenticated: populate sidebar with demo chats
            loadDemoChats()
            // Fetch default daily inspirations (public endpoint, no auth required)
            Task { await syncInspirationToWidget() }
        }
        applyLaunchCommandIfNeeded()
        applyPendingQuickActionIfNeeded()
    }

    private func applyPendingQuickActionIfNeeded() {
        guard let action = AppQuickActionCenter.shared.consumePendingAction() else { return }
        handleQuickAction(action)
    }

    private func handleViewChatActivity(_ activity: NSUserActivity) {
        if let chatId = activity.userInfo?["chatId"] as? String {
            selectedChatId = chatId
            showNewChat = false
        }
    }

    private func handleSpotlightActivity(_ activity: NSUserActivity) {
        guard let identifier = activity.userInfo?[CSSearchableItemActivityIdentifier] as? String,
              identifier.hasPrefix("chat-") else { return }
        selectedChatId = String(identifier.dropFirst("chat-".count))
        showNewChat = false
    }

    private var topStatusOverlay: some View {
        VStack(spacing: 0) {
            OfflineBanner(isOffline: syncBridge?.networkStatus == .offline)
            NetworkStatusBanner(wsManager: wsManager)
        }
    }

    private func shellSwipeGesture(viewportWidth: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 45)
            .onChanged { value in
                updateShellSwipeProgress(value, viewportWidth: viewportWidth)
            }
            .onEnded { value in
                handleShellSwipe(value, viewportWidth: viewportWidth)
            }
    }

    private func updateShellSwipeProgress(_ value: DragGesture.Value, viewportWidth: CGFloat) {
        let dx = value.translation.width
        let dy = value.translation.height
        guard abs(dx) > abs(dy) * 1.2 else {
            shellDragOffset = 0
            return
        }

        let target = currentShellSwipeTarget(for: value, viewportWidth: viewportWidth)
        switch target {
        case .openChats:
            shellDragOffset = min(dx, min(viewportWidth - 10, 390))
        case .closeChats:
            shellDragOffset = min(0, dx)
        case .openSettings:
            shellDragOffset = max(dx, -min(viewportWidth - 40, 323))
        case .closeSettings:
            shellDragOffset = min(dx, min(viewportWidth - 40, 323))
        case nil:
            shellDragOffset = 0
        }
    }

    private func handleShellSwipe(_ value: DragGesture.Value, viewportWidth: CGFloat) {
        let dx = value.translation.width
        let dy = value.translation.height
        defer {
            shellSwipeTarget = nil
            shellDragOffset = 0
        }
        guard abs(dx) > 70, abs(dx) > abs(dy) * 1.35 else { return }
        guard let target = currentShellSwipeTarget(for: value, viewportWidth: viewportWidth) else { return }

        withAnimation(.easeInOut(duration: 0.24)) {
            switch target {
            case .openChats:
                isChatsPanelOpen = true
            case .closeChats:
                isChatsPanelOpen = false
            case .openSettings:
                showSettings = true
            case .closeSettings:
                showSettings = false
            }
        }
    }

    private func currentShellSwipeTarget(for value: DragGesture.Value, viewportWidth: CGFloat) -> ShellSwipeTarget? {
        if let shellSwipeTarget {
            return shellSwipeTarget
        }

        let dx = value.translation.width
        let startedNearLeftEdge = value.startLocation.x <= 42
        let startedNearRightEdge = value.startLocation.x >= viewportWidth - 42
        let settingsPanelWidth = min(viewportWidth - 40, 323)
        let settingsIsOverlay = showSettings && !isSettingsSideBySide(width: viewportWidth)
        let startedInSettingsPanel = value.startLocation.x >= viewportWidth - settingsPanelWidth
        let target: ShellSwipeTarget?

        if settingsIsOverlay, dx > 0 {
            target = .closeSettings
        } else if showSettings, dx > 0, startedInSettingsPanel {
            target = .closeSettings
        } else if !isChatsPanelOpen, startedNearLeftEdge, dx > 0 {
            target = .openChats
        } else if isChatsPanelOpen, dx < 0 {
            target = .closeChats
        } else if !showSettings, startedNearRightEdge, dx < 0 {
            target = .openSettings
        } else {
            target = nil
        }

        shellSwipeTarget = target
        return target
    }

    private func activeAppChrome(viewportWidth: CGFloat) -> some View {
        VStack(spacing: 0) {
            OpenMatesWebHeader(
                isAuthenticated: isAuthenticated || showAuthSheet,
                isChatsPanelOpen: isChatsPanelOpen,
                isSettingsOpen: showSettings,
                profileUserId: authManager.currentUser?.id,
                profileImageUrl: authManager.currentUser?.profileImageUrl,
                onToggleChats: { withAnimation(.easeInOut(duration: 0.2)) { isChatsPanelOpen.toggle() } },
                onNewChat: { selectedChatId = nil; showNewChat = true },
                onShareChat: { showShareChat = true },
                canShareChat: selectedChatId != nil,
                onOpenSettings: {
                    withAnimation(.easeInOut(duration: 0.3)) {
                        showSettings.toggle()
                    }
                },
                onOpenAuth: { showAuthSheet = true }
            )

            chatContainer {
                if isSettingsSideBySide(width: viewportWidth) {
                    HStack(spacing: showSettings ? .spacing10 : 0) {
                        shellContent

                        settingsPanel(width: 323)
                            .frame(width: showSettings ? 323 : 0, alignment: .trailing)
                            .opacity(showSettings ? 1 : 0)
                            .clipped()
                            .allowsHitTesting(showSettings)
                            .accessibilityHidden(!showSettings)
                    }
                    .animation(.easeInOut(duration: 0.3), value: showSettings)
                } else {
                    shellContent
                        .overlay {
                            settingsSlidePanel(viewportWidth: viewportWidth)
                        }
                }
            }
        }
    }

    // MARK: - Web-style shell

    private func chatContainer<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        content()
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.grey20)
            .clipShape(RoundedRectangle(cornerRadius: activeChatContainerRadius))
            .shadow(color: .black.opacity(0.25), radius: 12, x: 0, y: 0)
            .padding(.horizontal, .spacing5)
            .padding(.top, .spacing5)
            .padding(.bottom, .spacing5)
    }

    @ViewBuilder
    private var appOverlays: some View {
        if showExplore {
            appOverlay(title: AppStrings.explore, isPresented: $showExplore) {
                PublicChatListView()
            }
        }

        if showSearch {
            appOverlay(title: AppStrings.search, isPresented: $showSearch) {
                ChatSearchView { chatId in
                    selectedChatId = chatId
                    showSearch = false
                }
            }
        }

        if showShareChat, let chatId = selectedChatId {
            appOverlay(title: AppStrings.share, isPresented: $showShareChat) {
                ChatShareView(chatId: chatId)
            }
        }

        if showHiddenChats {
            appOverlay(title: AppStrings.hiddenChats, isPresented: $showHiddenChats) {
                if hiddenChatsUnlocked {
                    HiddenChatsListView(
                        onSelectChat: { chatId in
                            selectedChatId = chatId
                            showHiddenChats = false
                        },
                        onUnhideChat: { chatId in
                            unhideChat(chatId)
                        }
                    )
                } else {
                    HiddenChatsUnlockView(isUnlocked: $hiddenChatsUnlocked)
                }
            }
        }

        if showPairAuthorize, let pairToken {
            appOverlay(title: AppStrings.pairNewDevice, isPresented: $showPairAuthorize) {
                CLIPairAuthorizeView(token: pairToken)
            }
        }

        if showRenameAlert {
            renameOverlay
        }
    }

    // MARK: - Settings slide panel (web: slides from right, 323px wide, shadow)

    private func settingsPanel(width: CGFloat) -> some View {
        SettingsView {
            withAnimation(.easeInOut(duration: 0.3)) {
                showSettings = false
            }
        }
        .environmentObject(authManager)
        .environmentObject(themeManager)
        .frame(width: width)
        .frame(maxHeight: .infinity)
        .background(Color.grey20)
        .clipShape(RoundedRectangle(cornerRadius: activeChatContainerRadius))
        .shadow(color: .black.opacity(0.25), radius: 12, x: 0, y: 0)
    }

    private func settingsSlidePanel(viewportWidth: CGFloat) -> some View {
        ZStack(alignment: .trailing) {
            // Dimmed backdrop — web: .active-chat-container.dimmed opacity 0.3
            if showSettings {
                Color.black.opacity(0.35)
                    .ignoresSafeArea()
                    .onTapGesture { withAnimation(.easeInOut(duration: 0.3)) { showSettings = false } }
                    .transition(.opacity)
            }

            // Settings panel — web: 323px, fixed right, translateX slide
            let panelWidth = min(viewportWidth - 40, 323)
            let dragReveal = !showSettings ? max(0, -shellDragOffset) : max(0, panelWidth - shellDragOffset)
            if showSettings || dragReveal > 0 {
                HStack(spacing: 0) {
                    Spacer(minLength: 0)
                    settingsPanel(width: panelWidth)
                        .offset(x: showSettings ? max(0, shellDragOffset) : max(0, panelWidth + shellDragOffset))
                }
                .transition(.move(edge: .trailing))
            }
        }
        .animation(.easeInOut(duration: 0.3), value: showSettings)
    }

    private func appOverlay<Content: View>(
        title: String,
        isPresented: Binding<Bool>,
        maxWidth: CGFloat = 760,
        maxHeight: CGFloat = 760,
        showHeader: Bool = true,
        @ViewBuilder content: () -> Content
    ) -> some View {
        ZStack {
            Color.black.opacity(0.35)
                .ignoresSafeArea()
                .onTapGesture {
                    isPresented.wrappedValue = false
                }

            VStack(spacing: 0) {
                if showHeader {
                    HStack(spacing: .spacing4) {
                        Text(title)
                            .font(.omH3)
                            .fontWeight(.semibold)
                            .foregroundStyle(Color.fontPrimary)
                        Spacer()
                        OMIconButton(icon: "close", label: AppStrings.close, size: 34) {
                            isPresented.wrappedValue = false
                        }
                    }
                    .padding(.spacing6)
                    .background(Color.grey0)
                }

                content()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .frame(maxWidth: maxWidth, maxHeight: maxHeight)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .overlay(
                RoundedRectangle(cornerRadius: .radius8)
                    .stroke(Color.grey20, lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.18), radius: 24, x: 0, y: 12)
            .padding(.spacing8)
        }
    }

    private var renameOverlay: some View {
        ZStack {
            Color.black.opacity(0.35)
                .ignoresSafeArea()
                .onTapGesture {
                    showRenameAlert = false
                }

            VStack(alignment: .leading, spacing: .spacing5) {
                HStack {
                    Text(AppStrings.renameChat)
                        .font(.omH3)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontPrimary)
                    Spacer()
                    OMIconButton(icon: "close", label: AppStrings.cancel, size: 34) {
                        showRenameAlert = false
                    }
                }

                TextField(AppStrings.chatTitle, text: $renameChatTitle)
                    .textFieldStyle(OMTextFieldStyle())

                HStack(spacing: .spacing3) {
                    Button(AppStrings.cancel) {
                        showRenameAlert = false
                    }
                    .buttonStyle(OMSecondaryButtonStyle())

                    Button(AppStrings.rename) {
                        submitRename()
                    }
                    .buttonStyle(OMPrimaryButtonStyle())
                }
            }
            .padding(.spacing6)
            .frame(maxWidth: 420)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .overlay(
                RoundedRectangle(cornerRadius: .radius8)
                    .stroke(Color.grey20, lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.18), radius: 24, x: 0, y: 12)
            .padding(.spacing8)
        }
    }

    @ViewBuilder
    private var shellContent: some View {
        if isCompactShell {
            if showAuthSheet {
                authContent
            } else {
                detailContent
            }
        } else if showAuthSheet {
            authContent
        } else {
            detailContent
        }
    }

    private var authContent: some View {
        AuthFlowView(onBackToDemo: {
            authFlowState.reset()
            showAuthSheet = false
            selectedChatId = "demo-for-everyone"
        }, flowState: authFlowState)
        .environmentObject(authManager)
    }

    @ViewBuilder
    private var detailContent: some View {
        if showNewChat || selectedChatId == nil {
            NewChatWelcomeView(
                inspirations: dailyInspirations,
                isAuthenticated: isAuthenticated,
                currentUser: authManager.currentUser,
                chats: chatStore.chats,
                totalChatCount: totalChatCount,
                serverSuggestions: syncedNewChatSuggestions,
                onCreateChatWithMessage: { message in
                    let chatId = UUID().uuidString
                    let now = ChatSendPipeline.isoString(from: Date())
                    let chat = Chat(
                        id: chatId,
                        title: nil,
                        lastMessageAt: nil,
                        createdAt: now,
                        updatedAt: now,
                        isArchived: false,
                        isPinned: false,
                        appId: nil,
                        encryptedTitle: nil,
                        encryptedChatKey: nil,
                        messagesV: 0,
                        titleV: 0,
                        draftV: 0
                    )
                    let result = try await ChatSendPipeline().sendUserMessage(
                        content: message,
                        in: chat,
                        existingMessages: [],
                        wsManager: wsManager,
                        chatStore: chatStore,
                        waitForRemoteSend: false
                    )
                    return result.chat.id
                },
                onChatCreated: { chatId in
                    selectedChatId = chatId
                    showNewChat = false
                },
                onOpenChat: { chatId in
                    selectedChatId = chatId
                    showNewChat = false
                },
                onInspirationViewed: { inspirationId in
                    guard isAuthenticated else { return }
                    Task {
                        do {
                            try await wsManager.send(
                                WSOutboundMessage(
                                    type: "inspiration_viewed",
                                    payload: ["inspiration_id": inspirationId]
                                )
                            )
                        } catch {
                            print("[MainApp] Failed to mark inspiration viewed: \(error)")
                        }
                    }
                },
                onOpenAuth: { showAuthSheet = true }
            )
        } else if isAuthenticated, let chatId = selectedChatId {
            let isPublic = publicChatGroup(for: chatId) != nil
            let initialWindow: [Message] = isPublic ? [] : chatStore.initialMessageWindow(for: chatId)
            ChatView(
                chatId: chatId,
                bannerState: isPublic ? demoBannerState(for: chatId) : nil,
                bannerCreatedAt: nil,
                initialChat: isPublic ? nil : chatStore.chat(for: chatId),
                initialMessages: initialWindow,
                initialEmbeds: isPublic ? [] : chatStore.initialEmbedsForVisibleWindow(for: chatId, messages: initialWindow),
                wsManager: wsManager,
                chatStore: chatStore,
                isSettingsOpen: !isCompactShell && showSettings,
                onShareChat: { showShareChat = true },
                onPreviousChat: previousChatAction(for: chatId),
                onNextChat: nextChatAction(for: chatId),
                onOpenPublicChat: openPublicChat,
                onOpenChat: { selectedChatId = $0; showNewChat = false },
                onNewChat: openNewChatScreen,
                onScrollPositionChanged: { messageId in
                    sendScrollPositionUpdate(chatId: chatId, messageId: messageId)
                }
            )
        } else if !isAuthenticated, let chatId = selectedChatId {
            ChatView(
                chatId: chatId,
                bannerState: demoBannerState(for: chatId),
                bannerCreatedAt: nil,
                isSettingsOpen: !isCompactShell && showSettings,
                onPreviousChat: previousChatAction(for: chatId),
                onNextChat: nextChatAction(for: chatId),
                onOpenPublicChat: openPublicChat,
                onNewChat: openNewChatScreen
            )
        }
    }

    // MARK: - Chat navigation (prev/next)
    // Web: chatNavigationStore — navigatePrev/navigateNext switch to adjacent chat in sidebar list.

    /// Ordered chat list matching sidebar display order (pinned first, then by lastMessageAt).
    private var orderedChatIds: [String] {
        let pinned = chatStore.chats.filter { $0.isPinned == true }.sorted { ($0.lastMessageAt ?? "") > ($1.lastMessageAt ?? "") }
        let unpinned = chatStore.chats.filter { $0.isPinned != true && $0.isArchived != true }.sorted { ($0.lastMessageAt ?? "") > ($1.lastMessageAt ?? "") }
        return (pinned + unpinned).map(\.id)
    }

    private func previousChatAction(for chatId: String) -> (() -> Void)? {
        guard let idx = orderedChatIds.firstIndex(of: chatId), idx > 0 else { return nil }
        let prevId = orderedChatIds[idx - 1]
        return { selectedChatId = prevId }
    }

    private func nextChatAction(for chatId: String) -> (() -> Void)? {
        guard let idx = orderedChatIds.firstIndex(of: chatId), idx < orderedChatIds.count - 1 else { return nil }
        let nextId = orderedChatIds[idx + 1]
        return { selectedChatId = nextId }
    }

    private func openPublicChat(_ chatId: String) {
        guard chatStore.chat(for: chatId) != nil else {
            print("[MainApp] Public chat card selected unknown chat id: \(chatId)")
            return
        }
        selectedChatId = chatId
        if isCompactShell {
            isChatsPanelOpen = false
        }
    }

    private var chatsPanel: some View {
        VStack(spacing: 0) {
            chatPanelTopButtons

            ScrollView {
                LazyVStack(alignment: .leading, spacing: .spacing2) {
                    showHiddenChatsButton

                    if !filteredPinnedChats.isEmpty {
                        chatSectionHeader(AppStrings.pinnedChats)
                        ForEach(filteredPinnedChats) { chat in
                            chatRow(chat)
                        }
                    }

                    if !visibleFilteredUnpinnedChats.isEmpty {
                        let header = filteredPinnedChats.isEmpty ? AppStrings.chats : AppStrings.recentChats
                        chatSectionHeader(header)
                        ForEach(visibleFilteredUnpinnedChats) { chat in
                            chatRow(chat)
                        }
                    } else if filteredPinnedChats.isEmpty && isAuthenticated && self.publicChats(in: .intro).isEmpty {
                        Text(AppStrings.noChats)
                            .font(.omSmall)
                            .foregroundStyle(Color.fontTertiary)
                            .frame(maxWidth: .infinity, alignment: .center)
                            .padding(.top, .spacing10)
                    }

                    if shouldShowMoreUserChats {
                        ShowMoreChatsButton(
                            totalCount: max(totalChatCount, userChatCountForDisplayLimit),
                            loadedCount: min(visibleUserChatLimit, userChatCountForDisplayLimit),
                            isLoading: isLoadingMore,
                            onLoadMore: { showMoreUserChats() }
                        )
                        .padding(.horizontal, .spacing5)
                    }

                    chatPublicSection(.intro, title: AppStrings.introSection)
                    chatPublicSection(.examples, title: AppStrings.exampleChatsSection)
                    chatPublicSection(.announcements, title: AppStrings.announcementsSection)
                    chatPublicSection(.legal, title: AppStrings.legalSection)
                }
                .padding(.vertical, .spacing3)
            }
            .refreshable {
                if isAuthenticated {
                    await loadInitialData()
                }
            }
        }
        .background(Color.grey0)
        .accessibilityIdentifier("chat-history-panel")
    }

    private var chatPanelTopButtons: some View {
        HStack(spacing: .spacing6) {
            Button {
                openSearchOverlay()
            } label: {
                Icon("search", size: 25)
                    .foregroundStyle(LinearGradient.primary)
                    .frame(width: 25, height: 25)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("search-button")
            .accessibilityLabel(AppStrings.search)

            Spacer()

            Button {
                withAnimation(.easeInOut(duration: 0.24)) {
                    isChatsPanelOpen = false
                }
            } label: {
                Icon("close", size: 25)
                    .foregroundStyle(LinearGradient.primary)
                    .frame(width: 25, height: 25)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(AppStrings.close)
        }
        .frame(height: 32)
        .padding(.horizontal, .spacing10)
        .padding(.vertical, .spacing8)
        .background(Color.grey20)
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(Color.grey30)
                .frame(height: 1)
        }
    }

    private var showHiddenChatsButton: some View {
        Button {
            if isAuthenticated {
                showHiddenChats = true
            } else {
                showAuthSheet = true
                withAnimation(.easeInOut(duration: 0.24)) {
                    isChatsPanelOpen = false
                }
            }
        } label: {
            HStack(spacing: .spacing4) {
                Icon("hidden", size: 18)
                    .foregroundStyle(LinearGradient.primary)
                Text(AppStrings.showHiddenChats.uppercased())
                    .font(.omXs)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontTertiary)
                Spacer()
            }
            .padding(.horizontal, .spacing5)
            .padding(.vertical, .spacing4)
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private func chatPublicSection(_ group: PublicChatGroup, title: String) -> some View {
        let chats = self.publicChats(in: group)
        if !chats.isEmpty {
            chatSectionHeader(title)
            ForEach(chats) { chat in
                chatRow(chat)
            }
        }
    }

    private func chatSectionHeader(_ title: String) -> some View {
        Text(title.uppercased())
            .font(.omXs)
            .fontWeight(.semibold)
            .foregroundStyle(Color.fontTertiary)
            .padding(.horizontal, .spacing5)
            .padding(.top, .spacing4)
            .padding(.bottom, .spacing1)
    }

    private func publicChatGroup(for chatId: String) -> PublicChatGroup? {
        if chatId.hasPrefix("demo-") {
            return .intro
        }
        if chatId.hasPrefix("example-") {
            return .examples
        }
        if chatId.hasPrefix("announcements-") {
            return .announcements
        }
        if chatId.hasPrefix("legal-") {
            return .legal
        }
        return nil
    }

    private func publicChats(in group: PublicChatGroup) -> [Chat] {
        let chats = chatStore.chats.filter { publicChatGroup(for: $0.id) == group }
        let filtered = searchText.isEmpty
            ? chats
            : chats.filter { $0.displayTitle.localizedCaseInsensitiveContains(searchText) }
        return filtered.sorted {
            (publicChatOrder[$0.id] ?? Int.max) < (publicChatOrder[$1.id] ?? Int.max)
        }
    }

    @ViewBuilder
    private func chatRow(_ chat: Chat) -> some View {
        let isSelected = selectedChatId == chat.id
        Button {
            selectedChatId = chat.id
            showNewChat = false
            if isCompactShell {
                withAnimation(.easeInOut(duration: 0.2)) {
                    isChatsPanelOpen = false
                }
            }
        } label: {
            ChatListRow(chat: chat)
                .background(isSelected ? Color.buttonPrimary.opacity(0.12) : Color.clear)
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
                .contentShape(RoundedRectangle(cornerRadius: .radius3))
        }
        .buttonStyle(.plain)
        .padding(.horizontal, .spacing3)
        .onLongPressGesture {
            if isAuthenticated {
                actionChat = chat
            }
        }
    }

    private func chatActionsOverlay(for chat: Chat) -> some View {
        ZStack {
            Color.black.opacity(0.28)
                .ignoresSafeArea()
                .onTapGesture {
                    actionChat = nil
                }

            VStack(alignment: .leading, spacing: .spacing2) {
                Text(chat.displayTitle)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(1)
                    .padding(.horizontal, .spacing4)
                    .padding(.top, .spacing3)

                chatActionRow(icon: "copy", title: chat.isPinned == true ? AppStrings.unpin : AppStrings.pin) {
                    pinChat(chat)
                    actionChat = nil
                }

                chatActionRow(icon: "share", title: AppStrings.share) {
                    selectedChatId = chat.id
                    showShareChat = true
                    actionChat = nil
                }

                chatActionRow(icon: "copy", title: AppStrings.rename) {
                    renameChat(chat)
                    actionChat = nil
                }

                chatActionRow(icon: "copy", title: AppStrings.archive) {
                    archiveChat(chat.id)
                    actionChat = nil
                }

                chatActionRow(icon: "anonym", title: AppStrings.hide) {
                    hideChat(chat.id)
                    actionChat = nil
                }

                chatActionRow(icon: "delete", title: AppStrings.delete, isDestructive: true) {
                    deleteChat(chat.id)
                    actionChat = nil
                }
            }
            .padding(.vertical, .spacing2)
            .frame(width: 280)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius7))
            .overlay(
                RoundedRectangle(cornerRadius: .radius7)
                    .stroke(Color.grey20, lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.18), radius: 18, x: 0, y: 10)
        }
    }

    private func chatActionRow(
        icon: String,
        title: String,
        isDestructive: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: .spacing3) {
                Icon(icon, size: 17)
                    .foregroundStyle(isDestructive ? Color.error : Color.fontSecondary)
                Text(title)
                    .font(.omSmall)
                    .fontWeight(.medium)
                    .foregroundStyle(isDestructive ? Color.error : Color.fontPrimary)
                Spacer()
            }
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing3)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    // MARK: - Demo chats for unauthenticated users

    /// Populates the sidebar with all public chats matching the web app's cold-boot landing page.
    /// Mirrors: INTRO_CHATS + LEGAL_CHATS + announcements + example chats from demo_chats/index.ts
    private func loadDemoChats(selectDefault: Bool = true) {
        let now = ISO8601DateFormatter().string(from: Date())
        // All strings via AppStrings → LocalizationManager → i18n JSON (never hardcoded English)
        let demoChats: [Chat] = [
            // INTRO_CHATS
            Chat(id: "demo-for-everyone", title: AppStrings.demoForEveryoneTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "openmates", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "demo-for-developers", title: AppStrings.demoForDevelopersTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "openmates", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "demo-who-develops-openmates", title: AppStrings.demoWhoDevTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "openmates", encryptedTitle: nil, encryptedChatKey: nil),
            // Example chats — real conversations (exampleChatStore.ts)
            Chat(id: "example-gigantic-airplanes", title: AppStrings.exampleGiganticAirplanesTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "general_knowledge", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "example-artemis-ii-mission", title: AppStrings.exampleArtemisMissionTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "science", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "example-beautiful-single-page-html", title: AppStrings.exampleBeautifulHtmlTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "software_development", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "example-eu-chat-control-law", title: AppStrings.exampleEuChatControlTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "legal_law", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "example-flights-berlin-bangkok", title: AppStrings.exampleFlightsBerlinBangkokTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "general_knowledge", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "example-creativity-drawing-meetups-berlin", title: AppStrings.exampleCreativityDrawingTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "general_knowledge", encryptedTitle: nil, encryptedChatKey: nil),
            // Announcements newsletter chats
            Chat(id: "announcements-introducing-openmates-v09", title: AppStrings.demoAnnouncementsV09Title,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "openmates", encryptedTitle: nil, encryptedChatKey: nil),
            // Legal chats (accessible via sidebar + settings)
            Chat(id: "legal-privacy", title: AppStrings.legalPrivacyTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "openmates", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "legal-terms", title: AppStrings.legalTermsTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "openmates", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "legal-imprint", title: AppStrings.legalImprintTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "openmates", encryptedTitle: nil, encryptedChatKey: nil),
        ]
        chatStore.upsertChats(demoChats)
        if selectDefault {
            // Open the for-everyone chat by default — matches web app's cold-boot behaviour
            selectedChatId = "demo-for-everyone"
        }
    }

    /// Returns the gradient banner state for a given demo/legal/example chat ID.
    /// All strings via AppStrings → i18n JSON — never hardcoded English.
    private func demoBannerState(for chatId: String) -> ChatBannerState? {
        switch chatId {
        // INTRO_CHATS
        case "demo-for-everyone":
            return .loaded(title: AppStrings.demoForEveryoneTitle, appId: "openmates_official",
                           summary: AppStrings.demoForEveryoneDescription)
        case "demo-for-developers":
            return .loaded(title: AppStrings.demoForDevelopersTitle, appId: "openmates_official",
                           summary: AppStrings.demoForDevelopersDescription)
        case "demo-who-develops-openmates":
            return .loaded(title: AppStrings.demoWhoDevTitle, appId: "openmates_official",
                           summary: AppStrings.demoWhoDevDescription)
        // Announcements
        case "announcements-introducing-openmates-v09":
            return .loaded(title: AppStrings.demoAnnouncementsV09Title, appId: "openmates_official",
                           summary: AppStrings.demoAnnouncementsV09Description)
        // Legal chats
        case "legal-privacy":
            return .loaded(title: AppStrings.legalPrivacyTitle, appId: "ai",
                           summary: AppStrings.legalPrivacyDescription)
        case "legal-terms":
            return .loaded(title: AppStrings.legalTermsTitle, appId: "ai",
                           summary: AppStrings.legalTermsDescription)
        case "legal-imprint":
            return .loaded(title: AppStrings.legalImprintTitle, appId: "ai",
                           summary: AppStrings.legalImprintDescription)
        // Example chats
        case "example-gigantic-airplanes":
            return .loaded(title: AppStrings.exampleGiganticAirplanesTitle, appId: "general_knowledge",
                           summary: AppStrings.exampleGiganticAirplanesSummary)
        case "example-artemis-ii-mission":
            return .loaded(title: AppStrings.exampleArtemisMissionTitle, appId: "science",
                           summary: AppStrings.exampleArtemisMissionSummary)
        case "example-beautiful-single-page-html":
            return .loaded(title: AppStrings.exampleBeautifulHtmlTitle, appId: "software_development",
                           summary: AppStrings.exampleBeautifulHtmlSummary)
        case "example-eu-chat-control-law":
            return .loaded(title: AppStrings.exampleEuChatControlTitle, appId: "legal_law",
                           summary: AppStrings.exampleEuChatControlSummary)
        case "example-flights-berlin-bangkok":
            return .loaded(title: AppStrings.exampleFlightsBerlinBangkokTitle, appId: "general_knowledge",
                           summary: AppStrings.exampleFlightsBerlinBangkokSummary)
        case "example-creativity-drawing-meetups-berlin":
            return .loaded(title: AppStrings.exampleCreativityDrawingTitle, appId: "general_knowledge",
                           summary: AppStrings.exampleCreativityDrawingSummary)
        default:
            return nil
        }
    }

    // MARK: - Data loading

    private func bootstrapAuthenticatedSession() async {
        guard isAuthenticated, !didBootstrapAuthenticatedSession else { return }
        didBootstrapAuthenticatedSession = true

        print("[MainApp] Bootstrapping authenticated session")

        // Clear stale in-memory content before loading real user data, then
        // immediately re-add public sections. Web always keeps intro/example/
        // announcement/legal groups visible outside the user-chat display cap.
        chatStore.clearInMemory()
        totalChatCount = 0
        selectedChatId = nil
        showNewChat = false
        visibleUserChatLimit = Self.initialUserChatLimit
        loadDemoChats(selectDefault: false)

        let bridge = appSession.prepareAuthenticatedRuntime()
        syncBridge = bridge

        Task { await authManager.validateSessionAfterOfflineBootstrap() }
        connectWebSocket()
        scheduleTokenBackedWebSocketReconnectIfNeeded()
        scheduleInitialDataFallback()
        Task { await syncInspirationToWidget() }
        await flushQueuedNotificationReplies()
    }

    private func scheduleTokenBackedWebSocketReconnectIfNeeded() {
        guard authManager.webSocketToken?.isEmpty != false else { return }
        Task { @MainActor in
            for _ in 0..<120 {
                guard isAuthenticated, didBootstrapAuthenticatedSession else { return }
                if authManager.webSocketToken?.isEmpty == false {
                    connectWebSocket()
                    return
                }
                try? await Task.sleep(nanoseconds: 250_000_000)
            }
        }
    }

    private func scheduleInitialDataFallback() {
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            guard isAuthenticated, didBootstrapAuthenticatedSession else { return }
            let userChats = chatStore.chats.filter { publicChatGroup(for: $0.id) == nil }
            if userChats.isEmpty {
                await loadInitialData(limit: Self.initialUserChatLimit)
            }
        }
    }

    private func loadInitialData(limit: Int? = nil) async {
        do {
            let start = NativeSyncPerfLog.now()
            let path = limit.map { "/v1/chats?limit=\($0)" } ?? "/v1/chats"
            let response: ChatListResponse = try await APIClient.shared.request(.get, path: path)

            // Load master key from Keychain and unwrap per-chat keys
            if let userId = authManager.currentUser?.id {
                await loadChatKeys(chats: response.chats, userId: userId)
            }

            // Decrypt chat titles and upsert into store
            var decryptedChats: [Chat] = []
            for var chat in response.chats {
                chat = await decryptChatMetadata(chat)
                decryptedChats.append(chat)
            }
            chatStore.upsertChats(decryptedChats)

            // Defer full-text Spotlight indexing so login remains responsive.
            SpotlightIndexer.shared.scheduleIndexChats(decryptedChats, reason: "restFallback")
            NativeSyncPerfLog.info(
                "phase=restInitialLoad chats=\(response.chats.count) limit=\(limit ?? 0) elapsedMs=\(NativeSyncPerfLog.ms(since: start))"
            )
        } catch {
            print("[MainApp] Failed to load chats: \(error)")
        }
    }

    /// Load master key from Keychain, then bulk-unwrap all per-chat encryption keys.
    private func loadChatKeys(chats: [Chat], userId: String) async {
        do {
            guard let masterKey = try await CryptoManager.shared.loadMasterKey(for: userId) else {
                print("[MainApp] No master key in Keychain — encrypted content will not be decryptable")
                return
            }

            let chatKeysToLoad = chats.compactMap { chat -> (chatId: String, encryptedChatKey: String)? in
                guard !ChatKeyManager.shared.hasKey(for: chat.id) else { return nil }
                guard let eck = chat.encryptedChatKey else { return nil }
                return (chatId: chat.id, encryptedChatKey: eck)
            }

            guard !chatKeysToLoad.isEmpty else { return }

            await ChatKeyManager.shared.loadChatKeys(from: chatKeysToLoad, masterKey: masterKey)
            print("[MainApp] Loaded \(chatKeysToLoad.count) chat keys")
        } catch {
            print("[MainApp] Failed to load chat keys: \(error)")
        }
    }

    /// Fetches the current daily inspiration from the public API and writes it
    /// to the App Group container so the WidgetKit extension can display it.
    private func syncInspirationToWidget() async {
        let baseURL = await APIClient.shared.baseURL.absoluteString
        guard let url = URL(string: "\(baseURL)/v1/default-inspirations?lang=en") else { return }

        do {
            let (data, _) = try await URLSession.shared.data(from: url)

            struct Response: Decodable {
                let inspirations: [Item]
                struct Item: Decodable {
                    let inspirationId: String
                    let phrase: String
                    let title: String
                    let category: String
                    let video: Video?
                    struct Video: Decodable {
                        let youtubeId: String?
                        let title: String?
                        let channelName: String?
                        let thumbnailUrl: String?
                        let durationSeconds: Int?
                        let viewCount: Int?
                        let publishedAt: String?
                        enum CodingKeys: String, CodingKey {
                            case youtubeId = "youtube_id"
                            case title
                            case channelName = "channel_name"
                            case thumbnailUrl = "thumbnail_url"
                            case durationSeconds = "duration_seconds"
                            case viewCount = "view_count"
                            case publishedAt = "published_at"
                        }
                    }
                    enum CodingKeys: String, CodingKey {
                        case inspirationId = "inspiration_id", phrase, title, category, video
                    }
                }
            }

            let response = try JSONDecoder().decode(Response.self, from: data)
            if let first = response.inspirations.first {
                // Populate the daily inspiration state for the welcome screen
                dailyInspirations = response.inspirations.map { item in
                    DailyInspirationBanner.DailyInspiration(
                        inspirationId: item.inspirationId,
                        text: item.phrase,
                        title: item.title,
                        category: item.category,
                        iconName: nil,
                        video: item.video.map {
                            DailyInspirationVideo(
                                youtubeId: $0.youtubeId,
                                title: $0.title,
                                channelName: $0.channelName,
                                thumbnailUrl: $0.thumbnailUrl,
                                durationSeconds: $0.durationSeconds,
                                viewCount: $0.viewCount,
                                publishedAt: $0.publishedAt
                            )
                        }
                    )
                }

                // Encode as WidgetInspirationData and write to shared App Group container
                let widgetData = WidgetInspirationData(
                    phrase: first.phrase,
                    title: first.title,
                    category: first.category,
                    inspirationId: first.inspirationId,
                    videoTitle: first.video?.title,
                    channelName: first.video?.channelName,
                    thumbnailUrl: first.video?.thumbnailUrl,
                    updatedAt: Date()
                )
                if let defaults = UserDefaults(suiteName: "group.org.openmates.app"),
                   let encoded = try? JSONEncoder().encode(widgetData) {
                    defaults.set(encoded, forKey: "widget_daily_inspiration")
                }
                WidgetCenter.shared.reloadAllTimelines()
            }
        } catch {
            print("[MainApp] Inspiration API unavailable, using hardcoded default")
            // Hardcoded fallback matching web's hardcodedInspirations.ts
            if dailyInspirations.isEmpty {
                dailyInspirations = [
                    DailyInspirationBanner.DailyInspiration(
                        inspirationId: "hardcoded-dreams",
                        text: "Why does your brain create entire worlds while you sleep?",
                        title: nil,
                        category: "science",
                        iconName: nil
                    ),
                    DailyInspirationBanner.DailyInspiration(
                        inspirationId: "hardcoded-history",
                        text: "What forgotten event quietly changed how people live today?",
                        title: nil,
                        category: "history",
                        iconName: nil
                    ),
                    DailyInspirationBanner.DailyInspiration(
                        inspirationId: "hardcoded-activism",
                        text: "Which everyday choice has a bigger social impact than it seems?",
                        title: nil,
                        category: "activism",
                        iconName: nil
                    )
                ]
            }
        }
    }

    private func deleteChat(_ id: String) {
        Task {
            do {
                let _: Data = try await APIClient.shared.request(.delete, path: "/v1/chats/\(id)")
                chatStore.removeChat(id)
                SpotlightIndexer.shared.removeChat(id)
                if selectedChatId == id { selectedChatId = nil }
            } catch {
                print("[MainApp] Failed to delete chat: \(error)")
            }
        }
    }

    private func loadMoreChats() {
        isLoadingMore = true
        Task {
            do {
                let offset = chatStore.chats.count
                let response: ChatListResponse = try await APIClient.shared.request(
                    .get, path: "/v1/chats?offset=\(offset)&limit=20"
                )
                await upsertSyncedChats(response.chats)
            } catch {
                print("[MainApp] Failed to load more chats: \(error)")
            }
            isLoadingMore = false
        }
    }

    private func showMoreUserChats() {
        if visibleUserChatLimit < userChatCountForDisplayLimit {
            visibleUserChatLimit += Self.showMoreUserChatIncrement
            return
        }
        loadMoreChats()
        visibleUserChatLimit += Self.showMoreUserChatIncrement
    }

    private func pinChat(_ chat: Chat) {
        let isPinned = !(chat.isPinned ?? false)
        Task {
            try? await APIClient.shared.request(
                .patch, path: "/v1/chats/\(chat.id)",
                body: ["is_pinned": isPinned]
            ) as Data
            await loadInitialData()
        }
    }

    private func hideChat(_ id: String) {
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/chats/\(id)/hide"
            ) as Data
            chatStore.removeChat(id)
            if selectedChatId == id { selectedChatId = nil }
        }
    }

    private func renameChat(_ chat: Chat) {
        renameChatId = chat.id
        renameChatTitle = chat.displayTitle
        showRenameAlert = true
    }

    private func submitRename() {
        guard let chatId = renameChatId, !renameChatTitle.isEmpty else { return }
        Task {
            try? await APIClient.shared.request(
                .patch, path: "/v1/chats/\(chatId)",
                body: ["title": renameChatTitle]
            ) as Data
            await loadInitialData()
        }
    }

    private func unhideChat(_ id: String) {
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/chats/\(id)/unhide"
            ) as Data
            await loadInitialData()
        }
    }

    private func archiveChat(_ id: String) {
        Task {
            try? await APIClient.shared.request(
                .patch, path: "/v1/chats/\(id)",
                body: ["is_archived": true]
            ) as Data
            chatStore.removeChat(id)
            if selectedChatId == id { selectedChatId = nil }
        }
    }

    // MARK: - WebSocket

    private func connectWebSocket() {
        wsManager.connect(
            sessionId: AuthManager.nativeSessionId,
            token: authManager.webSocketToken,
            syncState: chatStore.makeSyncClientState(
                clientSuggestionsCount: syncedNewChatSuggestions.count
            )
        )
    }

    private func sendScrollPositionUpdate(chatId: String, messageId: String) {
        chatStore.updateLastVisibleMessage(chatId: chatId, messageId: messageId)
        Task {
            do {
                try await wsManager.send(
                    WSOutboundMessage(
                        type: "scroll_position_update",
                        payload: [
                            "chat_id": chatId,
                            "message_id": messageId
                        ]
                    )
                )
            } catch {
                print("[MainApp] Failed to sync scroll position chat=\(chatId.prefix(8)) message=\(messageId.prefix(8)): \(error)")
            }
        }
    }

    private func handleChatUpdate(_ notification: Notification) {
        guard let type = notification.userInfo?["type"] as? String,
              let raw = notification.userInfo?["raw"] as? Data else {
            Task { await loadInitialData() }
            return
        }
        Task { @MainActor in
            await processChatUpdate(type: type, raw: raw)
        }
    }

    private func processChatUpdate(type: String, raw: Data) async {
        do {
            switch type {
            case "new_chat_message":
                let envelope = try syncDecoder.decode(WSEnvelope<NewChatMessagePayload>.self, from: raw)
                guard let payload = envelope.payload ?? envelope.data else { return }
                await applyNewChatMessage(payload)

            case "ai_typing_started":
                let envelope = try syncDecoder.decode(WSEnvelope<AITypingStartedSyncPayload>.self, from: raw)
                guard let payload = envelope.payload ?? envelope.data else { return }
                await applyTypingStartedMetadata(payload)

            case "ai_background_response_completed":
                let envelope = try syncDecoder.decode(WSEnvelope<AIBackgroundResponseCompletedPayload>.self, from: raw)
                guard let payload = envelope.payload ?? envelope.data else { return }
                await applyAssistantCompletion(
                    chatId: payload.chatId,
                    messageId: payload.messageId,
                    userMessageId: payload.userMessageId,
                    content: payload.fullContent,
                    createdAt: nil,
                    modelName: payload.modelName,
                    category: payload.category,
                    rejectionReason: payload.rejectionReason,
                    source: "background"
                )

            case "pending_ai_response":
                let envelope = try syncDecoder.decode(WSEnvelope<PendingAIResponsePayload>.self, from: raw)
                guard let payload = envelope.payload ?? envelope.data else { return }
                await applyAssistantCompletion(
                    chatId: payload.chatId,
                    messageId: payload.messageId,
                    userMessageId: nil,
                    content: payload.content,
                    createdAt: payload.firedAt,
                    modelName: payload.modelName,
                    category: payload.category,
                    rejectionReason: nil,
                    source: "pending"
                )

            case "chat_deleted":
                let envelope = try syncDecoder.decode(WSEnvelope<ChatDeletedSyncPayload>.self, from: raw)
                guard let payload = envelope.payload ?? envelope.data else { return }
                chatStore.removeChat(payload.chatId)
                ChatKeyManager.shared.removeKey(for: payload.chatId)
                if selectedChatId == payload.chatId {
                    selectedChatId = nil
                    showNewChat = true
                }

            case "focus_mode_activated":
                let envelope = try syncDecoder.decode(WSEnvelope<FocusModeActivatedPayload>.self, from: raw)
                guard let payload = envelope.payload ?? envelope.data else { return }
                await applyFocusModeActivated(payload)

            default:
                await loadInitialData()
            }
        } catch {
            print("[MainApp] Failed to process chat update \(type): \(error)")
            await loadInitialData()
        }
    }

    private func applyNewChatMessage(_ payload: NewChatMessagePayload) async {
        await loadChatKeyIfNeeded(chatId: payload.chatId, encryptedChatKey: payload.encryptedChatKey)

        let createdAt = Self.isoString(fromUnixSeconds: payload.createdAt)
        let lastMessageAt = Self.isoString(fromUnixSeconds: payload.lastEditedOverallTimestamp ?? payload.createdAt)
        let existing = chatStore.chat(for: payload.chatId)
        var chat = Chat(
            id: payload.chatId,
            title: existing?.title,
            lastMessageAt: lastMessageAt,
            createdAt: existing?.createdAt ?? createdAt,
            updatedAt: lastMessageAt,
            isArchived: existing?.isArchived ?? false,
            isPinned: existing?.isPinned ?? false,
            appId: existing?.appId ?? "ai",
            category: existing?.category,
            icon: existing?.icon,
            chatSummary: existing?.chatSummary,
            encryptedTitle: payload.encryptedTitle ?? existing?.encryptedTitle,
            encryptedCategory: payload.encryptedCategory ?? existing?.encryptedCategory,
            encryptedIcon: existing?.encryptedIcon,
            encryptedChatSummary: existing?.encryptedChatSummary,
            encryptedChatKey: payload.encryptedChatKey ?? existing?.encryptedChatKey,
            messagesV: payload.messagesV ?? existing?.messagesV,
            titleV: payload.encryptedTitle != nil ? 1 : existing?.titleV,
            draftV: existing?.draftV,
            lastVisibleMessageId: existing?.lastVisibleMessageId,
            parentId: payload.parentId ?? existing?.parentId,
            isSubChat: payload.isSubChat ?? existing?.isSubChat,
            encryptedActiveFocusId: existing?.encryptedActiveFocusId,
            activeFocusId: existing?.activeFocusId
        )
        chat = await decryptChatMetadata(chat)
        chatStore.upsertChat(chat)

        let message = Message(
            id: payload.messageId,
            chatId: payload.chatId,
            role: MessageRole(rawValue: payload.role ?? "user") ?? .user,
            content: payload.content,
            encryptedContent: nil,
            createdAt: createdAt,
            updatedAt: nil,
            appId: payload.role == "assistant" ? (chat.category ?? chat.appId) : nil,
            isStreaming: false,
            embedRefs: nil
        )
        chatStore.appendMessage(message, to: payload.chatId)
        NativeSyncPerfLog.info("phase=newChatMessageSync chat=\(payload.chatId.prefix(8)) message=\(payload.messageId.prefix(8))")
    }

    private func applyTypingStartedMetadata(_ payload: AITypingStartedSyncPayload) async {
        await loadChatKeyIfNeeded(chatId: payload.chatId, encryptedChatKey: payload.encryptedChatKey)

        let existing = chatStore.chat(for: payload.chatId)
        let now = ISO8601DateFormatter().string(from: Date())
        var chat = Chat(
            id: payload.chatId,
            title: payload.title ?? existing?.title,
            lastMessageAt: existing?.lastMessageAt ?? now,
            createdAt: existing?.createdAt ?? now,
            updatedAt: now,
            isArchived: existing?.isArchived ?? false,
            isPinned: existing?.isPinned ?? false,
            appId: existing?.appId ?? "ai",
            category: payload.category ?? existing?.category,
            icon: payload.iconNames?.first ?? existing?.icon,
            chatSummary: existing?.chatSummary,
            encryptedTitle: existing?.encryptedTitle,
            encryptedCategory: existing?.encryptedCategory,
            encryptedIcon: existing?.encryptedIcon,
            encryptedChatSummary: existing?.encryptedChatSummary,
            encryptedChatKey: payload.encryptedChatKey ?? existing?.encryptedChatKey,
            messagesV: existing?.messagesV,
            titleV: payload.title == nil ? existing?.titleV : max(existing?.titleV ?? 0, 1),
            draftV: existing?.draftV,
            lastVisibleMessageId: existing?.lastVisibleMessageId,
            parentId: existing?.parentId,
            isSubChat: existing?.isSubChat,
            encryptedActiveFocusId: existing?.encryptedActiveFocusId,
            activeFocusId: existing?.activeFocusId
        )
        chat = await decryptChatMetadata(chat)
        chatStore.upsertChat(chat)
        NativeSyncPerfLog.info("phase=typingStartedMetadata chat=\(payload.chatId.prefix(8)) hasTitle=\(payload.title != nil) hasCategory=\(payload.category != nil)")
    }

    private func applyAssistantCompletion(
        chatId: String,
        messageId: String,
        userMessageId: String?,
        content: String,
        createdAt: Int?,
        modelName: String?,
        category: String?,
        rejectionReason: String?,
        source: String
    ) async {
        guard !chatId.isEmpty, !messageId.isEmpty, !content.isEmpty else { return }
        guard !chatStore.messages(for: chatId).contains(where: { $0.id == messageId }) else {
            NativeSyncPerfLog.info("phase=assistantCompletionSkip source=\(source) chat=\(chatId.prefix(8)) message=\(messageId.prefix(8)) reason=duplicate")
            return
        }
        guard let existingChat = chatStore.chat(for: chatId) else {
            NativeSyncPerfLog.warning("phase=assistantCompletionMissingChat source=\(source) chat=\(chatId.prefix(8))")
            await loadInitialData()
            return
        }

        let timestamp = Self.isoString(fromUnixSeconds: createdAt)
        let role: MessageRole = rejectionReason == nil ? .assistant : .system
        let rawMessage = Message(
            id: messageId,
            chatId: chatId,
            role: role,
            content: content,
            encryptedContent: nil,
            createdAt: timestamp,
            updatedAt: nil,
            appId: category ?? existingChat.category ?? existingChat.appId,
            isStreaming: false,
            embedRefs: nil,
            modelName: modelName
        )
        let message = rawMessage

        let nextMessagesV = max(existingChat.messagesV ?? 0, chatStore.messages(for: chatId).count) + 1
        let updatedChat = Chat(
            id: existingChat.id,
            title: existingChat.title,
            lastMessageAt: timestamp,
            createdAt: existingChat.createdAt,
            updatedAt: timestamp,
            isArchived: existingChat.isArchived,
            isPinned: existingChat.isPinned,
            appId: existingChat.appId,
            category: category ?? existingChat.category,
            icon: existingChat.icon,
            chatSummary: existingChat.chatSummary,
            encryptedTitle: existingChat.encryptedTitle,
            encryptedCategory: existingChat.encryptedCategory,
            encryptedIcon: existingChat.encryptedIcon,
            encryptedChatSummary: existingChat.encryptedChatSummary,
            encryptedChatKey: existingChat.encryptedChatKey,
            messagesV: nextMessagesV,
            titleV: existingChat.titleV,
            draftV: existingChat.draftV,
            lastVisibleMessageId: existingChat.lastVisibleMessageId,
            parentId: existingChat.parentId,
            isSubChat: existingChat.isSubChat,
            subChatSettings: existingChat.subChatSettings,
            budgetLimit: existingChat.budgetLimit,
            budgetSpent: existingChat.budgetSpent,
            encryptedActiveFocusId: existingChat.encryptedActiveFocusId,
            activeFocusId: existingChat.activeFocusId
        )
        chatStore.upsertChat(updatedChat)
        chatStore.appendMessage(message, to: chatId)
        NativeSyncPerfLog.info("phase=assistantCompletionApplied source=\(source) chat=\(chatId.prefix(8)) message=\(messageId.prefix(8)) role=\(role.rawValue)")
        await showAssistantNotificationIfNeeded(chat: updatedChat, message: message, source: source)

        do {
            _ = try await ChatSendPipeline().persistCompletedAssistantMessage(
                message,
                userMessageId: userMessageId,
                wsManager: wsManager,
                chatStore: chatStore
            )
        } catch {
            print("[MainApp] Failed to persist assistant completion source=\(source) chat=\(chatId.prefix(8)) message=\(messageId.prefix(8)): \(error)")
        }
    }

    private func showAssistantNotificationIfNeeded(chat: Chat, message: Message, source: String) async {
        guard source == "background" || source == "pending" else { return }
        guard message.role == .assistant else { return }
        guard scenePhase != .active else { return }
        guard selectedChatId != chat.id else { return }

        await pushManager.showChatMessageNotification(
            chatId: chat.id
        )
    }

    private func applyFocusModeActivated(_ payload: FocusModeActivatedPayload) async {
        guard let existing = chatStore.chat(for: payload.chatId) else { return }
        await loadChatKeyIfNeeded(chatId: payload.chatId, encryptedChatKey: existing.encryptedChatKey)
        guard let key = ChatKeyManager.shared.key(for: payload.chatId),
              let encryptedFocusId = try? await CryptoManager.shared.encryptContent(payload.focusId, key: key) else {
            NativeSyncPerfLog.warning("phase=focusModeActivated reason=missingKey")
            return
        }
        let updated = Chat(
            id: existing.id,
            title: existing.title,
            lastMessageAt: existing.lastMessageAt,
            createdAt: existing.createdAt,
            updatedAt: ISO8601DateFormatter().string(from: Date()),
            isArchived: existing.isArchived,
            isPinned: existing.isPinned,
            appId: existing.appId,
            category: existing.category,
            icon: existing.icon,
            chatSummary: existing.chatSummary,
            encryptedTitle: existing.encryptedTitle,
            encryptedCategory: existing.encryptedCategory,
            encryptedIcon: existing.encryptedIcon,
            encryptedChatSummary: existing.encryptedChatSummary,
            encryptedChatKey: existing.encryptedChatKey,
            messagesV: existing.messagesV,
            titleV: existing.titleV,
            draftV: existing.draftV,
            lastVisibleMessageId: existing.lastVisibleMessageId,
            parentId: existing.parentId,
            isSubChat: existing.isSubChat,
            subChatSettings: existing.subChatSettings,
            budgetLimit: existing.budgetLimit,
            budgetSpent: existing.budgetSpent,
            encryptedActiveFocusId: encryptedFocusId,
            activeFocusId: payload.focusId
        )
        chatStore.upsertChat(updated)
        chatStore.updateActiveFocus(
            chatId: payload.chatId,
            encryptedActiveFocusId: encryptedFocusId,
            activeFocusId: payload.focusId
        )
        do {
            try await wsManager.send(WSOutboundMessage(
                type: "update_encrypted_active_focus_id",
                payload: [
                    "chat_id": payload.chatId,
                    "encrypted_active_focus_id": encryptedFocusId
                ]
            ))
        } catch {
            print("[MainApp] Failed to persist focus sync metadata")
        }
    }

    private func announceActiveChat(_ chatId: String?) async {
        guard isAuthenticated else { return }
        do {
            try await ChatSendPipeline().sendSetActiveChat(chatId, wsManager: wsManager)
        } catch {
            print("[MainApp] Failed to announce active chat \(chatId?.prefix(8) ?? "nil"): \(error)")
        }
    }

    private func loadChatKeyIfNeeded(chatId: String, encryptedChatKey: String?) async {
        guard let encryptedChatKey, !ChatKeyManager.shared.hasKey(for: chatId),
              let userId = authManager.currentUser?.id,
              let masterKey = try? await CryptoManager.shared.loadMasterKey(for: userId) else {
            return
        }
        await ChatKeyManager.shared.loadChatKey(
            chatId: chatId,
            encryptedChatKey: encryptedChatKey,
            masterKey: masterKey
        )
    }

    private func handleSyncEvent(_ notification: Notification) {
        guard let type = notification.userInfo?["type"] as? String else { return }
        guard let raw = notification.userInfo?["raw"] as? Data else {
            print("[MainApp][sync] event type=\(type) missing raw payload; falling back to full load")
            Task { await loadInitialData() }
            return
        }
        let previousTask = syncProcessingTask
        syncProcessingTask = Task { @MainActor in
            await previousTask?.value
            let start = NativeSyncPerfLog.now()
            await processSyncEvent(type: type, raw: raw)
            NativeSyncPerfLog.info(
                "phase=wsSyncEvent type=\(type) rawBytes=\(raw.count) elapsedMs=\(NativeSyncPerfLog.ms(since: start))"
            )
        }
    }

    private func handleHistoryRequest(_ notification: Notification) {
        guard let raw = notification.userInfo?["raw"] as? Data else { return }
        Task { @MainActor in
            do {
                let envelope = try syncDecoder.decode(WSEnvelope<HistoryRequestPayload>.self, from: raw)
                guard let payload = envelope.payload ?? envelope.data else { return }
                await resendChatHistory(chatId: payload.chatId)
            } catch {
                print("[MainApp] Failed to decode history request: \(error)")
            }
        }
    }

    private func handlePendingDeferredSend(_ notification: Notification) {
        if notification.userInfo?["dispatchThroughActiveComposer"] as? Bool == true {
            return
        }
        guard let chatId = notification.userInfo?["chatId"] as? String,
              let content = notification.userInfo?["content"] as? String,
              let chat = chatStore.chat(for: chatId) else { return }
        Task { @MainActor in
            do {
                _ = try await ChatSendPipeline().sendUserMessage(
                    content: content,
                    in: chat,
                    existingMessages: chatStore.messages(for: chatId),
                    wsManager: wsManager,
                    chatStore: chatStore
                )
            } catch {
                print("[MainApp] Deferred upload send failed for chat \(chatId.prefix(8)): \(error)")
            }
        }
    }

    private func handleEmbedUpdate(_ notification: Notification) {
        // Forward embed updates so the active ChatView can reload its embeds.
        // The notification carries the raw WS data; ChatViewModel listens for
        // embed refresh signals via NotificationCenter.
        NotificationCenter.default.post(name: .embedRefreshNeeded, object: nil, userInfo: notification.userInfo)
    }

    private func resendChatHistory(chatId: String) async {
        let chat = chatStore.chat(for: chatId)
        var messages = chatStore.messages(for: chatId)
        guard !messages.isEmpty else {
            print("[MainApp] Cannot resend history; no messages for chat \(chatId.prefix(8))")
            return
        }
        if messages.contains(where: { ($0.content ?? "").isEmpty && $0.encryptedContent != nil }) {
            messages = await decryptHistoryMessages(messages, chatId: chatId)
        }
        guard let latestUserMessage = messages
            .filter({ $0.role == .user })
            .sorted(by: { $0.createdAt > $1.createdAt })
            .first,
            let content = latestUserMessage.content,
            !content.isEmpty else {
            print("[MainApp] Cannot resend history; missing latest user message for chat \(chatId.prefix(8))")
            return
        }

        let history = messages.map { message -> [String: Any] in
            [
                "message_id": message.id,
                "role": message.role.rawValue,
                "content": message.content ?? "",
                "category": message.appId as Any,
                "created_at": ChatSendPipeline.unixSeconds(from: message.createdAt)
            ]
        }
        let chatHasTitle = (chat?.titleV ?? 0) > 0
        var messagePayload: [String: Any] = [
            "message_id": latestUserMessage.id,
            "role": latestUserMessage.role.rawValue,
            "content": content,
            "created_at": ChatSendPipeline.unixSeconds(from: latestUserMessage.createdAt),
            "sender_name": "user",
            "chat_has_title": chatHasTitle,
            "message_history": history
        ]
        if chatHasTitle {
            messagePayload["current_chat_title"] = chat?.title
        }

        do {
            try await wsManager.send(WSOutboundMessage(
                type: "chat_message_added",
                payload: [
                    "chat_id": chatId,
                    "message": messagePayload,
                    "encrypted_chat_key": chat?.encryptedChatKey as Any
                ]
            ))
        } catch {
            print("[MainApp] Failed to resend chat history for \(chatId.prefix(8)): \(error)")
        }
    }

    private func decryptHistoryMessages(_ messages: [Message], chatId: String) async -> [Message] {
        var result: [Message] = []
        for var message in messages {
            if (message.content ?? "").isEmpty,
               let encryptedContent = message.encryptedContent,
               let decrypted = await ChatKeyManager.shared.decryptMessageContent(
                   chatId: chatId,
                   encryptedContent: encryptedContent
               ) {
                message.content = decrypted
            }
            result.append(message)
        }
        return result
    }

    private func processSyncEvent(type: String, raw: Data) async {
        do {
            switch type {
            case "phase_1_last_chat_ready":
                let start = NativeSyncPerfLog.now()
                let envelope = try syncDecoder.decode(WSEnvelope<Phase1SyncPayload>.self, from: raw)
                guard let payload = envelope.payload ?? envelope.data else { return }
                await upsertSyncedChats(([payload.chatDetails].compactMap { $0 }) + (payload.recentChatMetadata ?? []))
                await updateSyncedSuggestions(payload.newChatSuggestions ?? [])
                NativeSyncPerfLog.info(
                    "phase=phase1a recent=\(payload.recentChatMetadata?.count ?? 0) suggestions=\(payload.newChatSuggestions?.count ?? 0) processMs=\(NativeSyncPerfLog.ms(since: start))"
                )

            case "phase_1b_chat_content_ready", "background_message_sync":
                let start = NativeSyncPerfLog.now()
                let envelope = try syncDecoder.decode(WSEnvelope<PhaseContentSyncPayload>.self, from: raw)
                guard let payload = envelope.payload ?? envelope.data else { return }
                if let embedKeys = payload.embedKeys, !embedKeys.isEmpty {
                    EmbedKeyManager.shared.store(embedKeys, source: type)
                    OfflineStore.shared.persistEmbedKeys(embedKeys)
                }
                var messagesByChat: [String: [Message]] = [:]
                for item in payload.chats ?? [] {
                    guard let messages = item.messages, !messages.isEmpty else { continue }
                    messagesByChat[item.chatId] = messages
                }
                var embedsByChat: [String: [EmbedRecord]] = [:]
                var duplicateEmbedIdsByChat: [String: Int] = [:]
                if let embeds = payload.embeds, !embeds.isEmpty {
                    var chatIdsByHash: [String: String] = [:]
                    for item in payload.chats ?? [] {
                        chatIdsByHash[sha256Hex(item.chatId)] = item.chatId
                    }
                    let grouped = Dictionary(grouping: embeds) { embed in
                        embed.rawData?["chat_id"]?.value as? String
                            ?? embed.rawData?["chatId"]?.value as? String
                            ?? chatIdsByHash[embed.hashedChatId ?? ""]
                            ?? ""
                    }
                    for (chatId, chatEmbeds) in grouped where !chatId.isEmpty {
                        embedsByChat[chatId, default: []].append(contentsOf: chatEmbeds)
                    }
                    for item in payload.chats ?? [] {
                        let messages = messagesByChat[item.chatId] ?? chatStore.messages(for: item.chatId)
                        let relatedEmbeds = embedsForChat(item.chatId, messages: messages, from: embeds)
                        embedsByChat[item.chatId, default: []].append(contentsOf: relatedEmbeds)
                    }
                }
                let dedupedEmbedsByChat = embedsByChat.mapValues { embeds in
                    EmbedRecord.deduplicatedById(
                        embeds,
                        context: "sync.\(type)",
                        duplicateReporter: { duplicateIds in
                            guard !duplicateIds.isEmpty else { return }
                            duplicateEmbedIdsByChat["chatsWithDuplicates", default: 0] += 1
                            duplicateEmbedIdsByChat["duplicateIds", default: 0] += duplicateIds.count
                            duplicateEmbedIdsByChat["duplicateEntries", default: 0] += duplicateIds.values.reduce(0) { $0 + $1 - 1 }
                        }
                    )
                }
                if !duplicateEmbedIdsByChat.isEmpty {
                    NativeSyncPerfLog.warning(
                        "phase=embedDedup context=sync.\(type) chatsWithDuplicates=\(duplicateEmbedIdsByChat["chatsWithDuplicates"] ?? 0) duplicateIds=\(duplicateEmbedIdsByChat["duplicateIds"] ?? 0) duplicateEntries=\(duplicateEmbedIdsByChat["duplicateEntries"] ?? 0)"
                    )
                }
                if type == "background_message_sync" {
                    enqueueBackgroundSyncedContent(
                        messagesByChat: messagesByChat,
                        embedsByChat: dedupedEmbedsByChat
                    )
                } else {
                    chatStore.applySyncedContent(
                        messagesByChat: messagesByChat,
                        embedsByChat: dedupedEmbedsByChat
                    )
                }
                NativeSyncPerfLog.info(
                    "phase=phase1bContent chats=\(payload.chats?.count ?? 0) messages=\(messagesByChat.values.reduce(0) { $0 + $1.count }) embeds=\(payload.embeds?.count ?? 0) relatedEmbedChats=\(dedupedEmbedsByChat.count) embedKeys=\(payload.embedKeys?.count ?? 0) decrypt=deferred processMs=\(NativeSyncPerfLog.ms(since: start))"
                )

            case "phase_2_last_20_chats_ready", "phase_3_last_100_chats_ready", "sync_metadata_chats_response":
                let start = NativeSyncPerfLog.now()
                let envelope = try syncDecoder.decode(WSEnvelope<PhaseBulkSyncPayload>.self, from: raw)
                guard let payload = envelope.payload ?? envelope.data else { return }
                totalChatCount = payload.totalChatCount ?? totalChatCount
                await upsertSyncedChats((payload.chats ?? []).compactMap(\.chatDetails))
                await updateSyncedSuggestions(payload.newChatSuggestions ?? [])
                NativeSyncPerfLog.info(
                    "phase=metadataSync type=\(type) chats=\(payload.chats?.count ?? 0) total=\(totalChatCount) processMs=\(NativeSyncPerfLog.ms(since: start))"
                )

            case "phased_sync_complete":
                if !isBackgroundSyncFlushInProgress {
                    backgroundSyncFlushTask?.cancel()
                    backgroundSyncFlushTask = nil
                    await flushBackgroundSyncedContent(reason: "syncComplete")
                }
                syncBridge?.startOfflinePrefetchIfEligible(reason: "startupSyncComplete")

            default:
                await loadInitialData()
            }
        } catch {
            print("[MainApp] Failed to process sync event \(type): \(error)")
        }
    }

    private func enqueueBackgroundSyncedContent(
        messagesByChat: [String: [Message]],
        embedsByChat: [String: [EmbedRecord]]
    ) {
        pendingBackgroundSyncContent.merge(
            messagesByChat: messagesByChat,
            embedsByChat: embedsByChat
        )
        backgroundSyncFlushTask?.cancel()
        NativeSyncPerfLog.info(
            "phase=backgroundSyncBuffered chats=\(messagesByChat.count) messages=\(messagesByChat.values.reduce(0) { $0 + $1.count }) embedChats=\(embedsByChat.count) embeds=\(embedsByChat.values.reduce(0) { $0 + $1.count }) pendingChats=\(pendingBackgroundSyncContent.chatCount)"
        )
        if !isBackgroundSyncFlushInProgress {
            scheduleBackgroundSyncFlush(delay: Self.backgroundSyncFlushDelayNs, reason: "debounced")
        }
    }

    private func scheduleBackgroundSyncFlush(delay: UInt64, reason: String) {
        backgroundSyncFlushTask?.cancel()
        backgroundSyncFlushTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: delay)
            guard !Task.isCancelled else { return }
            await flushBackgroundSyncedContent(reason: reason)
        }
    }

    private func flushBackgroundSyncedContent(reason: String) async {
        guard !pendingBackgroundSyncContent.isEmpty, !isBackgroundSyncFlushInProgress else { return }
        isBackgroundSyncFlushInProgress = true
        let start = NativeSyncPerfLog.now()
        let (messagesByChat, embedsByChat) = pendingBackgroundSyncContent.drain()
        var chatIds = Array(Set(messagesByChat.keys).union(embedsByChat.keys))
        if let selectedChatId, let selectedIndex = chatIds.firstIndex(of: selectedChatId) {
            chatIds.remove(at: selectedIndex)
            chatIds.insert(selectedChatId, at: 0)
        }
        let chunks = backgroundSyncChunks(chatIds: chatIds, embedsByChat: embedsByChat)
        for chunk in chunks {
            guard isAuthenticated else {
                isBackgroundSyncFlushInProgress = false
                return
            }
            if shouldDeferBackgroundSyncChunk(chunk) {
                try? await Task.sleep(nanoseconds: Self.backgroundSyncForegroundPauseNs)
            }
            let chunkMessages = messagesByChat.filter { chunk.contains($0.key) }
            let chunkEmbeds = embedsByChat.filter { chunk.contains($0.key) }
            chatStore.applySyncedContent(
                messagesByChat: chunkMessages,
                embedsByChat: chunkEmbeds
            )
            await Task.yield()
            try? await Task.sleep(nanoseconds: Self.backgroundSyncInterChunkPauseNs)
        }
        NativeSyncPerfLog.info(
            "phase=backgroundSyncFlush reason=\(reason) chats=\(messagesByChat.count) messages=\(messagesByChat.values.reduce(0) { $0 + $1.count }) embedChats=\(embedsByChat.count) embeds=\(embedsByChat.values.reduce(0) { $0 + $1.count }) elapsedMs=\(NativeSyncPerfLog.ms(since: start))"
        )
        isBackgroundSyncFlushInProgress = false
        backgroundSyncFlushTask = nil
        if !pendingBackgroundSyncContent.isEmpty {
            scheduleBackgroundSyncFlush(delay: Self.backgroundSyncInterChunkPauseNs, reason: "followUp")
        }
    }

    private func shouldDeferBackgroundSyncChunk(_ chatIds: [String]) -> Bool {
        guard Date().timeIntervalSince(lastForegroundInteractionAt) < Self.foregroundInteractionGraceSeconds else {
            return false
        }
        if showSettings {
            return true
        }
        guard let selectedChatId else { return false }
        return !chatIds.contains(selectedChatId)
    }

    private func backgroundSyncChunks(
        chatIds: [String],
        embedsByChat: [String: [EmbedRecord]]
    ) -> [[String]] {
        var chunks: [[String]] = []
        var current: [String] = []
        var currentEmbedCount = 0

        for chatId in chatIds {
            let embedCount = embedsByChat[chatId]?.count ?? 0
            let exceedsChatLimit = current.count >= Self.backgroundSyncFlushChunkSize
            let exceedsEmbedLimit = !current.isEmpty &&
                currentEmbedCount + embedCount > Self.backgroundSyncMaxEmbedsPerChunk
            if exceedsChatLimit || exceedsEmbedLimit {
                chunks.append(current)
                current = []
                currentEmbedCount = 0
            }
            current.append(chatId)
            currentEmbedCount += embedCount
        }

        if !current.isEmpty {
            chunks.append(current)
        }
        return chunks
    }

    private func embedsForChat(_ chatId: String, messages: [Message]? = nil, from embeds: [EmbedRecord]) -> [EmbedRecord] {
        let messages = messages ?? chatStore.messages(for: chatId)
        let referencedIds = Set(messages.flatMap { $0.embedRefs?.map(\.id) ?? [] })
        guard !referencedIds.isEmpty else {
            let hashedChatId = sha256Hex(chatId)
            let hashedEmbeds = embeds.filter { $0.hashedChatId == hashedChatId }
            return hashedEmbeds.isEmpty ? embeds : hashedEmbeds
        }
        var includedIds = referencedIds
        var changed = true
        while changed {
            changed = false
            for embed in embeds {
                let referencesIncludedParent = embed.parentEmbedId.map { includedIds.contains($0) } ?? false
                let referencesIncludedChild = !Set(embed.childEmbedIds).isDisjoint(with: includedIds)
                if (referencesIncludedParent || referencesIncludedChild), includedIds.insert(embed.id).inserted {
                    changed = true
                }
            }
        }
        return embeds.filter { embed in
            includedIds.contains(embed.id) ||
            (embed.parentEmbedId.map { includedIds.contains($0) } ?? false) ||
            !Set(embed.childEmbedIds).isDisjoint(with: includedIds)
        }
    }

    private func sha256Hex(_ value: String) -> String {
        let digest = SHA256.hash(data: Data(value.utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    private static func isoString(fromUnixSeconds seconds: Int?) -> String {
        guard let seconds else {
            return ISO8601DateFormatter().string(from: Date())
        }
        return ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: TimeInterval(seconds)))
    }

    private var syncDecoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    private func upsertSyncedChats(_ chats: [Chat]) async {
        guard !chats.isEmpty else { return }
        let start = NativeSyncPerfLog.now()
        if let userId = authManager.currentUser?.id {
            await loadChatKeys(chats: chats, userId: userId)
        }

        var indexedChats: [Chat] = []
        for var chat in chats {
            chat = await decryptChatMetadata(chat)
            indexedChats.append(chat)
        }
        chatStore.upsertChats(indexedChats)
        let searchableUserChats = chatStore.sortedChats.filter { publicChatGroup(for: $0.id) == nil }
        SpotlightIndexer.shared.scheduleIndexChats(searchableUserChats, reason: "syncMetadata")
        NativeSyncPerfLog.info(
            "phase=upsertSyncedChats chats=\(chats.count) elapsedMs=\(NativeSyncPerfLog.ms(since: start))"
        )
    }

    private func decryptChatMetadata(_ chat: Chat) async -> Chat {
        var decrypted = chat
        guard ChatKeyManager.shared.hasKey(for: decrypted.id) else {
            if NativeSyncPerfLog.verboseCrypto {
                print("[MainApp][decrypt] chat=\(decrypted.id.prefix(8)) missing chat key; encryptedTitle=\(decrypted.encryptedTitle != nil) encryptedCategory=\(decrypted.encryptedCategory != nil) encryptedIcon=\(decrypted.encryptedIcon != nil) encryptedSummary=\(decrypted.encryptedChatSummary != nil)")
            }
            return decrypted
        }
        if decrypted.title == nil,
           let encryptedTitle = decrypted.encryptedTitle,
           let title = await ChatKeyManager.shared.decryptChatField(
               chatId: decrypted.id,
               encryptedValue: encryptedTitle,
               fieldName: "encrypted_title"
        ) {
            decrypted.title = title
            if NativeSyncPerfLog.verboseCrypto {
                print("[MainApp][decrypt] chat=\(decrypted.id.prefix(8)) title ok")
            }
        } else if decrypted.title == nil, decrypted.encryptedTitle != nil {
            if NativeSyncPerfLog.verboseCrypto {
                print("[MainApp][decrypt] chat=\(decrypted.id.prefix(8)) title missing after decrypt attempt")
            }
        }
        if decrypted.category == nil,
           let encryptedCategory = decrypted.encryptedCategory,
           let category = await ChatKeyManager.shared.decryptChatField(
               chatId: decrypted.id,
               encryptedValue: encryptedCategory,
               fieldName: "encrypted_category"
        ) {
            decrypted.category = category
            if NativeSyncPerfLog.verboseCrypto {
                print("[MainApp][decrypt] chat=\(decrypted.id.prefix(8)) category ok")
            }
        } else if decrypted.category == nil, decrypted.encryptedCategory != nil {
            if NativeSyncPerfLog.verboseCrypto {
                print("[MainApp][decrypt] chat=\(decrypted.id.prefix(8)) category missing after decrypt attempt")
            }
        }
        if decrypted.icon == nil,
           let encryptedIcon = decrypted.encryptedIcon,
           let icon = await ChatKeyManager.shared.decryptChatField(
               chatId: decrypted.id,
               encryptedValue: encryptedIcon,
               fieldName: "encrypted_icon"
        ) {
            decrypted.icon = icon
            if NativeSyncPerfLog.verboseCrypto {
                print("[MainApp][decrypt] chat=\(decrypted.id.prefix(8)) icon ok")
            }
        } else if decrypted.icon == nil, decrypted.encryptedIcon != nil {
            if NativeSyncPerfLog.verboseCrypto {
                print("[MainApp][decrypt] chat=\(decrypted.id.prefix(8)) icon missing after decrypt attempt")
            }
        }
        if decrypted.chatSummary == nil,
           let encryptedSummary = decrypted.encryptedChatSummary,
           let summary = await ChatKeyManager.shared.decryptChatField(
               chatId: decrypted.id,
               encryptedValue: encryptedSummary,
               fieldName: "encrypted_chat_summary"
        ) {
            decrypted.chatSummary = summary
            if NativeSyncPerfLog.verboseCrypto {
                print("[MainApp][decrypt] chat=\(decrypted.id.prefix(8)) summary ok")
            }
        } else if decrypted.chatSummary == nil, decrypted.encryptedChatSummary != nil {
            if NativeSyncPerfLog.verboseCrypto {
                print("[MainApp][decrypt] chat=\(decrypted.id.prefix(8)) summary missing after decrypt attempt")
            }
        }
        if decrypted.activeFocusId == nil,
           let encryptedActiveFocusId = decrypted.encryptedActiveFocusId,
           let activeFocusId = await ChatKeyManager.shared.decryptChatField(
                chatId: decrypted.id,
                encryptedValue: encryptedActiveFocusId,
                fieldName: "encrypted_active_focus_id"
        ) {
            decrypted.activeFocusId = activeFocusId
        }
        return decrypted
    }

    private func updateSyncedSuggestions(_ suggestions: [SyncedNewChatSuggestion]) async {
        guard !suggestions.isEmpty, let userId = authManager.currentUser?.id else { return }
        guard let masterKey = try? await CryptoManager.shared.loadMasterKey(for: userId) else { return }

        var decrypted: [NewChatSuggestionsView.ChatSuggestion] = []
        for suggestion in suggestions {
            if let text = suggestion.text {
                decrypted.append(suggestion.chatSuggestion(text: text))
                continue
            }
            guard let encrypted = suggestion.encryptedSuggestion,
                  let text = try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: masterKey) else {
                continue
            }
            decrypted.append(suggestion.chatSuggestion(text: text))
        }

        if !decrypted.isEmpty {
            syncedNewChatSuggestions = decrypted
        }
    }
}

@MainActor
private struct MainAppExternalEventModifier: ViewModifier {
    @ObservedObject var deepLinkHandler: DeepLinkHandler

    let onDeepLink: @MainActor (URL) -> Void
    let onQuickAction: @MainActor (AppQuickAction) -> Void
    let onNewChatDeepLink: @MainActor () -> Void
    let onSearchDeepLink: @MainActor () -> Void

    func body(content: Content) -> some View {
        content
            .onReceive(NotificationCenter.default.publisher(for: .deepLinkReceived)) { notification in
                if let url = notification.userInfo?["url"] as? URL {
                    onDeepLink(url)
                }
            }
            .onReceive(NotificationCenter.default.publisher(for: .quickActionReceived)) { notification in
                if let rawAction = notification.userInfo?["action"] as? String,
                   let action = AppQuickAction(rawValue: rawAction) {
                    onQuickAction(action)
                }
            }
            .onChange(of: deepLinkHandler.pendingNewChat) { _, shouldOpen in
                if shouldOpen {
                    onNewChatDeepLink()
                }
            }
            .onChange(of: deepLinkHandler.pendingSearch) { _, shouldOpen in
                if shouldOpen {
                    onSearchDeepLink()
                }
            }
    }
}

private struct PendingSyncedContent {
    private(set) var messagesByChat: [String: [Message]] = [:]
    private var embedsByChat: [String: [String: EmbedRecord]] = [:]

    var isEmpty: Bool {
        messagesByChat.isEmpty && embedsByChat.isEmpty
    }

    var chatCount: Int {
        Set(messagesByChat.keys).union(embedsByChat.keys).count
    }

    mutating func merge(
        messagesByChat incomingMessages: [String: [Message]],
        embedsByChat incomingEmbeds: [String: [EmbedRecord]]
    ) {
        for (chatId, messages) in incomingMessages where !messages.isEmpty {
            var mergedById: [String: Message] = [:]
            for message in messagesByChat[chatId] ?? [] {
                mergedById[message.id] = message
            }
            for message in messages {
                mergedById[message.id] = message
            }
            messagesByChat[chatId] = mergedById.values.sorted { $0.createdAt < $1.createdAt }
        }

        for (chatId, embeds) in incomingEmbeds where !embeds.isEmpty {
            var mergedById = embedsByChat[chatId] ?? [:]
            for embed in embeds {
                mergedById[embed.id] = embed
            }
            embedsByChat[chatId] = mergedById
        }
    }

    mutating func drain() -> (messagesByChat: [String: [Message]], embedsByChat: [String: [EmbedRecord]]) {
        let drainedMessages = messagesByChat
        let drainedEmbeds = embedsByChat.mapValues { Array($0.values) }
        messagesByChat = [:]
        embedsByChat = [:]
        return (drainedMessages, drainedEmbeds)
    }
}

private extension Array {
    func chunked(into size: Int) -> [[Element]] {
        guard size > 0 else { return [self] }
        return stride(from: 0, to: count, by: size).map {
            Array(self[$0..<Swift.min($0 + size, count)])
        }
    }
}

private struct WSEnvelope<Payload: Decodable>: Decodable {
    let payload: Payload?
    let data: Payload?
}

private struct NewChatMessagePayload: Decodable {
    let chatId: String
    let messageId: String
    let content: String
    let role: String?
    let createdAt: Int?
    let messagesV: Int?
    let lastEditedOverallTimestamp: Int?
    let encryptedChatKey: String?
    let encryptedTitle: String?
    let encryptedCategory: String?
    let parentId: String?
    let isSubChat: Bool?
}

private struct AITypingStartedSyncPayload: Decodable {
    let chatId: String
    let messageId: String?
    let title: String?
    let category: String?
    let iconNames: [String]?
    let encryptedChatKey: String?
}

private struct AIBackgroundResponseCompletedPayload: Decodable {
    let chatId: String
    let messageId: String
    let userMessageId: String?
    let taskId: String?
    let fullContent: String
    let modelName: String?
    let category: String?
    let interruptedBySoftLimit: Bool?
    let interruptedByRevocation: Bool?
    let rejectionReason: String?
}

private struct PendingAIResponsePayload: Decodable {
    let chatId: String
    let messageId: String
    let content: String
    let userId: String?
    let firedAt: Int?
    let modelName: String?
    let category: String?
}

private struct ChatDeletedSyncPayload: Decodable {
    let chatId: String
}

private struct FocusModeActivatedPayload: Decodable {
    let chatId: String
    let focusId: String
}

private struct Phase1SyncPayload: Decodable {
    let chatDetails: Chat?
    let recentChatMetadata: [Chat]?
    let newChatSuggestions: [SyncedNewChatSuggestion]?
}

private struct PhaseBulkSyncPayload: Decodable {
    let chats: [PhaseChatItem]?
    let totalChatCount: Int?
    let newChatSuggestions: [SyncedNewChatSuggestion]?
}

private struct PhaseContentSyncPayload: Decodable {
    let chats: [PhaseChatContentItem]?
    let embeds: [EmbedRecord]?
    let embedKeys: [EmbedKeyRecord]?

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        chats = try container.decodeIfPresent([PhaseChatContentItem].self, forKey: .chats)
        do {
            embeds = try container.decodeIfPresent([EmbedRecord].self, forKey: .embeds) ?? []
        } catch {
            print("[MainApp][sync][decode] embeds failed: \(error)")
            embeds = []
        }
        do {
            embedKeys = try container.decodeIfPresent([EmbedKeyRecord].self, forKey: .embedKeys) ?? []
        } catch {
            print("[MainApp][sync][decode] embed_keys failed: \(error)")
            embedKeys = []
        }
    }

    private enum CodingKeys: String, CodingKey {
        case chats
        case embeds
        case embedKeys
    }
}

private struct HistoryRequestPayload: Decodable {
    let chatId: String
    let reason: String?

    private enum CodingKeys: String, CodingKey {
        case chatId
        case reason
    }
}

private struct PhaseChatItem: Decodable {
    let chatDetails: Chat?
}

private struct PhaseChatContentItem: Decodable {
    let chatId: String
    let messages: [Message]?

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        chatId = try container.decode(String.self, forKey: .chatId)

        if let decodedMessages = try? container.decodeIfPresent([Message].self, forKey: .messages) {
            messages = decodedMessages
            return
        }

        let rawMessages = (try? container.decodeIfPresent([String].self, forKey: .messages)) ?? []
        let messageDecoder = JSONDecoder()
        messageDecoder.keyDecodingStrategy = .convertFromSnakeCase
        messages = rawMessages.compactMap { raw in
            guard let data = raw.data(using: .utf8) else { return nil }
            return try? messageDecoder.decode(Message.self, from: data)
        }
    }

    private enum CodingKeys: String, CodingKey {
        case chatId
        case messages
    }
}

private struct SyncedNewChatSuggestion: Decodable {
    let id: String?
    let text: String?
    let encryptedSuggestion: String?
    let appId: String?
    let category: String?
    let icon: String?

    func chatSuggestion(text: String) -> NewChatSuggestionsView.ChatSuggestion {
        NewChatSuggestionsView.ChatSuggestion(
            id: id ?? encryptedSuggestion ?? text,
            text: text,
            appId: appId,
            category: category,
            icon: icon
        )
    }
}

// MARK: - Web app header

struct OpenMatesWebHeader: View {
    let isAuthenticated: Bool
    let isChatsPanelOpen: Bool
    let isSettingsOpen: Bool
    let profileUserId: String?
    let profileImageUrl: String?
    let onToggleChats: () -> Void
    let onNewChat: () -> Void
    let onShareChat: () -> Void
    let canShareChat: Bool
    let onOpenSettings: () -> Void
    let onOpenAuth: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: .spacing4) {
            if !isChatsPanelOpen {
                Button(action: onToggleChats) {
                    // Web: uses the same branded icon treatment as the top-right settings affordance.
                    WebHamburgerIcon(isOpen: isChatsPanelOpen)
                        .foregroundStyle(LinearGradient.primary)
                        .frame(width: 25, height: 25)
                }
                .buttonStyle(.plain)
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
                .accessibilityIdentifier("sidebar-toggle")
                .accessibilityLabel(LocalizationManager.shared.text("header.toggle_menu"))
            }

            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 0) {
                    // Web: "Open" uses var(--color-primary) gradient as text color
                    Text("Open")
                        .font(.omH3)
                        .fontWeight(.bold)
                        .foregroundStyle(LinearGradient.primary)

                    Text("Mates")
                        .font(.omH3)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.grey100)
                }

                Text(AppStrings.signupVersionTitle)
                    .font(.omXs)
                    .foregroundStyle(Color.grey60)
                    .lineLimit(1)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("OpenMates, \(AppStrings.signupVersionTitle)")

            Spacer(minLength: .spacing4)

            if !isAuthenticated {
                Button(action: onOpenAuth) {
                    Text(AppStrings.signup)
                        .font(.omP)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.fontButton)
                        .lineLimit(1)
                        .padding(.horizontal, .spacing8)
                        .padding(.vertical, .spacing4)
                        .background(Color.buttonPrimary)
                        .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("login-signup-button")
                .accessibilityLabel(AppStrings.signup)
            }

            Button(action: onOpenSettings) {
                // Web: settings affordance changes into the close affordance while the panel is open.
                headerSettingsIcon
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("settings-button")
            .accessibilityLabel(isSettingsOpen ? AppStrings.close : AppStrings.settings)
        }
        .padding(.horizontal, .spacing10)
        .padding(.top, .spacing5)
        .padding(.bottom, .spacing3)
        .background(Color.grey0)
    }

    @ViewBuilder
    private var headerSettingsIcon: some View {
        if isSettingsOpen {
            Icon("close", size: 25)
                .foregroundStyle(LinearGradient.primary)
                .frame(width: 38, height: 38)
        } else if isAuthenticated, let profileImageUrl = effectiveProfileImageUrl {
            AuthenticatedProfileImage(urlString: profileImageUrl) {
                Icon("settings", size: 22)
                    .foregroundStyle(LinearGradient.primary)
                    .frame(width: 38, height: 38)
                    .background(Color.grey10)
            }
            .frame(width: 38, height: 38)
            .clipShape(Circle())
        } else {
            Icon("settings", size: 22)
                .foregroundStyle(LinearGradient.primary)
                .frame(width: 38, height: 38)
                .background(Color.grey10)
                .clipShape(Circle())
        }
    }

    private var effectiveProfileImageUrl: String? {
        if let profileImageUrl,
           !profileImageUrl.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return profileImageUrl
        }
        guard let profileUserId,
              !profileUserId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              let encodedUserId = profileUserId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) else {
            return nil
        }
        return "/v1/users/\(encodedUserId)/profile-image"
    }
}

struct AuthenticatedProfileImage<Fallback: View>: View {
    let urlString: String
    @ViewBuilder let fallback: () -> Fallback

    @State private var imageData: Data?

    var body: some View {
        Group {
            if let image = platformImage {
                image
                    .resizable()
                    .scaledToFill()
            } else {
                fallback()
            }
        }
        .task(id: urlString) {
            await loadImage()
        }
    }

    private var platformImage: Image? {
        guard let imageData else { return nil }
        #if os(iOS)
        guard let image = UIImage(data: imageData) else { return nil }
        return Image(uiImage: image)
        #elseif os(macOS)
        guard let image = NSImage(data: imageData) else { return nil }
        return Image(nsImage: image)
        #else
        return nil
        #endif
    }

    private func loadImage() async {
        let trimmed = urlString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            imageData = nil
            return
        }
        if let cachedData = await ProfileImageRequestCache.shared.cachedData(for: trimmed) {
            imageData = cachedData
            return
        }
        guard await ProfileImageRequestCache.shared.shouldAttempt(trimmed) else {
            imageData = nil
            return
        }

        do {
            let data: Data
            if let absoluteURL = URL(string: trimmed), absoluteURL.scheme != nil {
                let (downloadedData, response) = try await URLSession.shared.data(from: absoluteURL)
                guard let httpResponse = response as? HTTPURLResponse,
                      (200...299).contains(httpResponse.statusCode) else {
                    throw APIError.invalidResponse
                }
                data = downloadedData
            } else {
                data = try await APIClient.shared.request(.get, path: trimmed)
            }
            imageData = data
            await ProfileImageRequestCache.shared.recordSuccess(data, for: trimmed)
        } catch {
            imageData = nil
            await ProfileImageRequestCache.shared.recordFailure(for: trimmed)
            print("[ProfileImage] failed to load profile image url=\(trimmed) error=\(error.localizedDescription)")
        }
    }
}

private actor ProfileImageRequestCache {
    static let shared = ProfileImageRequestCache()

    private let failedRetryDelay: TimeInterval = 300
    private var cachedDataByUrl: [String: Data] = [:]
    private var lastFailureByUrl: [String: Date] = [:]

    func cachedData(for url: String) -> Data? {
        cachedDataByUrl[url]
    }

    func shouldAttempt(_ url: String) -> Bool {
        guard let lastFailure = lastFailureByUrl[url] else { return true }
        return Date().timeIntervalSince(lastFailure) > failedRetryDelay
    }

    func recordSuccess(_ data: Data, for url: String) {
        cachedDataByUrl[url] = data
        lastFailureByUrl[url] = nil
    }

    func recordFailure(for url: String) {
        lastFailureByUrl[url] = Date()
    }
}

#if os(macOS)
private struct MacWindowTitleUpdater: NSViewRepresentable {
    let title: String

    func makeNSView(context: Context) -> NSView {
        let view = NSView(frame: .zero)
        DispatchQueue.main.async {
            updateWindowTitle(for: view)
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async {
            updateWindowTitle(for: nsView)
        }
    }

    private func updateWindowTitle(for view: NSView) {
        guard let window = view.window, window.title != title else { return }
        window.title = title
    }
}
#endif

private struct WebHamburgerIcon: View {
    let isOpen: Bool

    var body: some View {
        VStack(spacing: .spacing2) {
            Capsule()
                .frame(width: 22, height: 2)
                .rotationEffect(.degrees(isOpen ? 45 : 0))
                .offset(y: isOpen ? 7 : 0)
            Capsule()
                .frame(width: 22, height: 2)
                .opacity(isOpen ? 0 : 1)
            Capsule()
                .frame(width: 22, height: 2)
                .rotationEffect(.degrees(isOpen ? -45 : 0))
                .offset(y: isOpen ? -7 : 0)
        }
        .animation(.easeInOut(duration: 0.18), value: isOpen)
    }
}

private struct WebMenuDotsIcon: View {
    var body: some View {
        HStack(spacing: .spacing1) {
            Circle().frame(width: 4, height: 4)
            Circle().frame(width: 4, height: 4)
            Circle().frame(width: 4, height: 4)
        }
        .foregroundStyle(Color.fontPrimary)
        .frame(width: 22, height: 22)
    }
}

private struct WebHeaderIconButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(Color.fontPrimary)
            .frame(width: 34, height: 34)
            .background(configuration.isPressed ? Color.grey10 : Color.clear)
            .clipShape(RoundedRectangle(cornerRadius: .radius3))
    }
}

// MARK: - Inline new chat welcome screen
// Shown for ALL users (authenticated and unauthenticated) when no chat is selected.
// Matches the web app's ActiveChat.svelte showWelcome state.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/ActiveChat.svelte (showWelcome state)
//          frontend/packages/ui/src/components/DailyInspirationBanner.svelte
//          frontend/packages/ui/src/components/NewChatSuggestions.svelte
// CSS:     ActiveChat.svelte <style> — .welcome-text, .new-chat-cta-button,
//          .daily-inspiration-area, .center-content, .message-input-action-row
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

struct WelcomeChatCardData: Identifiable, Equatable {
    let id: String
    let title: String
    let summary: String?
    let category: String
    let iconName: String
    let isPinned: Bool
}

@MainActor
enum WelcomeScreenState {
    static let recentChatLimit = 10

    static func shouldShowWelcomeNewChatCTA(inputText: String) -> Bool {
        false
    }

    static func shouldShowInFieldSendButton(inputText: String) -> Bool {
        !inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    static func shouldHideMobileNewChatLabel(isCompact: Bool) -> Bool {
        isCompact
    }

    static func isPublicChat(_ chatId: String) -> Bool {
        chatId.hasPrefix("demo-") ||
        chatId.hasPrefix("legal-") ||
        chatId.hasPrefix("example-") ||
        chatId.hasPrefix("announcements-")
    }

    static func resumeChat(from chats: [Chat], lastOpened: String?) -> Chat? {
        guard let lastOpened, !lastOpened.isEmpty, lastOpened != "/chat/new", !isPublicChat(lastOpened) else {
            return nil
        }
        return chats.first { $0.id == lastOpened && $0.isArchived != true }
    }

    static func recentChats(from chats: [Chat], excluding resumeChatId: String?) -> [Chat] {
        chats
            .filter { chat in
                chat.isArchived != true &&
                chat.id != resumeChatId &&
                !isPublicChat(chat.id)
            }
            .sorted { lhs, rhs in
                (lhs.lastMessageAt ?? lhs.updatedAt ?? lhs.createdAt) >
                (rhs.lastMessageAt ?? rhs.updatedAt ?? rhs.createdAt)
            }
            .prefix(recentChatLimit - (resumeChatId == nil ? 0 : 1))
            .map { $0 }
    }

    static func cardData(for chat: Chat) -> WelcomeChatCardData {
        let category = chat.category ?? category(for: chat)
        return WelcomeChatCardData(
            id: chat.id,
            title: chat.displayTitle,
            summary: chat.chatSummary ?? summary(for: chat.id),
            category: category,
            iconName: chat.icon ?? cardIconName(for: chat),
            isPinned: chat.isPinned == true && !isPublicChat(chat.id)
        )
    }

    private static func category(for chat: Chat) -> String {
        switch chat.id {
        case "demo-for-everyone",
             "demo-for-developers",
             "demo-who-develops-openmates",
             "announcements-introducing-openmates-v09":
            return "openmates_official"
        case "example-beautiful-single-page-html":
            return "software_development"
        case "example-artemis-ii-mission":
            return "science"
        case "example-eu-chat-control-law":
            return "legal_law"
        case "example-gigantic-airplanes",
             "example-flights-berlin-bangkok",
             "example-creativity-drawing-meetups-berlin":
            return "general_knowledge"
        default:
            return "general_knowledge"
        }
    }

    private static func cardIconName(for chat: Chat) -> String {
        switch chat.id {
        case "demo-for-everyone":
            return "hand"
        case "demo-for-developers":
            return "code"
        case "demo-who-develops-openmates",
             "announcements-introducing-openmates-v09":
            return "shield-check"
        case "example-beautiful-single-page-html":
            return "code"
        case "example-artemis-ii-mission":
            return "rocket"
        case "example-eu-chat-control-law":
            return "shield"
        case "example-gigantic-airplanes",
             "example-flights-berlin-bangkok":
            return "plane"
        case "example-creativity-drawing-meetups-berlin":
            return "pencil"
        default:
            return CategoryMapping.lucideIconName(for: category(for: chat))
        }
    }

    private static func summary(for chatId: String) -> String? {
        switch chatId {
        case "demo-for-everyone":
            return AppStrings.demoForEveryoneDescription
        case "demo-for-developers":
            return AppStrings.demoForDevelopersDescription
        case "demo-who-develops-openmates":
            return AppStrings.demoWhoDevDescription
        case "announcements-introducing-openmates-v09":
            return AppStrings.demoAnnouncementsV09Description
        case "example-gigantic-airplanes":
            return AppStrings.exampleGiganticAirplanesSummary
        case "example-artemis-ii-mission":
            return AppStrings.exampleArtemisMissionSummary
        case "example-beautiful-single-page-html":
            return AppStrings.exampleBeautifulHtmlSummary
        case "example-eu-chat-control-law":
            return AppStrings.exampleEuChatControlSummary
        case "example-flights-berlin-bangkok":
            return AppStrings.exampleFlightsBerlinBangkokSummary
        case "example-creativity-drawing-meetups-berlin":
            return AppStrings.exampleCreativityDrawingSummary
        default:
            return nil
        }
    }
}

struct NewChatWelcomeView: View {
    let inspirations: [DailyInspirationBanner.DailyInspiration]
    let isAuthenticated: Bool
    let currentUser: UserProfile?
    let chats: [Chat]
    let totalChatCount: Int
    let serverSuggestions: [NewChatSuggestionsView.ChatSuggestion]
    let onCreateChatWithMessage: (String) async throws -> String
    let onChatCreated: (String) -> Void
    let onOpenChat: (String) -> Void
    let onInspirationViewed: (String) -> Void
    let onOpenAuth: () -> Void
    @State private var messageText = ""
    @State private var suggestions: [NewChatSuggestionsView.ChatSuggestion] = []
    @State private var hiddenSuggestionIds = Set<String>()
    @State private var inspirationIndex = 0
    @State private var viewedInspirationIds = Set<String>()
    @State private var isComposerExpanded = false
    @FocusState private var isFocused: Bool

    private var activeInspiration: DailyInspirationBanner.DailyInspiration? {
        guard !inspirations.isEmpty else { return nil }
        return inspirations[min(inspirationIndex, inspirations.count - 1)]
    }

    private var displayName: String {
        let username = currentUser?.username.trimmingCharacters(in: .whitespacesAndNewlines)
        return (username?.isEmpty == false ? username : nil) ?? "OpenMates"
    }

    private var resumeChat: Chat? {
        WelcomeScreenState.resumeChat(from: chats, lastOpened: currentUser?.lastOpened)
    }

    private var recentChatCards: [WelcomeChatCardData] {
        var cards: [WelcomeChatCardData] = []
        if let resumeChat {
            cards.append(WelcomeScreenState.cardData(for: resumeChat))
        }
        cards.append(contentsOf: WelcomeScreenState
            .recentChats(from: chats, excluding: resumeChat?.id)
            .map { WelcomeScreenState.cardData(for: $0) })
        return cards
    }

    private var nonAuthChatCards: [WelcomeChatCardData] {
        chats
            .filter { chat in
                !chat.id.hasPrefix("legal-") &&
                (chat.id.hasPrefix("demo-") || chat.id.hasPrefix("example-") || chat.id.hasPrefix("announcements-"))
            }
            .map { WelcomeScreenState.cardData(for: $0) }
    }

    private var shownChatCards: [WelcomeChatCardData] {
        isAuthenticated ? recentChatCards : nonAuthChatCards
    }

    private var isComposerActive: Bool {
        isFocused || isComposerExpanded || WelcomeScreenState.shouldShowInFieldSendButton(inputText: messageText)
    }

    private var overflowCount: Int {
        guard isAuthenticated, totalChatCount > shownChatCards.count else { return 0 }
        return totalChatCount - shownChatCards.count
    }

    private var subtitle: String {
        if isAuthenticated, !shownChatCards.isEmpty {
            return AppStrings.resumeLastChatTitle
        }
        if isAuthenticated {
            return AppStrings.whatDoYouNeedHelpWith
        }
        return AppStrings.exploreOpenMatesTitle
    }

    var body: some View {
        GeometryReader { proxy in
            let composerReserve: CGFloat = isComposerActive ? 156 : 100

            ZStack(alignment: .bottom) {
                Color.clear
                    .ignoresSafeArea()

                VStack(spacing: 0) {
                    if let activeInspiration, !isComposerActive {
                        inspirationCarousel(activeInspiration)
                            .padding(.top, 0)
                            .transition(.opacity)
                    }

                    Spacer(minLength: 0)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)

                if !isComposerActive {
                    VStack(spacing: .spacing4) {
                        welcomeHeader

                        if !shownChatCards.isEmpty {
                            welcomeCardsCarousel
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .position(
                        x: proxy.size.width / 2,
                        y: welcomeClusterCenterY(for: proxy.size, composerReserve: composerReserve)
                    )
                    .transition(.opacity)
                }

                if !suggestions.isEmpty && (shownChatCards.isEmpty || isComposerActive) {
                    suggestionsCarousel
                        .frame(maxWidth: .infinity)
                        .padding(.bottom, composerReserve)
                        .transition(.opacity)
                }

                WelcomeComposer(
                    text: $messageText,
                    isExpanded: $isComposerExpanded,
                    isFocused: $isFocused,
                    isAuthenticated: isAuthenticated,
                    onSend: { createChatWith(message: messageText) },
                    onOpenAuth: onOpenAuth
                )
            }
            .animation(.easeInOut(duration: 0.2), value: isComposerActive)
        }
        .background(Color.clear)
        .task { await loadSuggestions() }
        .onChange(of: serverSuggestions.map(\.id)) { _, _ in
            if !serverSuggestions.isEmpty {
                suggestions = serverSuggestions
                hiddenSuggestionIds.removeAll()
            }
        }
    }

    private var welcomeHeader: some View {
        VStack(spacing: .spacing3) {
            Text(isAuthenticated ? AppStrings.welcomeHeyUser(displayName) : AppStrings.welcomeHeyGuest)
                .font(.custom("Lexend Deca", size: 30).weight(.semibold))
                .foregroundStyle(Color.fontPrimary)
                .multilineTextAlignment(.center)
                .lineLimit(2)

            Text(subtitle)
                .font(.custom("Lexend Deca", size: 16).weight(.semibold))
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)
                .lineLimit(2)
        }
        .padding(.horizontal, .spacing6)
    }

    private var welcomeCardsCarousel: some View {
        GeometryReader { proxy in
            let cardWidth: CGFloat = min(330, proxy.size.width - 72)
            let sideInset = max((proxy.size.width - cardWidth) / 2, CGFloat.spacing5)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: .spacing8) {
                    ForEach(shownChatCards) { card in
                        WelcomeResumeCard(card: card, width: cardWidth, height: 216) {
                            onOpenChat(card.id)
                        }
                    }
                    if overflowCount > 0 {
                        OverflowCard(count: overflowCount)
                    }
                }
                .padding(.leading, sideInset)
                .padding(.trailing, .spacing12)
                .padding(.vertical, .spacing3)
            }
        }
        .frame(height: 240)
    }

    private var suggestionsCarousel: some View {
        GeometryReader { proxy in
            let cardWidth: CGFloat = proxy.size.width <= 730 ? 210 : 300
            let sideInset = max((proxy.size.width - cardWidth) / 2, proxy.size.width <= 730 ? 15 : 48)

            VStack(alignment: .leading, spacing: .spacing3) {
                Text(AppStrings.suggestionsHeader)
                    .font(proxy.size.width <= 730 ? .omSmall : .omP)
                    .foregroundStyle(Color.grey60)
                    .tracking(0.5)
                    .opacity(0.9)
                    .padding(.leading, sideInset)

                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: proxy.size.width <= 730 ? .spacing5 : .spacing6) {
                        ForEach(filteredSuggestions) { suggestion in
                            SuggestionChip(suggestion: suggestion, width: cardWidth) {
                                hiddenSuggestionIds.insert(suggestion.id)
                                messageText = suggestion.parsedBody
                                isFocused = true
                            }
                        }
                    }
                    .padding(.leading, sideInset)
                    .padding(.trailing, proxy.size.width <= 730 ? 15 : 48)
                    .padding(.top, 4)
                    .padding(.bottom, proxy.size.width <= 730 ? 8 : 14)
                }
            }
            .mask(
                LinearGradient(
                    stops: [
                        .init(color: .clear, location: 0),
                        .init(color: .black, location: proxy.size.width <= 730 ? 0.05 : 0.035),
                        .init(color: .black, location: proxy.size.width <= 730 ? 0.95 : 0.965),
                        .init(color: .clear, location: 1)
                    ],
                    startPoint: .leading,
                    endPoint: .trailing
                )
            )
        }
        .frame(height: 106)
    }

    private func inspirationCarousel(_ activeInspiration: DailyInspirationBanner.DailyInspiration) -> some View {
        ZStack {
            InspirationCard(inspiration: activeInspiration) {
                createChatWith(message: activeInspiration.text)
            }
            .frame(maxWidth: .infinity)

            if inspirations.count > 1 {
                HStack {
                    carouselArrow(label: AppStrings.previousInspiration) {
                        inspirationIndex = (inspirationIndex - 1 + inspirations.count) % inspirations.count
                    }
                    Spacer()
                    carouselArrow(label: AppStrings.nextInspiration) {
                        inspirationIndex = (inspirationIndex + 1) % inspirations.count
                    }
                    .scaleEffect(x: -1, y: 1)
                }
                .padding(.horizontal, .spacing2)
            }
        }
        .frame(maxWidth: .infinity)
        .onAppear { sendViewedEvent(for: activeInspiration) }
        .onChange(of: inspirationIndex) { _, _ in
            if let current = self.activeInspiration {
                sendViewedEvent(for: current)
            }
        }
    }

    private func welcomeClusterCenterY(for size: CGSize, composerReserve: CGFloat) -> CGFloat {
        let availableHeight = max(0, size.height - composerReserve)
        let webLikeCenter = availableHeight * 0.79
        return min(max(webLikeCenter, 330), max(330, size.height - composerReserve - 150))
    }

    private func carouselArrow(label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Icon("back", size: 22)
                .foregroundStyle(.white.opacity(0.85))
                .frame(width: 40, height: 240)
                .background(.white.opacity(0.001))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }

    private func sendViewedEvent(for inspiration: DailyInspirationBanner.DailyInspiration) {
        guard let inspirationId = inspiration.inspirationId, !viewedInspirationIds.contains(inspirationId) else { return }
        viewedInspirationIds.insert(inspirationId)
        onInspirationViewed(inspirationId)
    }

    /// Filter suggestions based on typed text, matching web's debounced filter behavior
    private var filteredSuggestions: [NewChatSuggestionsView.ChatSuggestion] {
        let visibleSuggestions = suggestions.filter { !hiddenSuggestionIds.contains($0.id) }
        guard !messageText.isEmpty else { return visibleSuggestions }
        let query = messageText.lowercased()
        let filtered = visibleSuggestions.filter {
            $0.parsedBody.lowercased().contains(query) ||
            $0.resolvedAppId.lowercased().contains(query)
        }
        return filtered.isEmpty ? visibleSuggestions : filtered
    }

    private func loadSuggestions() async {
        if !serverSuggestions.isEmpty {
            suggestions = serverSuggestions
            hiddenSuggestionIds.removeAll()
            return
        }

        do {
            suggestions = try await APIClient.shared.request(
                .get, path: "/v1/chat/suggestions"
            )
        } catch {
            print("[NewChatWelcome] Suggestions API unavailable, using defaults")
        }

        // Hardcoded fallback when API is unavailable (matches web DEFAULT_NEW_CHAT_SUGGESTION_KEYS)
        if suggestions.isEmpty {
            suggestions = Self.defaultSuggestions
        }
        hiddenSuggestionIds.removeAll()
    }

    /// Hardcoded default suggestions matching the web app's defaultNewChatSuggestions.ts
    private static let defaultSuggestions: [NewChatSuggestionsView.ChatSuggestion] = [
        .init(id: "s1", text: "What's the difference between machine learning and AI?", appId: "ai", category: nil, icon: nil),
        .init(id: "s2", text: "Search the web for the latest AI news", appId: "web", category: nil, icon: nil),
        .init(id: "s3", text: "Plan a 7-day trip to Japan", appId: "travel", category: nil, icon: nil),
        .init(id: "s4", text: "Find trending videos about space exploration", appId: "videos", category: nil, icon: nil),
        .init(id: "s5", text: "Explain quantum computing in simple terms", appId: "ai", category: nil, icon: nil),
        .init(id: "s6", text: "Write a professional cover letter", appId: "ai", category: nil, icon: nil),
        .init(id: "s7", text: "Create a healthy meal prep plan", appId: "nutrition", category: nil, icon: nil),
        .init(id: "s8", text: "Help me learn basic Spanish phrases", appId: "ai", category: nil, icon: nil),
    ]

    private func createChatWith(message: String) {
        guard !message.isEmpty else { return }

        // Unauthenticated users: open auth flow instead of creating a chat
        guard isAuthenticated else {
            onOpenAuth()
            return
        }

        Task {
            do {
                let chatId = try await onCreateChatWithMessage(message)
                onChatCreated(chatId)
            } catch {
                print("[NewChatWelcome] Failed to create chat: \(error)")
            }
        }
    }
}

private struct WelcomeResumeCard: View {
    let card: WelcomeChatCardData
    let width: CGFloat
    let height: CGFloat
    let onTap: () -> Void

    var body: some View {
        TimelineView(.animation) { timeline in
            let time = timeline.date.timeIntervalSinceReferenceDate

            Button(action: onTap) {
                ZStack {
                    AnimatedCategoryBackground(category: card.category, iconName: card.iconName, time: time)

                    VStack(spacing: .spacing2) {
                        WelcomeCardIcon(name: card.iconName, size: 32)

                        Text(card.title)
                            .font(.custom("Lexend Deca", size: 16).weight(.bold))
                            .fontWeight(.bold)
                            .foregroundStyle(.white)
                            .multilineTextAlignment(.center)
                            .lineLimit(2)
                            .minimumScaleFactor(0.82)

                        if let summary = card.summary {
                            Text(summary)
                                .font(.custom("Lexend Deca", size: 12).weight(.medium))
                                .foregroundStyle(.white.opacity(0.86))
                                .multilineTextAlignment(.center)
                                .lineLimit(4)
                        }
                    }
                    .padding(.horizontal, .spacing12)
                    .shadow(color: .black.opacity(0.28), radius: 4, x: 0, y: 1)

                    if card.isPinned {
                        Icon("pin", size: 16)
                            .foregroundStyle(.white)
                            .frame(width: 30, height: 30)
                            .background(.black.opacity(0.18))
                            .clipShape(Circle())
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                            .padding(.spacing4)
                    }
                }
                .frame(width: width, height: height)
                .clipShape(RoundedRectangle(cornerRadius: 30))
                .shadow(color: .black.opacity(0.18), radius: 16, x: 0, y: 8)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(card.title)
        }
    }
}

private struct AnimatedCategoryBackground: View {
    let category: String
    let iconName: String
    let time: Double

    var body: some View {
        GeometryReader { geo in
            ZStack {
                CategoryMapping.gradient(for: category)

                resumeOrb(color: CategoryMapping.orbColor(for: category), size: CGSize(width: 280, height: 240), opacity: 0.35, time: time, morph: 11, drift: 19)
                    .position(x: -20, y: 20)
                resumeOrb(color: CategoryMapping.orbColor(for: category), size: CGSize(width: 260, height: 220), opacity: 0.35, time: time + 8, morph: 13, drift: 23)
                    .position(x: geo.size.width + 20, y: geo.size.height + 10)
                resumeOrb(color: CategoryMapping.orbColor(for: category), size: CGSize(width: 200, height: 180), opacity: 0.38, time: time + 15, morph: 17, drift: 29)
                    .position(x: geo.size.width * 0.48, y: 50)

                decoIcon(size: 80, rotation: -15, time: time)
                    .position(x: 30, y: geo.size.height - 12)
                decoIcon(size: 80, rotation: 15, time: time + 8)
                    .position(x: geo.size.width - 30, y: geo.size.height - 12)
            }
        }
        .clipped()
    }

    private func resumeOrb(color: Color, size: CGSize, opacity: Double, time: Double, morph: Double, drift: Double) -> some View {
        let morphX = 1.0 + 0.15 * sin(time * .pi * 2 / morph)
        let morphY = 1.0 + 0.15 * cos(time * .pi * 2 / morph + 0.7)
        let driftX = 18 * sin(time * .pi * 2 / drift)
        let driftY = 15 * cos(time * .pi * 2 / drift + 1.2)

        return Ellipse()
            .fill(
                RadialGradient(
                    colors: [color, color, color.opacity(0)],
                    center: .center,
                    startRadius: 0,
                    endRadius: max(size.width, size.height) * 0.45
                )
            )
            .frame(width: size.width, height: size.height)
            .scaleEffect(x: morphX, y: morphY)
            .offset(x: driftX, y: driftY)
            .blur(radius: 22)
            .opacity(opacity)
    }

    private func decoIcon(size: CGFloat, rotation: Double, time: Double) -> some View {
        WelcomeCardIcon(name: iconName, size: size)
            .opacity(0.3)
            .rotationEffect(.degrees(rotation))
            .offset(
                x: 7 * cos(time * .pi * 2 / 16),
                y: 8 * sin(time * .pi * 2 / 16)
            )
    }
}

private struct WelcomeCardIcon: View {
    let name: String
    let size: CGFloat

    var body: some View {
        LucideNativeIcon(name, size: size)
            .foregroundStyle(.white)
    }
}

struct LucideNativeIcon: View {
    let name: String
    let size: CGFloat

    init(_ name: String, size: CGFloat) {
        self.name = name
        self.size = size
    }

    var body: some View {
        #if os(iOS)
        if let image = UIImage(lucideId: name) ?? UIImage(lucideId: "message-square") {
            Image(uiImage: image)
                .renderingMode(.template)
                .resizable()
                .scaledToFit()
                .frame(width: size, height: size)
        } else {
            EmptyView()
        }
        #elseif os(macOS)
        if let image = NSImage.image(lucideId: name) ?? NSImage.image(lucideId: "message-square") {
            Image(nsImage: image)
                .renderingMode(.template)
                .resizable()
                .scaledToFit()
                .frame(width: size, height: size)
        } else {
            EmptyView()
        }
        #endif
    }
}

private struct OverflowCard: View {
    let count: Int

    var body: some View {
        Text("+\(count)")
            .font(.omH3)
            .fontWeight(.bold)
            .foregroundStyle(Color.fontPrimary)
            .frame(width: 92, height: 200)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .overlay(
                RoundedRectangle(cornerRadius: .radius8)
                    .stroke(Color.grey20, lineWidth: 1)
            )
    }
}

private struct WelcomeComposer: View {
    @Binding var text: String
    @Binding var isExpanded: Bool
    @FocusState.Binding var isFocused: Bool
    let isAuthenticated: Bool
    let onSend: () -> Void
    let onOpenAuth: () -> Void

    private var hasContent: Bool {
        WelcomeScreenState.shouldShowInFieldSendButton(inputText: text)
    }

    private var isOpen: Bool {
        hasContent || isFocused || isExpanded
    }

    var body: some View {
        VStack(spacing: 0) {
            OMMessageInputField(
                text: $text,
                isFocused: $isFocused,
                compact: !hasContent,
                placeholder: AppStrings.typeMessage,
                compactHeight: 60,
                compactCornerRadius: 24,
                showActionButtonsWhenCompact: isOpen,
                expandedMinHeight: 112,
                accessibilityHint: AppStrings.typeMessage,
                onSubmit: { isAuthenticated ? onSend() : onOpenAuth() }
            ) {
                HStack(spacing: .spacing5) {
                    Icon("files", size: 22)
                        .foregroundStyle(Color.fontSecondary)
                    Icon("maps", size: 22)
                        .foregroundStyle(Color.fontSecondary)
                    Icon("modify", size: 22)
                        .foregroundStyle(Color.fontSecondary)
                    Spacer()
                    Icon("take_photo", size: 22)
                        .foregroundStyle(Color.fontSecondary)
                    Icon("recordaudio", size: 22)
                        .foregroundStyle(Color.fontSecondary)
                    if hasContent {
                        Button {
                            isAuthenticated ? onSend() : onOpenAuth()
                        } label: {
                            Text(isAuthenticated ? AppStrings.sendAction : AppStrings.signUp)
                                .font(.omSmall)
                                .fontWeight(.semibold)
                                .foregroundStyle(Color.fontButton)
                                .padding(.horizontal, .spacing8)
                                .frame(height: 40)
                                .background(Color.buttonPrimary)
                                .clipShape(RoundedRectangle(cornerRadius: .radius8))
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("send-button")
                    }
                }
                .padding(.horizontal, .spacing5)
                .padding(.bottom, .spacing4)
                .transition(.opacity)
            }
            .onChange(of: isFocused) { _, newValue in
                if newValue {
                    isExpanded = true
                }
            }

            if isOpen {
                Button {
                    isFocused = false
                    isExpanded = false
                } label: {
                    Text(hasContent ? AppStrings.save : AppStrings.cancel)
                        .font(.omSmall)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.fontSecondary)
                        .padding(.horizontal, .spacing8)
                        .padding(.vertical, .spacing3)
                        .background(Color.grey10)
                        .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                        .overlay(
                            RoundedRectangle(cornerRadius: .radiusFull)
                                .stroke(Color.grey30, lineWidth: 1)
                        )
                }
                .buttonStyle(.plain)
                .padding(.top, .spacing3)
                .transition(.opacity)
            }
        }
        .padding(.horizontal, .spacing5)
        .padding(.bottom, .spacing10)
        .animation(.easeInOut(duration: 0.2), value: isOpen)
        .animation(.easeInOut(duration: 0.2), value: hasContent)
    }
}

// InspirationCard is defined in DailyInspirationView.swift — matches
// DailyInspirationBanner.svelte gradient card with living gradient orbs,
// category-specific gradient, mate profile, phrase text, and CTA.
