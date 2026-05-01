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

struct MainAppView: View {
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
    @State private var showNewChatSheet = false
    @State private var showExplore = false
    @State private var showSearch = false
    @State private var showShareChat = false
    @State private var showHiddenChats = false
    @State private var hiddenChatsUnlocked = false
    @State private var showPairAuthorize = false
    @State private var pairToken: String?
    @State private var searchText = ""
    @State private var dailyInspiration: DailyInspirationBanner.DailyInspiration?
    @State private var totalChatCount = 0
    @State private var isLoadingMore = false
    @State private var showRenameAlert = false
    @State private var renameChatId: String?
    @State private var renameChatTitle = ""
    @State private var showAuthSheet = false
    @State private var actionChat: Chat?

    /// Whether the user is currently authenticated
    private var isAuthenticated: Bool {
        authManager.state == .authenticated
    }

    private var filteredPinnedChats: [Chat] {
        let pinned = chatStore.pinnedChats
        guard !searchText.isEmpty else { return pinned }
        return pinned.filter { $0.displayTitle.localizedCaseInsensitiveContains(searchText) }
    }

    private var filteredUnpinnedChats: [Chat] {
        let unpinned = chatStore.unpinnedChats
        guard !searchText.isEmpty else { return unpinned }
        return unpinned.filter { $0.displayTitle.localizedCaseInsensitiveContains(searchText) }
    }

    private var isCompactShell: Bool {
        horizontalSizeClass == .compact
    }

    var body: some View {
        VStack(spacing: 0) {
            OpenMatesWebHeader(
                isAuthenticated: isAuthenticated,
                isChatsPanelOpen: isChatsPanelOpen,
                onToggleChats: { withAnimation(.easeInOut(duration: 0.2)) { isChatsPanelOpen.toggle() } },
                onNewChat: { showNewChatSheet = true },
                onShareChat: { showShareChat = true },
                canShareChat: selectedChatId != nil,
                onOpenSettings: { showSettings = true },
                onOpenAuth: { showAuthSheet = true }
            )

            shellContent
        }
        .background(Color.grey0)
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
            onNewChat: { showNewChatSheet = true },
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
                showNewChatSheet = true
                deepLinkHandler.pendingInspirationId = nil
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .newChat)) { _ in
            showNewChatSheet = true
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
                // Initialize offline bridge and load cached data before network
                let bridge = OfflineSyncBridge(chatStore: chatStore)
                chatStore.setBridge(bridge)
                syncBridge = bridge
                bridge.loadFromDisk()

                await loadInitialData()
                await syncInspirationToWidget()
                connectWebSocket()
            } else {
                // Unauthenticated: populate sidebar with demo chats
                loadDemoChats()
            }
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
            }
        }
        .onChange(of: pushManager.pendingChatId) { _, chatId in
            if let chatId {
                selectedChatId = chatId
                pushManager.pendingChatId = nil
            }
        }
    }

    // MARK: - Web-style shell

    @ViewBuilder
    private var appOverlays: some View {
        // Settings: right-side sliding panel matching web (not a centered modal)
        settingsSlidePanel

        if showExplore {
            appOverlay(title: AppStrings.explore, isPresented: $showExplore) {
                PublicChatListView()
            }
        }

        if showNewChatSheet {
            appOverlay(title: AppStrings.newChat, isPresented: $showNewChatSheet) {
                NewChatView { chatId in
                    selectedChatId = chatId
                    showNewChatSheet = false
                }
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

        if showAuthSheet {
            appOverlay(title: AppStrings.loginSignup, isPresented: $showAuthSheet) {
                AuthFlowView()
            }
        }

        if showRenameAlert {
            renameOverlay
        }
    }

    // MARK: - Settings slide panel (web: slides from right, 323px wide, shadow)

    private var settingsSlidePanel: some View {
        ZStack(alignment: .trailing) {
            // Dimmed backdrop — web: .active-chat-container.dimmed opacity 0.3
            if showSettings {
                Color.black.opacity(0.35)
                    .ignoresSafeArea()
                    .onTapGesture { withAnimation(.easeInOut(duration: 0.3)) { showSettings = false } }
                    .transition(.opacity)
            }

            // Settings panel — web: 323px, fixed right, translateX slide
            if showSettings {
                HStack(spacing: 0) {
                    Spacer(minLength: 0)
                    SettingsView()
                        .environmentObject(authManager)
                        .environmentObject(themeManager)
                        .frame(width: min(UIScreen.main.bounds.width - 40, 323))
                        .frame(maxHeight: .infinity)
                        .background(Color.grey0)
                        .shadow(color: .black.opacity(0.15), radius: 12, x: -4, y: 0)
                }
                .transition(.move(edge: .trailing))
                .ignoresSafeArea(.container, edges: .bottom)
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
            ZStack(alignment: .leading) {
                detailContent

                if isChatsPanelOpen {
                    Color.black.opacity(0.18)
                        .ignoresSafeArea()
                        .onTapGesture {
                            withAnimation(.easeInOut(duration: 0.2)) {
                                isChatsPanelOpen = false
                            }
                        }

                    chatsPanel
                        .frame(maxWidth: 340)
                        .transition(.move(edge: .leading).combined(with: .opacity))
                        .zIndex(1)
                }
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

                detailContent
            }
        }
    }

    @ViewBuilder
    private var detailContent: some View {
        if isAuthenticated, let chatId = selectedChatId {
            ChatView(
                chatId: chatId,
                onPreviousChat: previousChatAction(for: chatId),
                onNextChat: nextChatAction(for: chatId)
            )
        } else if !isAuthenticated, let chatId = selectedChatId {
            ChatView(
                chatId: chatId,
                bannerState: demoBannerState(for: chatId),
                bannerCreatedAt: nil,
                onPreviousChat: previousChatAction(for: chatId),
                onNextChat: nextChatAction(for: chatId)
            )
        } else if !isAuthenticated {
            WelcomeView(onLogin: { showAuthSheet = true })
        } else {
            EmptyStateView()
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

    private var chatsPanel: some View {
        VStack(spacing: 0) {
            DailyInspirationBanner(inspiration: dailyInspiration) { _ in
                showNewChatSheet = true
            }

            HStack(spacing: .spacing3) {
                Icon("search", size: 14)
                    .foregroundStyle(Color.fontTertiary)

                TextField(AppStrings.search, text: $searchText)
                    .textFieldStyle(.plain)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontPrimary)
            }
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing3)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .padding(.horizontal, .spacing5)
            .padding(.top, .spacing3)
            .padding(.bottom, .spacing2)

            ScrollView {
                LazyVStack(alignment: .leading, spacing: .spacing2) {
                    if !filteredPinnedChats.isEmpty {
                        // Web: unauthenticated sidebar uses "INTRO" header; authenticated uses "PINNED"
                        chatSectionHeader(isAuthenticated ? AppStrings.pinnedChats : AppStrings.introSection)
                        ForEach(filteredPinnedChats) { chat in
                            chatRow(chat)
                        }
                    }

                    if !filteredUnpinnedChats.isEmpty {
                        // Web: unauthenticated uses "EXAMPLE CHATS"; authenticated uses "RECENT"/"CHATS"
                        let header = isAuthenticated
                            ? (filteredPinnedChats.isEmpty ? AppStrings.chats : AppStrings.recentChats)
                            : AppStrings.exampleChatsSection
                        chatSectionHeader(header)
                        ForEach(filteredUnpinnedChats) { chat in
                            chatRow(chat)
                        }
                    } else if filteredPinnedChats.isEmpty {
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

                        Button {
                            showHiddenChats = true
                        } label: {
                            HStack(spacing: .spacing3) {
                                Icon("anonym", size: 16)
                                    .foregroundStyle(Color.fontSecondary)
                                Text(AppStrings.hiddenChats)
                                    .font(.omSmall)
                                    .foregroundStyle(Color.fontSecondary)
                                Spacer()
                            }
                            .padding(.horizontal, .spacing5)
                            .padding(.vertical, .spacing4)
                        }
                        .buttonStyle(.plain)
                    }
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

    private func chatSectionHeader(_ title: String) -> some View {
        Text(title.uppercased())
            .font(.omXs)
            .fontWeight(.semibold)
            .foregroundStyle(Color.fontTertiary)
            .padding(.horizontal, .spacing5)
            .padding(.top, .spacing4)
            .padding(.bottom, .spacing1)
    }

    @ViewBuilder
    private func chatRow(_ chat: Chat) -> some View {
        let isSelected = selectedChatId == chat.id
        Button {
            selectedChatId = chat.id
            if isCompactShell {
                withAnimation(.easeInOut(duration: 0.2)) {
                    isChatsPanelOpen = false
                }
            }
        } label: {
            ChatListRow(chat: chat)
                .background(isSelected ? Color.buttonPrimary.opacity(0.12) : Color.clear)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .contentShape(RoundedRectangle(cornerRadius: 8))
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
            // INTRO_CHATS (featured: true, pinned in sidebar)
            Chat(id: "demo-for-everyone", title: AppStrings.demoForEveryoneTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: true,
                 appId: "ai", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "demo-for-developers", title: AppStrings.demoForDevelopersTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: true,
                 appId: "code", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "demo-who-develops-openmates", title: AppStrings.demoWhoDevTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: true,
                 appId: "ai", encryptedTitle: nil, encryptedChatKey: nil),
            // Announcements newsletter chat
            Chat(id: "announcements-introducing-openmates-v09", title: AppStrings.demoAnnouncementsV09Title,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "ai", encryptedTitle: nil, encryptedChatKey: nil),
            // Legal chats (accessible via sidebar + settings)
            Chat(id: "legal-privacy", title: AppStrings.legalPrivacyTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "ai", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "legal-terms", title: AppStrings.legalTermsTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "ai", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "legal-imprint", title: AppStrings.legalImprintTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "ai", encryptedTitle: nil, encryptedChatKey: nil),
            // Example chats — real conversations (exampleChatStore.ts)
            Chat(id: "example-gigantic-airplanes", title: AppStrings.exampleGiganticAirplanesTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "ai", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "example-artemis-ii-mission", title: AppStrings.exampleArtemisMissionTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "ai", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "example-beautiful-single-page-html", title: AppStrings.exampleBeautifulHtmlTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "code", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "example-eu-chat-control-law", title: AppStrings.exampleEuChatControlTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "legal", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "example-flights-berlin-bangkok", title: AppStrings.exampleFlightsBerlinBangkokTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "travel", encryptedTitle: nil, encryptedChatKey: nil),
            Chat(id: "example-creativity-drawing-meetups-berlin", title: AppStrings.exampleCreativityDrawingTitle,
                 lastMessageAt: now, createdAt: now, updatedAt: now,
                 isArchived: false, isPinned: false,
                 appId: "events", encryptedTitle: nil, encryptedChatKey: nil),
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
            return .loaded(title: AppStrings.demoForEveryoneTitle, appId: "openmates",
                           summary: AppStrings.demoForEveryoneDescription)
        case "demo-for-developers":
            return .loaded(title: AppStrings.demoForDevelopersTitle, appId: "code",
                           summary: AppStrings.demoForDevelopersDescription)
        case "demo-who-develops-openmates":
            return .loaded(title: AppStrings.demoWhoDevTitle, appId: "ai",
                           summary: AppStrings.demoWhoDevDescription)
        // Announcements
        case "announcements-introducing-openmates-v09":
            return .loaded(title: AppStrings.demoAnnouncementsV09Title, appId: "ai",
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
            return .loaded(title: AppStrings.exampleGiganticAirplanesTitle, appId: "ai",
                           summary: AppStrings.exampleGiganticAirplanesSummary)
        case "example-artemis-ii-mission":
            return .loaded(title: AppStrings.exampleArtemisMissionTitle, appId: "ai",
                           summary: AppStrings.exampleArtemisMissionSummary)
        case "example-beautiful-single-page-html":
            return .loaded(title: AppStrings.exampleBeautifulHtmlTitle, appId: "code",
                           summary: AppStrings.exampleBeautifulHtmlSummary)
        case "example-eu-chat-control-law":
            return .loaded(title: AppStrings.exampleEuChatControlTitle, appId: "legal",
                           summary: AppStrings.exampleEuChatControlSummary)
        case "example-flights-berlin-bangkok":
            return .loaded(title: AppStrings.exampleFlightsBerlinBangkokTitle, appId: "travel",
                           summary: AppStrings.exampleFlightsBerlinBangkokSummary)
        case "example-creativity-drawing-meetups-berlin":
            return .loaded(title: AppStrings.exampleCreativityDrawingTitle, appId: "events",
                           summary: AppStrings.exampleCreativityDrawingSummary)
        default:
            return nil
        }
    }

    // MARK: - Data loading

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
                        let title: String?
                        let channelName: String?
                        let thumbnailUrl: String?
                        enum CodingKeys: String, CodingKey {
                            case title, channelName = "channel_name", thumbnailUrl = "thumbnail_url"
                        }
                    }
                    enum CodingKeys: String, CodingKey {
                        case inspirationId = "inspiration_id", phrase, title, category, video
                    }
                }
            }

            let response = try JSONDecoder().decode(Response.self, from: data)
            if let first = response.inspirations.first {
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
            print("[MainApp] Failed to sync inspiration to widget: \(error)")
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
    let onToggleChats: () -> Void
    let onNewChat: () -> Void
    let onShareChat: () -> Void
    let canShareChat: Bool
    let onOpenSettings: () -> Void
    let onOpenAuth: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: .spacing4) {
            Button(action: onToggleChats) {
                // Web: uses static/icons/menu.svg, color: var(--color-font-primary) 0.6 opacity
                Icon(isChatsPanelOpen ? "close" : "menu", size: 22)
                    .foregroundStyle(Color.fontPrimary.opacity(0.6))
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
                // Web: 44x44 circle, icon at 0.6 opacity, grey-20 hover bg
                Icon("settings", size: 22)
                    .foregroundStyle(LinearGradient.primary)
                    .frame(width: 38, height: 38)
                    .background(Color.grey10)
                    .clipShape(Circle())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("settings-button")
            .accessibilityLabel(AppStrings.settings)
        }
        .padding(.horizontal, .spacing5)
        .padding(.top, .spacing5)
        .padding(.bottom, .spacing3)
        .background(Color.grey0)
    }
}

private struct WebHamburgerIcon: View {
    let isOpen: Bool

    var body: some View {
        VStack(spacing: 5) {
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
        .foregroundStyle(Color.fontPrimary)
        .animation(.easeInOut(duration: 0.18), value: isOpen)
    }
}

private struct WebMenuDotsIcon: View {
    var body: some View {
        HStack(spacing: 3) {
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
            .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: - Welcome view for unauthenticated users

struct WelcomeView: View {
    let onLogin: () -> Void

    var body: some View {
        VStack(spacing: .spacing8) {
            Spacer()

            Image.iconOpenmates
                .resizable()
                .frame(width: 72, height: 72)

            // Brand name — intentionally not translated (proper noun, same in all locales)
            Text("OpenMates")
                .font(.omH1)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontPrimary)

            Text(LocalizationManager.shared.text("chat.select_or_new"))
                .font(.omP)
                .foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, .spacing10)

            Button(action: onLogin) {
                Text("\(AppStrings.login) / \(AppStrings.signup)")
                    .font(.omP)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontButton)
                    .padding(.horizontal, .spacing12)
                    .padding(.vertical, .spacing8)
                    .frame(minHeight: 41)
                    .background(Color.buttonPrimary)
                    .clipShape(RoundedRectangle(cornerRadius: .radius8))
                    .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
            }
            .accessibilityIdentifier("welcome-login-button")
            .padding(.top, .spacing4)

            Spacer()
        }
    }
}

// MARK: - Empty state

struct EmptyStateView: View {
    var body: some View {
        VStack(spacing: .spacing6) {
            Image.iconOpenmates
                .resizable()
                .frame(width: 48, height: 48)
                .opacity(0.5)
            Text(AppStrings.selectChatOrNew)
                .font(.omP)
                .foregroundStyle(Color.fontSecondary)
        }
    }
}

// MARK: - New chat sheet

struct NewChatView: View {
    let onChatCreated: (String) -> Void
    @State private var messageText = ""
    @State private var selectedApp: String?
    @FocusState private var isFocused: Bool

    private let popularApps = [
        ("ai", "AI Chat"), ("web", "Web Search"), ("code", "Code"),
        ("travel", "Travel"), ("news", "News"), ("mail", "Email"),
        ("maps", "Maps"), ("shopping", "Shopping"), ("events", "Events"),
        ("videos", "Videos"), ("photos", "Photos"), ("nutrition", "Nutrition"),
    ]

    var body: some View {
        VStack(spacing: .spacing6) {
            Text(AppStrings.whatToHelpWith)
                .font(.omH3).fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)

            // App selector
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 80))], spacing: .spacing4) {
                ForEach(popularApps, id: \.0) { appId, name in
                    Button {
                        selectedApp = selectedApp == appId ? nil : appId
                    } label: {
                        VStack(spacing: .spacing2) {
                            AppIconView(appId: appId, size: 40)
                                .overlay(
                                    selectedApp == appId ?
                                    Circle().stroke(Color.buttonPrimary, lineWidth: 2)
                                        .frame(width: 44, height: 44) : nil
                                )
                            Text(name)
                                .font(.omTiny)
                                .foregroundStyle(Color.fontSecondary)
                                .lineLimit(1)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal)

            // Message input — pill style matching ChatView.inputBar and fields.css
            HStack(alignment: .bottom, spacing: .spacing3) {
                TextField(AppStrings.startTyping, text: $messageText, axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(.omP)
                    .lineLimit(1...4)
                    .padding(.horizontal, .spacing8)
                    .padding(.vertical, .spacing6)
                    .background(Color.grey0)
                    .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                    .overlay(
                        RoundedRectangle(cornerRadius: .radiusFull)
                            .stroke(isFocused ? Color.buttonPrimary : Color.grey30, lineWidth: 2)
                    )
                    .shadow(
                        color: isFocused ? Color.buttonPrimary.opacity(0.22) : .clear,
                        radius: 3, x: 0, y: 0
                    )
                    .shadow(
                        color: isFocused ? .black.opacity(0.08) : .black.opacity(0.05),
                        radius: isFocused ? 12 : 2, x: 0, y: 4
                    )
                    .tint(Color.buttonPrimary)
                    .focused($isFocused)

                Button(action: createChat) {
                    Icon("up", size: 16)
                        .foregroundStyle(messageText.isEmpty ? Color.fontTertiary : Color.fontButton)
                        .frame(width: 32, height: 32)
                        .background(messageText.isEmpty ? Color.grey20 : Color.buttonPrimary)
                        .clipShape(Circle())
                }
                .buttonStyle(.plain)
                .disabled(messageText.isEmpty)
            }
            .padding(.horizontal)

            Spacer()
        }
        .padding(.top, .spacing8)
        .onAppear { isFocused = true }
    }

    private func createChat() {
        let chatId = UUID().uuidString

        Task {
            let body: [String: Any] = [
                "chat_id": chatId,
                "message": [
                    "message_id": UUID().uuidString,
                    "role": "user",
                    "content": messageText,
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
                print("[NewChat] Failed to create chat: \(error)")
            }
        }
    }
}
