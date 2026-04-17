// Main app shell after authentication.
// Uses NavigationSplitView for adaptive layout across iPhone, iPad, and Mac.
// Sidebar shows chat list; detail shows active chat or empty state.
// Manages WebSocket connection and phased sync lifecycle.

import SwiftUI

struct MainAppView: View {
    @EnvironmentObject var authManager: AuthManager
    @EnvironmentObject var pushManager: PushNotificationManager
    @StateObject private var chatStore = ChatStore()
    @StateObject private var wsManager = WebSocketManager()
    @StateObject private var deepLinkHandler = DeepLinkHandler()
    @StateObject private var incognitoManager = IncognitoManager()
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
    @State private var searchText = ""
    @State private var dailyInspiration: DailyInspirationBanner.DailyInspiration?
    @State private var totalChatCount = 0
    @State private var isLoadingMore = false

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
                            Button("Done") { showExplore = false }
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
                    Text("Hidden chats loaded")
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
        .onChange(of: deepLinkHandler.pendingChatId) { _, chatId in
            if let chatId {
                selectedChatId = chatId
                deepLinkHandler.clearPending()
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .newChat)) { _ in
            showNewChatSheet = true
        }
        .task {
            // Initialize offline bridge and load cached data before network
            let bridge = OfflineSyncBridge(chatStore: chatStore)
            chatStore.setBridge(bridge)
            syncBridge = bridge
            bridge.loadFromDisk()

            await loadInitialData()
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
                Section("Pinned") {
                    ForEach(filteredPinnedChats) { chat in
                        chatRow(chat)
                    }
                }
            }

            Section(filteredPinnedChats.isEmpty ? "" : "Recent") {
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
                    Label("Hidden Chats", systemImage: "eye.slash")
                        .foregroundStyle(Color.fontSecondary)
                }
            }
        }
        .listStyle(.sidebar)
        .searchable(text: $searchText, prompt: "Search chats")
        .navigationTitle("Chats")
        #if os(iOS)
        .navigationBarTitleDisplayMode(.large)
        #endif
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button { showNewChatSheet = true } label: {
                    Image(systemName: "square.and.pencil")
                }
                .accessibilityIdentifier("new-chat-button")
                .accessibilityLabel("New chat")
                .accessibilityHint("Start a new conversation")
            }
            ToolbarItem(placement: .secondaryAction) {
                Button { showSearch = true } label: {
                    Label("Search", systemImage: "magnifyingglass")
                }
                .accessibilityIdentifier("search-button")
            }
            ToolbarItem(placement: .secondaryAction) {
                Button { showExplore = true } label: {
                    Label("Explore", systemImage: "globe")
                }
            }
            #if os(iOS)
            ToolbarItem(placement: .navigationBarLeading) {
                Button { showSettings = true } label: {
                    Image(systemName: "gearshape")
                }
                .accessibilityIdentifier("settings-button")
                .accessibilityLabel("Settings")
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
                    Label("Delete", systemImage: "trash")
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
                    onRename: { },
                    onDelete: { deleteChat(chat.id) }
                )
            }
    }

    // MARK: - Data loading

    private func loadInitialData() async {
        do {
            let response: ChatListResponse = try await APIClient.shared.request(.get, path: "/v1/chats")
            for chat in response.chats {
                chatStore.upsertChat(chat)
            }
        } catch {
            print("[MainApp] Failed to load chats: \(error)")
        }
    }

    private func deleteChat(_ id: String) {
        Task {
            do {
                let _: Data = try await APIClient.shared.request(.delete, path: "/v1/chats/\(id)")
                chatStore.removeChat(id)
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

    private func handleEmbedUpdate(_ notification: Notification) {}
}

// MARK: - Empty state

struct EmptyStateView: View {
    var body: some View {
        VStack(spacing: .spacing6) {
            Image.iconOpenmates
                .resizable()
                .frame(width: 48, height: 48)
                .opacity(0.5)
            Text("Select a chat or start a new one")
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
                Text("What would you like to help with?")
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
                    TextField("Start typing...", text: $messageText, axis: .vertical)
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
            .navigationTitle("New Chat")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
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
