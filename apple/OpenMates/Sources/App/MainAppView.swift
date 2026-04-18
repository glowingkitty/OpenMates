// Main app shell after authentication.
// Uses NavigationSplitView for adaptive layout across iPhone, iPad, and Mac.
// Sidebar shows chat list; detail shows active chat or empty state.
// Manages WebSocket connection and phased sync lifecycle.

import SwiftUI
import WidgetKit
import CoreSpotlight

struct MainAppView: View {
    @EnvironmentObject var authManager: AuthManager
    @EnvironmentObject var pushManager: PushNotificationManager
    @StateObject private var chatStore = ChatStore()
    @StateObject private var wsManager = WebSocketManager()
    @StateObject private var deepLinkHandler = DeepLinkHandler()
    @StateObject private var incognitoManager = IncognitoManager()
    @StateObject private var handoffManager = HandoffManager()
    @State private var syncBridge: OfflineSyncBridge?
    @State private var selectedChatId: String?
    @State private var columnVisibility: NavigationSplitViewVisibility = .automatic
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

    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            VStack(spacing: 0) {
                DailyInspirationBanner(inspiration: dailyInspiration) { text in
                    showNewChatSheet = true
                }
                sidebar
            }
        } detail: {
            if let chatId = selectedChatId {
                ChatView(chatId: chatId)
            } else {
                EmptyStateView()
            }
        }
        .sheet(isPresented: $showSettings) {
            SettingsView()
        }
        .sheet(isPresented: $showExplore) {
            NavigationStack {
                PublicChatListView()
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button(AppStrings.done) { showExplore = false }
                        }
                    }
            }
        }
        .sheet(isPresented: $showNewChatSheet) {
            NewChatView { chatId in
                selectedChatId = chatId
                showNewChatSheet = false
            }
        }
        .sheet(isPresented: $showSearch) {
            ChatSearchView { chatId in
                selectedChatId = chatId
            }
        }
        .sheet(isPresented: $showShareChat) {
            if let chatId = selectedChatId {
                ChatShareView(chatId: chatId)
            }
        }
        .sheet(isPresented: $showHiddenChats) {
            NavigationStack {
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
        .overlay {
            ToastOverlay()
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
        .sheet(isPresented: $showPairAuthorize) {
            if let pairToken {
                CLIPairAuthorizeView(token: pairToken)
            }
        }
        .alert(AppStrings.renameChat, isPresented: $showRenameAlert) {
            TextField(AppStrings.chatTitle, text: $renameChatTitle)
            Button(AppStrings.rename) { submitRename() }
            Button(AppStrings.cancel, role: .cancel) {}
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
        #if os(iOS)
        .onReceive(NotificationCenter.default.publisher(for: .handoffChatReceived)) { notification in
            if let chatId = notification.userInfo?["chatId"] as? String {
                selectedChatId = chatId
            }
        }
        #endif
        .task {
            // Initialize offline bridge and load cached data before network
            let bridge = OfflineSyncBridge(chatStore: chatStore)
            chatStore.setBridge(bridge)
            syncBridge = bridge
            bridge.loadFromDisk()

            await loadInitialData()
            await syncInspirationToWidget()
            connectWebSocket()
        }
        .onReceive(NotificationCenter.default.publisher(for: .wsMessageReceived)) { notification in
            handleChatUpdate(notification)
        }
        .onReceive(NotificationCenter.default.publisher(for: .wsEmbedUpdate)) { notification in
            handleEmbedUpdate(notification)
        }
        .onChange(of: pushManager.pendingChatId) { _, chatId in
            if let chatId {
                selectedChatId = chatId
                pushManager.pendingChatId = nil
            }
        }
    }

    // MARK: - Sidebar

    private var sidebar: some View {
        List(selection: $selectedChatId) {
            if !filteredPinnedChats.isEmpty {
                Section(AppStrings.pinnedChats) {
                    ForEach(filteredPinnedChats) { chat in
                        chatRow(chat)
                    }
                }
            }

            Section(filteredPinnedChats.isEmpty ? "" : AppStrings.recentChats) {
                ForEach(filteredUnpinnedChats) { chat in
                    chatRow(chat)
                }
            }

            // Pagination
            if chatStore.chats.count < totalChatCount {
                ShowMoreChatsButton(
                    totalCount: totalChatCount,
                    loadedCount: chatStore.chats.count,
                    isLoading: isLoadingMore,
                    onLoadMore: { loadMoreChats() }
                )
            }

            // Hidden chats section
            Section {
                Button {
                    showHiddenChats = true
                } label: {
                    Label(AppStrings.hiddenChats, systemImage: "eye.slash")
                        .foregroundStyle(Color.fontSecondary)
                }
            }
        }
        .listStyle(.sidebar)
        .searchable(text: $searchText, prompt: AppStrings.search)
        .navigationTitle(AppStrings.chats)
        #if os(iOS)
        .navigationBarTitleDisplayMode(.large)
        #endif
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button { showNewChatSheet = true } label: {
                    Image(systemName: "square.and.pencil")
                }
                .accessibilityIdentifier("new-chat-button")
                .accessibilityLabel(AppStrings.newChat)
                .accessibilityHint("Start a new conversation")
            }
            ToolbarItem(placement: .secondaryAction) {
                Button { showSearch = true } label: {
                    Label(AppStrings.search, systemImage: "magnifyingglass")
                }
                .accessibilityIdentifier("search-button")
            }
            ToolbarItem(placement: .secondaryAction) {
                Button { showExplore = true } label: {
                    Label(AppStrings.explore, systemImage: "globe")
                }
            }
            #if os(iOS)
            ToolbarItem(placement: .navigationBarLeading) {
                Button { showSettings = true } label: {
                    Image(systemName: "gearshape")
                }
                .accessibilityIdentifier("settings-button")
                .accessibilityLabel(AppStrings.settings)
            }
            #endif
        }
        .refreshable {
            await loadInitialData()
        }
    }

    // MARK: - Chat row with context menu

    private func chatRow(_ chat: Chat) -> some View {
        ChatListRow(chat: chat)
            .tag(chat.id)
            .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                Button(role: .destructive) { deleteChat(chat.id) } label: {
                    Label(AppStrings.delete, systemImage: "trash")
                }
            }
            .contextMenu {
                ChatContextMenuActions(
                    chat: chat,
                    onPin: { pinChat(chat) },
                    onHide: { hideChat(chat.id) },
                    onShare: {
                        selectedChatId = chat.id
                        showShareChat = true
                    },
                    onArchive: { archiveChat(chat.id) },
                    onRename: { renameChat(chat) },
                    onDelete: { deleteChat(chat.id) }
                )
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
    @Environment(\.dismiss) var dismiss
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
        NavigationStack {
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

                // Message input
                HStack(alignment: .bottom, spacing: .spacing3) {
                    TextField(AppStrings.startTyping, text: $messageText, axis: .vertical)
                        .textFieldStyle(.plain)
                        .font(.omP)
                        .lineLimit(1...4)
                        .padding(.spacing4)
                        .background(Color.grey10)
                        .clipShape(RoundedRectangle(cornerRadius: .radius5))
                        .focused($isFocused)

                    Button { createChat() } label: {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.system(size: 32))
                            .foregroundStyle(messageText.isEmpty ? Color.fontTertiary : Color.buttonPrimary)
                    }
                    .disabled(messageText.isEmpty)
                }
                .padding(.horizontal)

                Spacer()
            }
            .padding(.top, .spacing8)
            .navigationTitle(AppStrings.newChat)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(AppStrings.cancel) { dismiss() }
                }
            }
        }
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
