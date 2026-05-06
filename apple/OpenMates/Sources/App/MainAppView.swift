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
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct MainAppView: View {
    let launchCommand: AppWindowLaunchCommand?

    @EnvironmentObject var authManager: AuthManager
    @EnvironmentObject var themeManager: ThemeManager
    @EnvironmentObject var pushManager: PushNotificationManager
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @StateObject private var chatStore = ChatStore()
    @StateObject private var wsManager = WebSocketManager()
    @StateObject private var deepLinkHandler = DeepLinkHandler()
    @StateObject private var incognitoManager = IncognitoManager()
    @StateObject private var handoffManager = HandoffManager()
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
    @State private var totalChatCount = 0
    @State private var isLoadingMore = false
    @State private var showRenameAlert = false
    @State private var renameChatId: String?
    @State private var renameChatTitle = ""
    @State private var showAuthSheet = false
    @State private var actionChat: Chat?
    @State private var didBootstrapAuthenticatedSession = false
    @State private var didApplyLaunchCommand = false
    @State private var shellDragOffset: CGFloat = 0

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
        guard !searchText.isEmpty else { return unpinned }
        return unpinned.filter { $0.displayTitle.localizedCaseInsensitiveContains(searchText) }
    }

    private var isCompactShell: Bool {
        horizontalSizeClass == .compact
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
        GeometryReader { geo in
            let viewportWidth = geo.size.width
            let compactPanelWidth = min(viewportWidth - 10, 390)
            let chatsPanelOffset = isCompactShell
                ? (isChatsPanelOpen ? max(0, compactPanelWidth + shellDragOffset) : max(0, shellDragOffset))
                : 0

            ZStack(alignment: .leading) {
                activeAppChrome(viewportWidth: viewportWidth)
                    .offset(x: chatsPanelOffset)

                if isCompactShell {
                    chatsPanel
                        .frame(width: compactPanelWidth)
                        .offset(x: isChatsPanelOpen ? min(0, shellDragOffset) : -compactPanelWidth + max(0, shellDragOffset))
                        .allowsHitTesting(isChatsPanelOpen || shellDragOffset > 0)
                        .accessibilityHidden(!isChatsPanelOpen)
                        .zIndex(1)
                }
            }
            .clipped()
            .contentShape(Rectangle())
            .simultaneousGesture(shellSwipeGesture(viewportWidth: viewportWidth))
            .animation(.easeInOut(duration: 0.24), value: isChatsPanelOpen)
        }
        .background(Color.grey0)
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
            VStack(spacing: 0) {
                OfflineBanner(isOffline: syncBridge?.networkStatus == .offline)
                NetworkStatusBanner(wsManager: wsManager)
            }
        }
        .onOpenURL { url in
            deepLinkHandler.handle(url: url)
        }
        // Handoff: continue a chat from another Apple device
        .onContinueUserActivity(HandoffManager.viewChatActivityType) { activity in
            if let chatId = activity.userInfo?["chatId"] as? String {
                selectedChatId = chatId
            }
        }
        .onContinueUserActivity(HandoffManager.browseChatsActivityType) { _ in
            // Just bring the app to the chat list — no specific action needed
        }
        // Spotlight: open a chat from system search results
        .onContinueUserActivity(CSSearchableItemActionType) { activity in
            if let identifier = activity.userInfo?[CSSearchableItemActivityIdentifier] as? String,
               identifier.hasPrefix("chat-") {
                selectedChatId = String(identifier.dropFirst("chat-".count))
            }
        }
        // Global keyboard shortcuts (iPad + Mac)
        .appKeyboardShortcuts(
            onNewChat: openNewChatScreen,
            onSearch: { showSearch = true },
            onSettings: { showSettings = true }
        )
        .onChange(of: deepLinkHandler.pendingChatId) { _, chatId in
            if let chatId {
                selectedChatId = chatId
                deepLinkHandler.clearPending()
            }
        }
        .onChange(of: deepLinkHandler.pendingPairToken) { _, token in
            if let token {
                pairToken = token
                showPairAuthorize = true
                deepLinkHandler.pendingPairToken = nil
            }
        }
        .onChange(of: deepLinkHandler.pendingInspirationId) { _, inspirationId in
            if inspirationId != nil {
                selectedChatId = nil
                showNewChat = true
                deepLinkHandler.pendingInspirationId = nil
            }
        }
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
            }
        }
        #endif
        .task {
            if isAuthenticated {
                await bootstrapAuthenticatedSession()
            } else {
                // Unauthenticated: populate sidebar with demo chats
                loadDemoChats()
                // Fetch default daily inspirations (public endpoint, no auth required)
                await syncInspirationToWidget()
            }
            applyLaunchCommandIfNeeded()
        }
        .onReceive(NotificationCenter.default.publisher(for: .wsMessageReceived)) { notification in
            handleChatUpdate(notification)
        }
        .onReceive(NotificationCenter.default.publisher(for: .wsEmbedUpdate)) { notification in
            handleEmbedUpdate(notification)
        }
        .onChange(of: authManager.state) { _, newState in
            if newState == .authenticated {
                showAuthSheet = false
                Task { await bootstrapAuthenticatedSession() }
            } else if newState == .unauthenticated {
                didBootstrapAuthenticatedSession = false
                wsManager.disconnect()
            }
        }
        .onChange(of: pushManager.pendingChatId) { _, chatId in
            if let chatId {
                selectedChatId = chatId
                pushManager.pendingChatId = nil
            }
        }
    }

    private func openNewChatScreen() {
        selectedChatId = nil
        showNewChat = true
        showAuthSheet = false
    }

    private func applyLaunchCommandIfNeeded() {
        guard !didApplyLaunchCommand else { return }
        didApplyLaunchCommand = true

        if launchCommand?.action == .newChat {
            openNewChatScreen()
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

        let startedNearLeftEdge = value.startLocation.x <= 42
        let startedNearRightEdge = value.startLocation.x >= viewportWidth - 42

        if isCompactShell, !isChatsPanelOpen, !showSettings, startedNearLeftEdge, dx > 0 {
            shellDragOffset = min(dx, min(viewportWidth - 10, 390))
        } else if isCompactShell, isChatsPanelOpen, dx < 0 {
            shellDragOffset = min(0, dx)
        } else if !showSettings, startedNearRightEdge, dx < 0 {
            shellDragOffset = max(dx, -min(viewportWidth - 40, 323))
        } else if showSettings, dx > 0 {
            shellDragOffset = min(dx, min(viewportWidth - 40, 323))
        } else {
            shellDragOffset = 0
        }
    }

    private func handleShellSwipe(_ value: DragGesture.Value, viewportWidth: CGFloat) {
        let dx = value.translation.width
        let dy = value.translation.height
        defer { shellDragOffset = 0 }
        guard abs(dx) > 70, abs(dx) > abs(dy) * 1.35 else { return }

        let startedNearLeftEdge = value.startLocation.x <= 42
        let startedNearRightEdge = value.startLocation.x >= viewportWidth - 42

        withAnimation(.easeInOut(duration: 0.24)) {
            if dx < 0 {
                if isChatsPanelOpen {
                    isChatsPanelOpen = false
                } else if !showSettings, startedNearRightEdge {
                    showSettings = true
                }
            } else {
                if showSettings {
                    showSettings = false
                } else if !isChatsPanelOpen, startedNearLeftEdge {
                    isChatsPanelOpen = true
                }
            }
        }
    }

    private func activeAppChrome(viewportWidth: CGFloat) -> some View {
        VStack(spacing: 0) {
            OpenMatesWebHeader(
                isAuthenticated: isAuthenticated || showAuthSheet,
                isChatsPanelOpen: isChatsPanelOpen,
                isSettingsOpen: showSettings,
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

                        if showSettings {
                            settingsPanel(width: 323)
                                .transition(.move(edge: .trailing).combined(with: .opacity))
                        }
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
        } else {
            HStack(spacing: 0) {
                if isChatsPanelOpen {
                    chatsPanel
                        .frame(width: 340)
                        .transition(.move(edge: .leading).combined(with: .opacity))

                    Divider()
                        .overlay(Color.grey20)
                }

                if showAuthSheet {
                    authContent
                } else {
                    detailContent
                }
            }
        }
    }

    private var authContent: some View {
        AuthFlowView(onBackToDemo: {
            showAuthSheet = false
            selectedChatId = "demo-for-everyone"
        })
        .environmentObject(authManager)
    }

    @ViewBuilder
    private var detailContent: some View {
        if isAuthenticated, let chatId = selectedChatId {
            ChatView(
                chatId: chatId,
                isSettingsOpen: showSettings,
                onPreviousChat: previousChatAction(for: chatId),
                onNextChat: nextChatAction(for: chatId),
                onOpenPublicChat: openPublicChat,
                onNewChat: openNewChatScreen
            )
        } else if !isAuthenticated, let chatId = selectedChatId {
            ChatView(
                chatId: chatId,
                bannerState: demoBannerState(for: chatId),
                bannerCreatedAt: nil,
                isSettingsOpen: showSettings,
                onPreviousChat: previousChatAction(for: chatId),
                onNextChat: nextChatAction(for: chatId),
                onOpenPublicChat: openPublicChat,
                onNewChat: openNewChatScreen
            )
        } else {
            NewChatWelcomeView(
                inspirations: dailyInspirations,
                isAuthenticated: isAuthenticated,
                currentUser: authManager.currentUser,
                chats: chatStore.chats,
                totalChatCount: totalChatCount,
                onChatCreated: { chatId in
                    selectedChatId = chatId
                    showNewChat = false
                },
                onOpenChat: { chatId in
                    selectedChatId = chatId
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

                    if !filteredUnpinnedChats.isEmpty {
                        let header = filteredPinnedChats.isEmpty ? AppStrings.chats : AppStrings.recentChats
                        chatSectionHeader(header)
                        ForEach(filteredUnpinnedChats) { chat in
                            chatRow(chat)
                        }
                    } else if filteredPinnedChats.isEmpty && isAuthenticated && self.publicChats(in: .intro).isEmpty {
                        Text(AppStrings.noChats)
                            .font(.omSmall)
                            .foregroundStyle(Color.fontTertiary)
                            .frame(maxWidth: .infinity, alignment: .center)
                            .padding(.top, .spacing10)
                    }

                    if isAuthenticated {
                        if chatStore.chats.count < totalChatCount {
                            ShowMoreChatsButton(
                                totalCount: totalChatCount,
                                loadedCount: chatStore.chats.count,
                                isLoading: isLoadingMore,
                                onLoadMore: { loadMoreChats() }
                            )
                            .padding(.horizontal, .spacing5)
                        }
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
                showSearch = true
            } label: {
                Icon("search", size: 32)
                    .foregroundStyle(LinearGradient.primary)
                    .frame(width: 34, height: 34)
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
                Icon("close", size: 32)
                    .foregroundStyle(LinearGradient.primary)
                    .frame(width: 34, height: 34)
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
    /// Opens demo-for-everyone by default — same as +page.svelte cold-boot behaviour.
    /// Mirrors: INTRO_CHATS + LEGAL_CHATS + announcements + example chats from demo_chats/index.ts
    private func loadDemoChats() {
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
        // Open the for-everyone chat by default — matches web app's cold-boot behaviour
        selectedChatId = "demo-for-everyone"
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

        // Clear unauthenticated/demo content before loading real user data.
        chatStore.clearInMemory()
        totalChatCount = 0
        selectedChatId = nil
        showNewChat = false

        let bridge = syncBridge ?? OfflineSyncBridge(chatStore: chatStore)
        chatStore.setBridge(bridge)
        syncBridge = bridge
        bridge.loadFromDisk()

        await loadInitialData()
        await syncInspirationToWidget()
        connectWebSocket()
    }

    private func loadInitialData() async {
        do {
            let response: ChatListResponse = try await APIClient.shared.request(.get, path: "/v1/chats")

            // Load master key from Keychain and unwrap per-chat keys
            if let userId = authManager.currentUser?.id {
                await loadChatKeys(chats: response.chats, userId: userId)
            }

            // Decrypt chat titles and upsert into store
            var decryptedChats: [Chat] = []
            for var chat in response.chats {
                if let encTitle = chat.encryptedTitle,
                   let title = await ChatKeyManager.shared.decryptTitle(
                       for: chat.id, encryptedTitle: encTitle
                   ) {
                    chat.title = title
                }
                chatStore.upsertChat(chat)
                decryptedChats.append(chat)
            }

            // Index decrypted chats into Core Spotlight
            SpotlightIndexer.shared.indexChats(decryptedChats)
        } catch {
            print("[MainApp] Failed to load chats: \(error)")
        }
    }

    /// Load master key from Keychain, then bulk-unwrap all per-chat encryption keys.
    private func loadChatKeys(chats: [Chat], userId: String) async {
        // Skip if keys are already loaded
        guard !ChatKeyManager.shared.isReady else { return }

        do {
            guard let masterKey = try await CryptoManager.shared.loadMasterKey(for: userId) else {
                print("[MainApp] No master key in Keychain — encrypted content will not be decryptable")
                return
            }

            let chatKeysToLoad = chats.compactMap { chat -> (chatId: String, encryptedChatKey: String)? in
                guard let eck = chat.encryptedChatKey else { return nil }
                return (chatId: chat.id, encryptedChatKey: eck)
            }

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
                for chat in response.chats {
                    chatStore.upsertChat(chat)
                }
            } catch {
                print("[MainApp] Failed to load more chats: \(error)")
            }
            isLoadingMore = false
        }
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
        guard let sessionId = authManager.currentUser?.id else { return }
        wsManager.connect(sessionId: sessionId)
    }

    private func handleChatUpdate(_ notification: Notification) {
        Task { await loadInitialData() }
    }

    private func handleEmbedUpdate(_ notification: Notification) {
        // Forward embed updates so the active ChatView can reload its embeds.
        // The notification carries the raw WS data; ChatViewModel listens for
        // embed refresh signals via NotificationCenter.
        NotificationCenter.default.post(name: .embedRefreshNeeded, object: nil, userInfo: notification.userInfo)
    }
}

// MARK: - Web app header

struct OpenMatesWebHeader: View {
    let isAuthenticated: Bool
    let isChatsPanelOpen: Bool
    let isSettingsOpen: Bool
    let onToggleChats: () -> Void
    let onNewChat: () -> Void
    let onShareChat: () -> Void
    let canShareChat: Bool
    let onOpenSettings: () -> Void
    let onOpenAuth: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: .spacing4) {
            Button(action: onToggleChats) {
                // Web: uses the same branded icon treatment as the top-right settings affordance.
                WebHamburgerIcon(isOpen: isChatsPanelOpen)
                    .foregroundStyle(LinearGradient.primary)
            }
            .buttonStyle(.plain)
            .frame(width: 34, height: 34)
            .contentShape(Rectangle())
            .accessibilityIdentifier("sidebar-toggle")
            .accessibilityLabel(LocalizationManager.shared.text("header.toggle_menu"))

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
                Icon(isSettingsOpen ? "close" : "settings", size: isSettingsOpen ? 25 : 22)
                    .foregroundStyle(LinearGradient.primary)
                    .frame(width: 38, height: 38)
                    .background(isSettingsOpen ? Color.clear : Color.grey10)
                    .clipShape(Circle())
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
        WelcomeChatCardData(
            id: chat.id,
            title: chat.displayTitle,
            summary: summary(for: chat.id),
            category: category(for: chat),
            iconName: cardIconName(for: chat),
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
    let onChatCreated: (String) -> Void
    let onOpenChat: (String) -> Void
    let onInspirationViewed: (String) -> Void
    let onOpenAuth: () -> Void
    @State private var messageText = ""
    @State private var suggestions: [NewChatSuggestionsView.ChatSuggestion] = []
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
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: .spacing3) {
                ForEach(filteredSuggestions) { suggestion in
                    SuggestionChip(suggestion: suggestion) {
                        messageText = suggestion.text
                        isFocused = true
                    }
                }
            }
            .padding(.horizontal, .spacing5)
        }
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
        guard !messageText.isEmpty else { return suggestions }
        let query = messageText.lowercased()
        let filtered = suggestions.filter { $0.text.lowercased().contains(query) }
        return filtered.isEmpty ? suggestions : filtered
    }

    private func loadSuggestions() async {
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

        let chatId = UUID().uuidString

        Task {
            let body: [String: Any] = [
                "chat_id": chatId,
                "message": [
                    "message_id": UUID().uuidString,
                    "role": "user",
                    "content": message,
                    "created_at": Int(Date().timeIntervalSince1970),
                    "chat_has_title": false
                ] as [String: Any]
            ]

            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/chat/message", body: body
                )
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
        if let image = UIImage(lucideId: name) {
            Image(uiImage: image)
                .renderingMode(.template)
                .resizable()
                .scaledToFit()
                .frame(width: size, height: size)
        } else {
            EmptyView()
        }
        #elseif os(macOS)
        if let image = NSImage.image(lucideId: name) {
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
            ZStack(alignment: .bottom) {
                TextField(AppStrings.typeMessage, text: $text, axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(.omP)
                    .lineLimit(1...5)
                    .tint(Color.buttonPrimary)
                    .focused($isFocused)
                    .padding(.horizontal, .spacing8)
                    .padding(.top, isOpen ? .spacing6 : .spacing8)
                    .padding(.bottom, isOpen ? .spacing32 : .spacing5)
                    .fontWeight(isOpen ? .regular : .semibold)
                    .multilineTextAlignment(isOpen ? .leading : .center)
                    .frame(maxWidth: .infinity, minHeight: isOpen ? 112 : 68, alignment: isOpen ? .topLeading : .center)
                    .onTapGesture {
                        isExpanded = true
                        DispatchQueue.main.async {
                            isFocused = true
                        }
                    }
                    .onChange(of: isFocused) { _, newValue in
                        if newValue {
                            isExpanded = true
                        }
                    }
                    .accessibilityIdentifier("welcome-message-input")
                    .accessibilityLabel(AppStrings.typeMessage)

                if isOpen {
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
                            .accessibilityIdentifier("welcome-send-button")
                        }
                    }
                    .padding(.horizontal, .spacing5)
                    .padding(.bottom, .spacing4)
                    .transition(.opacity)
                }
            }
            .background(Color.greyBlue)
            .clipShape(RoundedRectangle(cornerRadius: 24))
            .overlay(
                RoundedRectangle(cornerRadius: 24)
                    .stroke(isOpen ? Color.buttonPrimary.opacity(0.7) : Color.clear, lineWidth: 2)
            )
            .shadow(color: .black.opacity(0.10), radius: 16, x: 0, y: 8)

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
