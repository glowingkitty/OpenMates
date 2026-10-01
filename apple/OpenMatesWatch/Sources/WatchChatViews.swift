// Watch chat list, transcript, and composer shell.
// Provides the dark Watch-native chat surface for the standalone watchOS client
// without using stock List/Form/navigation chrome. Runtime state is supplied by
// WatchChatRuntime so this file stays visual and platform-specific.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/ChatHistory.svelte
//          frontend/packages/ui/src/components/ChatMessage.svelte
//          frontend/packages/ui/src/components/embeds/EmbedInlineLink.svelte
//          frontend/packages/ui/src/components/enter_message/MessageInput.svelte
// CSS:     frontend/packages/ui/src/styles/chat.css
//          frontend/packages/ui/src/styles/fields.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.browse-search-open, apple-watch.chats.compact-layout
// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.action.routing-coherent

import AVFoundation
import SwiftUI

@MainActor
private final class WatchAudioRecorder: ObservableObject {
    @Published private(set) var isRecording = false
    @Published private(set) var duration: TimeInterval = 0
    @Published var errorMessage: String?

    private var audioRecorder: AVAudioRecorder?
    private var recordingURL: URL?
    private var timer: Timer?

    func requestPermission() async -> Bool {
        await withCheckedContinuation { continuation in
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                continuation.resume(returning: granted)
            }
        }
    }

    func startRecording() async {
        errorMessage = nil
        guard await requestPermission() else {
            errorMessage = WatchStrings.microphoneBlocked
            return
        }

        do {
            try AVAudioSession.sharedInstance().setCategory(.playAndRecord, mode: .default)
            try AVAudioSession.sharedInstance().setActive(true)
        } catch {
            errorMessage = error.localizedDescription
            return
        }

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("watch-recording-\(Int(Date().timeIntervalSince1970)).m4a")
        recordingURL = url
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 44_100.0,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
        ]

        do {
            audioRecorder = try AVAudioRecorder(url: url, settings: settings)
            guard audioRecorder?.record() == true else {
                errorMessage = WatchStrings.microphoneBlocked
                return
            }
            isRecording = true
            duration = 0
            timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
                Task { @MainActor in self?.duration += 0.1 }
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func stopRecording() -> URL? {
        guard isRecording else { return nil }
        audioRecorder?.stop()
        timer?.invalidate()
        timer = nil
        isRecording = false
        return recordingURL
    }

    func cancelRecording() {
        if let url = stopRecording() {
            try? FileManager.default.removeItem(at: url)
        }
        recordingURL = nil
        duration = 0
    }
}

@MainActor
private enum WatchChatCopy {
    static var chats: String { WatchLocalization.text("common.chats") }
    static var search: String { WatchLocalization.text("activity.search") }
    static var settings: String { WatchLocalization.text("common.settings") }
    static var chatsLoadFailed: String {
        WatchLocalization.text("common.detail_load_error", replacements: ["item": chats])
    }
    static var recording: String { WatchLocalization.text("enter_message.record_audio.recording") }
    static func welcomeGreeting(username: String?) -> String {
        guard let username = username?.trimmingCharacters(in: .whitespacesAndNewlines), !username.isEmpty else {
            return WatchLocalization.text("chat.welcome.hey_guest")
        }
        return WatchLocalization.text("chat.welcome.hey_user", replacements: ["username": username])
    }
    static var welcomePrompt: String { WatchLocalization.text("watch.chats.welcome_prompt") }
}

// Watch artboards use a dedicated black, blue, and teal palette at 184 × 224 pt.
private enum WatchChatPalette {
    static let background = Color.black
    static let foreground = Color.white
    static let muted = Color(red: 0.68, green: 0.69, blue: 0.72)
    static let surface = Color(red: 0.18, green: 0.19, blue: 0.20)
    static let blue = Color(red: 79.0 / 255, green: 117.0 / 255, blue: 216.0 / 255)
    static let teal = Color(red: 0.02, green: 0.69, blue: 0.57)
    static let orange = Color(red: 1.0, green: 0.33, blue: 0.24)
    static let recordingGradient = LinearGradient(
        colors: [Color(red: 0.02, green: 0.78, blue: 0.64), Color(red: 0.02, green: 0.65, blue: 0.53)],
        startPoint: .top, endPoint: .bottom
    )
}

struct WatchChatShellView: View {
    @StateObject private var runtime: WatchChatRuntime
    @StateObject private var phoneBridge = WatchPhoneLoginBridge.shared
    private let startsNetworkTasks: Bool
    private let seedsRemoteDraftFixture: Bool
    private let onOpenHub: (() -> Void)?
    private let onOpenSettings: (() -> Void)?
    private let initialSearchText: String?
    private let showsRecordingFixture: Bool
    private let currentUsername: String?
    private let notificationRoute: WatchNotificationRoute?
    private let isVisible: Bool
    private let fixtureNotificationChatID: String?
    @State private var networkReady = false
    @State private var resolvingRouteID: UUID?

    init(currentUserId: String?, currentUsername: String? = nil, webSocketToken: String?,
         notificationRoute: WatchNotificationRoute? = nil, isVisible: Bool = true,
         onOpenHub: (() -> Void)? = nil, onOpenSettings: (() -> Void)? = nil) {
        _runtime = StateObject(wrappedValue: WatchChatRuntime(
            currentUserId: currentUserId,
            syncSession: WatchSyncSession(
                sessionId: WatchCompatibleSession.nativeSessionId,
                token: webSocketToken
            )
        ))
        startsNetworkTasks = true
        seedsRemoteDraftFixture = false
        self.onOpenHub = onOpenHub
        self.onOpenSettings = onOpenSettings
        initialSearchText = nil
        showsRecordingFixture = false
        self.currentUsername = currentUsername
        self.notificationRoute = notificationRoute
        self.isVisible = isVisible
        self.fixtureNotificationChatID = nil
    }

#if DEBUG
    init(uiTestSnapshot: WatchChatSnapshot, selectedChatId: String?, initialDraft: String? = nil, remoteDraftFixture: Bool = false, initialSearchText: String? = nil, showsRecordingFixture: Bool = false, currentUsername: String? = nil, onOpenHub: (() -> Void)? = nil, onOpenSettings: (() -> Void)? = nil, fixtureNotificationChatID: String? = nil) {
        _runtime = StateObject(wrappedValue: WatchChatRuntime(
            uiTestSnapshot: uiTestSnapshot,
            selectedChatId: selectedChatId, initialDraft: initialDraft
        ))
        startsNetworkTasks = false
        seedsRemoteDraftFixture = remoteDraftFixture
        self.onOpenHub = onOpenHub
        self.onOpenSettings = onOpenSettings
        self.initialSearchText = initialSearchText
        self.showsRecordingFixture = showsRecordingFixture
        self.currentUsername = currentUsername
        self.notificationRoute = nil
        self.isVisible = true
        self.fixtureNotificationChatID = fixtureNotificationChatID
    }
#endif

    var body: some View {
        ZStack {
            if runtime.selectedChatId == nil {
                WatchChatListView(runtime: runtime, onOpenHub: onOpenHub,
                                  onOpenSettings: onOpenSettings, initialSearchText: initialSearchText)
            } else {
                WatchChatThreadView(runtime: runtime, currentUsername: currentUsername, showsRecordingFixture: showsRecordingFixture)
                    .environmentObject(phoneBridge)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(WatchChatPalette.background)
        .ignoresSafeArea(edges: .bottom)
        .task {
#if DEBUG
            if seedsRemoteDraftFixture { await runtime.seedRemoteDraftPreview() }
            if let fixtureNotificationChatID {
                _ = await runtime.openNotificationChat(chatID: fixtureNotificationChatID)
            }
#endif
            guard startsNetworkTasks else { return }
            phoneBridge.start(onApproval: { _ in }, onAcknowledgment: { _ in })
            await runtime.loadCachedSnapshot()
            await runtime.startRealtimeSync()
            await runtime.refresh()
            networkReady = true
        }
        .task(id: networkReady ? notificationRoute?.id : nil) {
            await resolveNotificationRoute()
        }
        .onChange(of: runtime.isSyncing) { _, syncing in
            if !syncing { Task { await resolveNotificationRoute() } }
        }
        .onChange(of: runtime.selectedChatId) { _, chatID in
            if startsNetworkTasks { WatchPushNotificationManager.shared.viewedChatID = isVisible ? chatID : nil }
        }
        .onChange(of: isVisible) { _, visible in
            if startsNetworkTasks { WatchPushNotificationManager.shared.viewedChatID = visible ? runtime.selectedChatId : nil }
        }
        .onDisappear {
            if startsNetworkTasks {
                WatchPushNotificationManager.shared.viewedChatID = nil
                Task { await runtime.flushDraftAndStop() }
            }
        }
    }

    @MainActor
    private func resolveNotificationRoute() async {
        guard networkReady, let notificationRoute, resolvingRouteID != notificationRoute.id,
              WatchPushNotificationManager.shared.permitsOpen(notificationRoute) else { return }
        resolvingRouteID = notificationRoute.id
        defer { if resolvingRouteID == notificationRoute.id { resolvingRouteID = nil } }
        let result = await runtime.openNotificationChat(chatID: notificationRoute.chatID)
        guard WatchPushNotificationManager.shared.permitsOpen(notificationRoute) else { return }
        if result == .opened || result == .unavailable {
            WatchPushNotificationManager.shared.consume(notificationRoute)
        }
        WatchPushNotificationManager.shared.viewedChatID = isVisible ? runtime.selectedChatId : nil
    }
}

private struct WatchChatListView: View {
    @ObservedObject var runtime: WatchChatRuntime
    let onOpenHub: (() -> Void)?
    let onOpenSettings: (() -> Void)?
    @State private var isSearching: Bool
    @State private var searchText: String

    init(runtime: WatchChatRuntime, onOpenHub: (() -> Void)?, onOpenSettings: (() -> Void)?, initialSearchText: String?) {
        self.runtime = runtime
        self.onOpenHub = onOpenHub
        self.onOpenSettings = onOpenSettings
        _isSearching = State(initialValue: initialSearchText != nil)
        _searchText = State(initialValue: initialSearchText ?? "")
    }

    private var visibleChats: [WatchChatSummary] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return runtime.chats }
        return runtime.chats.filter {
            ($0.title ?? "").localizedCaseInsensitiveContains(query)
                || ($0.preview ?? "").localizedCaseInsensitiveContains(query)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            Button {
                onOpenHub?()
            } label: {
                HStack(spacing: 12) {
                    Image(systemName: "bubble.left.and.bubble.right.fill")
                        .font(.system(size: 18, weight: .semibold))
                    Image(systemName: "arrowtriangle.down.fill")
                        .font(.system(size: 18))
                }
                .foregroundStyle(WatchChatPalette.foreground)
                .frame(width: 95, height: 37)
                .background(
                    LinearGradient(
                        colors: [Color(red: 0.30, green: 0.43, blue: 0.81), Color(red: 0.34, green: 0.52, blue: 0.91)],
                        startPoint: .topLeading, endPoint: .bottomTrailing
                    ), in: Capsule()
                )
            }
            .buttonStyle(.plain)
            .frame(maxWidth: .infinity, alignment: .leading)
            .frame(height: 49)
            .padding(.leading, .spacing4)
            .background(WatchChatPalette.background)
            .accessibilityLabel(WatchChatCopy.chats)
            .accessibilityIdentifier("watch-chats-heading")
            .zIndex(1)

            ScrollView {
                LazyVStack(alignment: .leading, spacing: .spacing3) {
                    HStack(spacing: 0) {
                        Button {
                            isSearching.toggle()
                            if !isSearching { searchText = "" }
                        } label: {
                            Image(systemName: "magnifyingglass")
                                .font(.system(size: 24))
                                .frame(maxWidth: .infinity, minHeight: 30)
                        }
                        .accessibilityLabel(WatchChatCopy.search)
                        .accessibilityIdentifier("watch-chat-search-button")

                        Button {
                            Task { await runtime.createNewChat() }
                        } label: {
                            Image(systemName: "square.and.pencil")
                                .font(.system(size: 24))
                                .frame(maxWidth: .infinity, minHeight: 30)
                        }
                        .accessibilityLabel(WatchStrings.newChat)
                        .accessibilityIdentifier("watch-new-chat-button")

                        Button {
                            onOpenSettings?()
                        } label: {
                            Image(systemName: "gearshape.fill")
                                .font(.system(size: 24))
                                .frame(maxWidth: .infinity, minHeight: 30)
                        }
                        .disabled(onOpenSettings == nil)
                        .accessibilityLabel(WatchChatCopy.settings)
                        .accessibilityIdentifier("watch-chat-settings-button")
                    }
                    .foregroundStyle(WatchChatPalette.blue)
                    .buttonStyle(.plain)
                    .padding(.top, 27)

                    // The first conversation sits below the three large controls
                    // in the 184-point Figma Watch frame.
                    Color.clear.frame(height: 25)

                    if isSearching {
                        TextField(WatchChatCopy.search, text: $searchText)
                            .font(.omXs)
                            .foregroundStyle(WatchChatPalette.foreground)
                            .tint(WatchChatPalette.blue)
                            .padding(.horizontal, .spacing3)
                            .frame(height: 28)
                            .background(WatchChatPalette.surface, in: Capsule())
                            .accessibilityIdentifier("watch-chat-search-input")
                    }

                    if runtime.isOffline {
                        WatchStatusPill(text: WatchStrings.offlineBanner)
                    }

                    if runtime.chatLoadFailed && !runtime.isOffline {
                        WatchStatusPill(text: WatchChatCopy.chatsLoadFailed)
                            .accessibilityIdentifier("watch-chat-load-error")
                        Button {
                            Task { await runtime.refresh() }
                        } label: {
                            Text(WatchStrings.retry)
                                .font(.omXs)
                                .foregroundStyle(WatchChatPalette.foreground)
                                .padding(.horizontal, .spacing4)
                                .frame(minHeight: 28)
                                .background(WatchChatPalette.blue, in: Capsule())
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("watch-chat-load-retry")
                    }

                    if runtime.unavailableChatCount > 0 {
                        WatchStatusPill(text: WatchLocalization.text("workflows.builder.chats_unavailable"))
                            .accessibilityIdentifier("watch-chat-unavailable")
                    }

                    if runtime.chats.isEmpty && !runtime.isSyncing && !runtime.isOffline && !runtime.chatLoadFailed && runtime.unavailableChatCount == 0 {
                        Text(WatchStrings.noChats)
                            .font(.omSmall)
                            .foregroundStyle(Color.grey0.opacity(0.76))
                            .frame(maxWidth: .infinity, alignment: .center)
                            .padding(.vertical, .spacing8)
                            .accessibilityIdentifier("watch-chat-empty")
                    }

                    ForEach(visibleChats) { chat in
                        Button {
                            Task { await runtime.openChat(chat) }
                        } label: {
                            WatchChatRow(chat: chat)
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("watch-chat-row-\(chat.id)")
                    }
                }
                .padding(.horizontal, .spacing4)
                .padding(.bottom, .spacing5)
            }
            .accessibilityIdentifier("watch-chat-list")
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(WatchChatPalette.background)
        .ignoresSafeArea(edges: .top)
    }
}

private struct WatchChatThreadView: View {
    @ObservedObject var runtime: WatchChatRuntime
    let currentUsername: String?
    @EnvironmentObject private var phoneBridge: WatchPhoneLoginBridge
    @StateObject private var audioRecorder = WatchAudioRecorder()
    @State private var draft = ""
    @State private var isSending = false
    @State private var pendingRecording: (url: URL, duration: TimeInterval)?
    @State private var recordingPreviewActive: Bool

    init(runtime: WatchChatRuntime, currentUsername: String? = nil, showsRecordingFixture: Bool = false) {
        self.runtime = runtime
        self.currentUsername = currentUsername
        _recordingPreviewActive = State(initialValue: showsRecordingFixture)
        _draft = State(initialValue: runtime.selectedChatId.flatMap { runtime.composerDrafts[$0] } ?? "")
    }

    var body: some View {
        ZStack {
            if audioRecorder.isRecording || recordingPreviewActive {
                recordingView
            } else {
                threadView
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(WatchChatPalette.background)
        .ignoresSafeArea(edges: .top)
        .onChange(of: draft) { _, text in
            if let chatId = runtime.selectedChatId, runtime.composerDrafts[chatId] != text { runtime.updateComposerDraft(text, chatId: chatId) }
        }
        .onChange(of: runtime.composerDrafts) { _, drafts in
            if let chatId = runtime.selectedChatId, let restored = drafts[chatId], restored != draft {
                draft = restored
            }
        }
    }

    private var threadView: some View {
        VStack(spacing: 0) {
            navigationHeader

            ScrollView {
                LazyVStack(spacing: .spacing3) {
                    if runtime.selectedMessages.isEmpty {
                        emptyChatWelcome
                    }
                    ForEach(runtime.selectedMessages) { message in
                        WatchMessageBubble(message: runtime.messageWithHydratedEmbeds(message)) { model in
                            sendEmbedOpenNotification(model)
                        }
                    }
                }
                .padding(.horizontal, .spacing4)
                .padding(.bottom, .spacing2)
            }
            .accessibilityIdentifier("watch-chat-shell")

            HStack(spacing: .spacing2) {
                Image(systemName: "keyboard")
                    .font(.omSmall)
                    .foregroundStyle(WatchChatPalette.blue)
                    .accessibilityHidden(true)
                TextField(WatchStrings.messagePlaceholder, text: $draft)
                    .textFieldStyle(.plain)
                    .controlSize(.small)
                    .font(.omXs)
                    .foregroundStyle(WatchChatPalette.foreground)
                    .tint(WatchChatPalette.blue)
                    .frame(height: 38)
                    .clipped()
                    .contentShape(Rectangle())
                    .disabled(isSending)
                    .accessibilityIdentifier("watch-message-input")

                if draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    Button {
                        Task { await audioRecorder.startRecording() }
                    } label: {
                        Image(systemName: "mic.fill")
                            .font(.omSmall)
                            .foregroundStyle(WatchChatPalette.blue)
                    }
                    .buttonStyle(.plain)
                    .disabled(isSending)
                    .accessibilityIdentifier("watch-audio-record-button")
                } else {
                    Button {
                        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
                        guard !text.isEmpty else { return }
                        isSending = true
                        Task {
                            defer { isSending = false }
                            if await runtime.sendText(text), draft.trimmingCharacters(in: .whitespacesAndNewlines) == text { draft = "" }
                        }
                    } label: {
                        Text(WatchStrings.send)
                            .font(.omMicro)
                            .fontWeight(.semibold)
                            .foregroundStyle(WatchChatPalette.foreground)
                            .padding(.horizontal, .spacing2)
                            .padding(.vertical, .spacing1)
                            .background(WatchChatPalette.blue, in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("watch-message-send")
                }
            }
            .padding(.horizontal, .spacing4)
            .frame(height: 38)
            .background(WatchChatPalette.surface, in: Capsule())
            .clipShape(Capsule())
            .padding(.horizontal, .spacing4)

            if let errorMessage = audioRecorder.errorMessage ?? runtime.errorMessage, !errorMessage.isEmpty {
                WatchStatusPill(text: errorMessage)
                    .padding(.horizontal, .spacing4)
                    .accessibilityIdentifier("watch-audio-error")
            }

            if pendingRecording != nil {
                Button(WatchStrings.retry) { Task { await retryRecording() } }
                    .font(.omXs)
                    .foregroundStyle(WatchChatPalette.blue)
                    .disabled(isSending)
                    .accessibilityIdentifier("watch-audio-retry-button")
            }

            ForEach(runtime.pendingAudioEmbeds) { embed in
                WatchPendingAudioEmbedView(embed: embed)
                    .padding(.horizontal, .spacing4)
            }
        }
        .padding(.bottom, .spacing4)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var navigationHeader: some View {
        HStack(spacing: 2) {
            Button {
                Task { await runtime.leaveChat() }
            } label: {
                HStack(spacing: 2) {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(WatchChatPalette.background)
                        .frame(width: 20, height: 20)
                        .background(WatchChatPalette.blue, in: Circle())
                    Text(WatchChatCopy.chats)
                        .font(.system(size: 17, weight: .medium))
                        .foregroundStyle(WatchChatPalette.blue)
                }
                // watchOS reserves the top 38 points for the status window.
                // The visible control matches Figma's top row; its hit target
                // extends below that window so taps reach this button.
                .frame(height: 76, alignment: .top)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(WatchStrings.back)
            .accessibilityIdentifier("watch-chat-back")
            .padding(.bottom, -56)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, .spacing4)
        .padding(.top, .spacing4)
        .zIndex(1)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(runtime.selectedChat?.title ?? WatchStrings.untitledChat)
        .accessibilityIdentifier("watch-chat-thread")
    }

    private var emptyChatWelcome: some View {
        VStack(spacing: 21) {
            Image(systemName: "phone.fill")
                .font(.system(size: 30, weight: .semibold))
                .foregroundStyle(WatchChatPalette.blue)
                .accessibilityHidden(true)
            VStack(spacing: 0) {
                Text(WatchChatCopy.welcomeGreeting(username: currentUsername))
                Text(WatchChatCopy.welcomePrompt)
            }
            .font(.custom(FontRegistration.fontFamily, size: 14).weight(.bold))
            .foregroundStyle(WatchChatPalette.foreground)
            .multilineTextAlignment(.center)
            .frame(maxWidth: 120)
            .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 6)
    }

    private var recordingView: some View {
        VStack(spacing: 3) {
            HStack(spacing: 2) {
                Button {
                    recordingPreviewActive = false
                    audioRecorder.cancelRecording()
                    Task { await runtime.leaveChat() }
                } label: {
                    HStack(spacing: 2) {
                        Image(systemName: "chevron.left")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundStyle(WatchChatPalette.background)
                            .frame(width: 20, height: 20)
                            .background(WatchChatPalette.blue, in: Circle())
                        Text(recordingPreviewActive ? WatchStrings.newChat : (runtime.selectedChat?.title ?? WatchStrings.newChat))
                            .font(.system(size: 17, weight: .medium))
                            .foregroundStyle(WatchChatPalette.blue)
                    }
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("watch-audio-back-button")
                Spacer(minLength: 0)
            }
            .padding(.horizontal, .spacing4)
            .frame(height: 31)

            recordingCard
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(WatchChatPalette.background)
    }

    private var recordingCard: some View {
        VStack(spacing: 0) {
            HStack(spacing: 5.5) {
                ForEach(0..<17, id: \.self) { index in
                    Capsule()
                        .fill(WatchChatPalette.foreground)
                        .frame(width: 3, height: CGFloat([12, 22, 16, 29, 17, 26, 12][index % 7]))
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: 31)
            .padding(.top, 8)
            .accessibilityHidden(true)

            Text(WatchChatCopy.recording)
                .font(.custom(FontRegistration.fontFamily, size: 14).weight(.bold))
                .foregroundStyle(WatchChatPalette.foreground)
                .multilineTextAlignment(.center)
                .lineLimit(2)
                .frame(height: 28, alignment: .top)
                .padding(.top, 12)

            Text(String(format: "%02d:%02d", Int(recordingPreviewActive ? 1 : audioRecorder.duration) / 60, Int(recordingPreviewActive ? 1 : audioRecorder.duration) % 60))
                .font(.custom(FontRegistration.fontFamily, size: 16).weight(.bold))
                .foregroundStyle(WatchChatPalette.foreground)
                .frame(width: 84, height: 31)
                .background(Color.red, in: Capsule())
                .padding(.top, 12)
                .accessibilityIdentifier("watch-audio-recording-duration")

            Spacer(minLength: 0)

            HStack(spacing: 8) {
                Button {
                    recordingPreviewActive = false
                    audioRecorder.cancelRecording()
                } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 28, weight: .medium))
                        .foregroundStyle(WatchChatPalette.foreground)
                        .frame(width: 42, height: 42)
                        .background(WatchChatPalette.teal, in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(WatchStrings.cancel)
                .accessibilityIdentifier("watch-audio-cancel-button")

                Button {
                    Task { await sendRecording() }
                } label: {
                    Text(WatchStrings.send)
                        .font(.custom(FontRegistration.fontFamily, size: 16).weight(.medium))
                        .foregroundStyle(WatchChatPalette.foreground)
                        .frame(maxWidth: .infinity)
                        .frame(height: 41)
                        .background(WatchChatPalette.orange, in: Capsule())
                }
                .buttonStyle(.plain)
                .disabled(isSending)
                .accessibilityIdentifier("watch-audio-send-button")
            }
            .padding(.bottom, 12)
        }
        .padding(.horizontal, .spacing4)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(WatchChatPalette.recordingGradient, in: RoundedRectangle(cornerRadius: 30, style: .continuous))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("watch-audio-recording-screen")
    }

    private func sendRecording() async {
        guard !isSending else { return }
        let duration = audioRecorder.duration
        guard let url = audioRecorder.stopRecording() else { return }
        pendingRecording = (url, duration)
        await retryRecording()
    }

    private func retryRecording() async {
        guard !isSending, let pendingRecording else { return }
        isSending = true
        defer { isSending = false }
        guard let data = try? Data(contentsOf: pendingRecording.url) else {
            self.pendingRecording = nil
            return
        }
        if await runtime.sendAudioRecording(data: data, filename: pendingRecording.url.lastPathComponent,
                                            duration: pendingRecording.duration) {
            try? FileManager.default.removeItem(at: pendingRecording.url)
            self.pendingRecording = nil
        }
    }

    private func sendEmbedOpenNotification(_ model: WatchEmbedPreviewModel) {
        guard let request = WatchEmbedOpenRequest(
            chatId: model.continuation.chatId ?? runtime.selectedChatId,
            embedId: model.id
        ) else { return }
        phoneBridge.sendEmbedOpenRequest(request)
    }
}

private struct WatchPendingAudioEmbedView: View {
    let embed: WatchPendingAudioEmbed

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing1) {
            Text(WatchStrings.voiceRecording)
                .font(.omMicro)
                .fontWeight(.semibold)
                .foregroundStyle(Color.grey30)
            Text(embed.transcript ?? embed.filename)
                .font(.omXs)
                .foregroundStyle(Color.grey0)
                .lineLimit(2)
        }
        .padding(.horizontal, .spacing3)
        .padding(.vertical, .spacing2)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey90, in: RoundedRectangle(cornerRadius: .radius6, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: .radius6, style: .continuous)
                .stroke(Color.buttonPrimary.opacity(0.55), lineWidth: 1)
        )
        .accessibilityIdentifier("watch-pending-audio-embed")
    }
}

private struct WatchChatHeader: View {
    let title: String
    let isSyncing: Bool

    var body: some View {
        HStack(spacing: .spacing3) {
            Circle()
                .fill(LinearGradient.primary)
                .frame(width: .iconSizeLg, height: .iconSizeLg)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.omP)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.grey0)
                Text(isSyncing ? WatchStrings.syncing : WatchStrings.loadingChats)
                    .font(.omMicro)
                    .foregroundStyle(Color.grey30)
            }
        }
    }
}

private struct WatchChatRow: View {
    let chat: WatchChatSummary

    var body: some View {
        HStack(alignment: .top, spacing: .spacing2) {
            Image(systemName: "bubble.left.fill")
                .font(.omSmall)
                .foregroundStyle(WatchChatPalette.foreground)
                .frame(width: 28, height: 28)
                .background(WatchChatPalette.teal.opacity(0.55), in: Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: .spacing1) {
                    Text(chat.title ?? WatchStrings.untitledChat)
                        .font(.custom(FontRegistration.fontFamily, size: 14).weight(.bold))
                        .foregroundStyle(WatchChatPalette.foreground)
                        .lineLimit(3)
                    if chat.isPinned {
                        Circle()
                            .fill(WatchChatPalette.blue)
                            .frame(width: 5, height: 5)
                            .accessibilityHidden(true)
                    }
                }
                if let preview = chat.preview?.trimmingCharacters(in: .whitespacesAndNewlines), !preview.isEmpty {
                    Text(preview)
                        .font(.custom(FontRegistration.fontFamily, size: 14).weight(.bold))
                        .foregroundStyle(WatchChatPalette.muted)
                        .lineLimit(1)
                        .multilineTextAlignment(.leading)
                }
            }
        }
        .padding(.vertical, .spacing2)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct WatchMessageBubble: View {
    let message: WatchChatMessage
    let onOpenEmbed: (WatchEmbedPreviewModel) -> Void

    private var isUser: Bool { message.role == .user }
    private let embedPreviews: [WatchEmbedPreviewModel]
    private let markdownBlocks: [WatchRenderedMarkdownBlock]

    init(message: WatchChatMessage, onOpenEmbed: @escaping (WatchEmbedPreviewModel) -> Void) {
        self.message = message
        self.onOpenEmbed = onOpenEmbed
        let records = message.watchEmbedRecords
        let lookup = EmbedRecord.dictionaryById(records, context: "watchMessageBubble") { _ in }
        embedPreviews = records.map { WatchEmbedPreviewMapper.makeModel(for: $0, chatId: message.chatId, allEmbedRecords: lookup) }
        markdownBlocks = WatchMarkdownParser.blocks(message.watchDisplayContent ?? "").map(WatchRenderedMarkdownBlock.init)
    }

    var body: some View {
        HStack {
            if isUser { Spacer(minLength: .spacing5) }
            VStack(alignment: .leading, spacing: .spacing2) {
                if !markdownBlocks.isEmpty {
                    WatchMarkdownContent(blocks: markdownBlocks)
                } else if embedPreviews.isEmpty {
                    Text(WatchStrings.clientEncrypted)
                        .font(.omXs)
                        .foregroundStyle(WatchChatPalette.foreground)
                        .fixedSize(horizontal: false, vertical: true)
                }

                ForEach(embedPreviews) { preview in
                    WatchEmbedPreviewCard(model: preview) {
                        onOpenEmbed(preview)
                    }
                }

                if message.isPending {
                    Text(WatchStrings.pendingSend)
                        .font(.omMicro)
                        .foregroundStyle(WatchChatPalette.muted)
                }
            }
            .padding(.horizontal, .spacing3)
            .padding(.vertical, .spacing2)
            .background(isUser ? WatchChatPalette.surface : WatchChatPalette.background, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
            if !isUser { Spacer(minLength: .spacing5) }
        }
    }
}

private struct WatchStatusPill: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.omMicro)
            .foregroundStyle(WatchChatPalette.foreground)
            .padding(.horizontal, .spacing3)
            .padding(.vertical, .spacing2)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(WatchChatPalette.surface, in: Capsule())
            .overlay(Capsule().stroke(WatchChatPalette.blue.opacity(0.55), lineWidth: 1))
    }
}

private struct WatchRenderedMarkdownBlock: Identifiable {
    let block: WatchMarkdownBlock
    let inlineText: AttributedString
    var id: Int { block.id }
    init(_ block: WatchMarkdownBlock) {
        self.block = block
        if case .code = block.kind { inlineText = AttributedString(block.text) }
        else { inlineText = (try? AttributedString(markdown: block.text,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(block.text) }
    }
}

private struct WatchMarkdownContent: View {
    let blocks: [WatchRenderedMarkdownBlock]
    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            ForEach(blocks) { rendered in
                switch rendered.block.kind {
                case .divider:
                    Rectangle().fill(WatchChatPalette.muted.opacity(0.4)).frame(height: 1)
                case .heading(let level):
                    Text(rendered.inlineText).font(.system(size: level <= 2 ? 15 : 13, weight: .bold))
                        .accessibilityIdentifier("watch-markdown-heading-\(rendered.id)")
                case .list(let marker):
                    HStack(alignment: .top, spacing: 4) {
                        Text(marker)
                        Text(rendered.inlineText).frame(maxWidth: .infinity, alignment: .leading)
                    }.font(.omXs).accessibilityIdentifier("watch-markdown-list-\(rendered.id)")
                case .quote:
                    HStack(alignment: .top, spacing: 5) {
                        Rectangle().fill(WatchChatPalette.blue).frame(width: 2)
                        Text(rendered.inlineText).italic()
                    }.font(.omXs)
                case .code:
                    ScrollView(.horizontal, showsIndicators: false) {
                        Text(rendered.block.text).font(.system(size: 11, design: .monospaced))
                    }.padding(5).background(WatchChatPalette.surface, in: RoundedRectangle(cornerRadius: 4))
                        .accessibilityIdentifier("watch-markdown-code-\(rendered.id)")
                case .paragraph:
                    Text(rendered.inlineText).font(.omXs)
                }
            }
        }
        .foregroundStyle(WatchChatPalette.foreground)
        .tint(WatchChatPalette.blue)
        .fixedSize(horizontal: false, vertical: true)
    }
}
