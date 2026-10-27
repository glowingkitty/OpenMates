// Compact signed-out Watch workspace using the bundled production examples.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/ChatHistory.svelte
//         frontend/packages/ui/src/components/Header.svelte
// CSS: frontend/packages/ui/src/styles/chat.css, header.css
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.guest.compact-workspace, apple-watch.guest.account-isolation,
//             apple-watch.pairing.explicit-entry-back, apple-watch.guest.public-inference
// ────────────────────────────────────────────────────────────────────
import SwiftUI

@MainActor
private enum WatchGuestCopy {
    static var login: String { WatchLocalization.text("login.login") }
    static var settingsSent: String { WatchLocalization.text("watch.hub.open_on_phone") }
    static func local(_ english: String, _ german: String) -> String {
        Locale.preferredLanguages.first?.hasPrefix("de") == true ? german : english
    }
    static var uncertain: String { local("The reply could not be confirmed. This request will not be sent again. Your text is saved here; start a new chat to continue.", "Die Antwort konnte nicht bestätigt werden. Diese Anfrage wird nicht erneut gesendet. Dein Text bleibt hier gespeichert; starte einen neuen Chat, um fortzufahren.") }
    static var storage: String { local("Could not save on this Watch. Your saved text has been kept.", "Auf dieser Watch konnte nicht gespeichert werden. Dein gespeicherter Text bleibt erhalten.") }
    static var unavailable: String { local("Free text is unavailable. Check your connection, try later, or Login.", "Kostenlose Textanfragen sind nicht verfügbar. Prüfe deine Verbindung, versuche es später oder melde dich an.") }
    static var historyFull: String { local("Start a new chat to continue.", "Starte einen neuen Chat, um fortzufahren.") }
    static func remaining(_ percent: Int) -> String { local("Free budget remaining: \(percent)%", "Verbleibendes kostenloses Budget: \(percent)%") }
    static var phoneUnavailable: String { WatchLocalization.text("settings.unreachable") }
}

// The exact signed-out route used by WatchRootView and deterministic UI coverage.
struct WatchGuestEntryView: View {
    @ObservedObject var authStore: WatchAuthStore
    let onSettings: () -> Bool
    var uiTestPairFixture: WatchPairLoginFixtureState? = nil
    @State private var showsPairLogin = false
    @State private var publicProfile: ServerProfile
    init(authStore: WatchAuthStore, publicProfile: ServerProfile = .production,
         onSettings: @escaping () -> Bool, uiTestPairFixture: WatchPairLoginFixtureState? = nil) {
        self.authStore = authStore; self.onSettings = onSettings; self.uiTestPairFixture = uiTestPairFixture
        _publicProfile = State(initialValue: publicProfile)
    }
    var body: some View {
        Group {
            if showsPairLogin {
                WatchPairLoginView(authStore: authStore, uiTestFixture: uiTestPairFixture,
                    onBack: { showsPairLogin = false })
            } else {
                WatchGuestWorkspaceView(publicProfile: publicProfile,
                    onLogin: { showsPairLogin = true }, onSettings: onSettings)
                    .id(publicProfile.apiBaseURL.absoluteString)
            }
        }.onReceive(NotificationCenter.default.publisher(for: ServerConfiguration.didChangeNotification)) { _ in
            publicProfile = ServerProfile.current()
        }
    }
}

struct WatchGuestWorkspaceView: View {
    let onLogin: () -> Void
    let onSettings: () -> Bool
    @StateObject private var catalog = WatchPublicExampleStore(text: { WatchLocalization.text($0) })
    @State private var search = ""
    @State private var searching = false
    @State private var conversation: WatchPublicExampleStore.Conversation?
    @State private var embed: WatchEmbedPreviewModel?
    @State private var zoomVisible = false
    @State private var creating = false
    @StateObject private var guest: WatchGuestChatWorkspace
    @State private var guestChatID: String?
    @State private var settingsMessage: String?

    init(publicProfile: ServerProfile, onLogin: @escaping () -> Void, onSettings: @escaping () -> Bool) {
        self.onLogin = onLogin; self.onSettings = onSettings
        let origin = publicProfile.apiBaseURL
        _guest = StateObject(wrappedValue: WatchGuestChatWorkspace(publicOrigin: origin,
            isCurrentOrigin: { ServerProfile.current().apiBaseURL == origin }))
    }
    var body: some View {
        ZStack {
            WatchWorkspacePalette.background.ignoresSafeArea()
            if let embed {
                WatchEmbedFullscreenView(model: embed, onClose: { self.embed = nil })
            } else if let conversation {
                VStack(spacing: .spacing2) {
                    header(conversation.summary.title ?? WatchStrings.untitledChat) {
                        self.conversation = nil; zoomVisible = false
                    }
                    ScrollView {
                        LazyVStack(spacing: .spacing3) {
                            ForEach(conversation.messages) { message in
                                WatchMessageBubble(message: message, hydratedChildren: conversation.records,
                                    onShowZoom: { zoomVisible = true }, onOpenEmbed: { embed = $0 })
                            }
                        }
                    }.accessibilityIdentifier("watch-public-transcript")
                }
                .overlay(alignment: .center) {
                    if zoomVisible { WatchMessageZoomControls(onClose: { zoomVisible = false }) }
                }
            } else if creating {
                guestConversation.accessibilityIdentifier("watch-guest-new-chat")
            } else if let settingsMessage {
                VStack(spacing: .spacing4) {
                    header(WatchChatCopy.settings) { self.settingsMessage = nil }
                    Text(settingsMessage).font(.omSmall).multilineTextAlignment(.center)
                    Spacer(minLength: 0)
                }.accessibilityIdentifier("watch-guest-settings")
            } else {
                ScrollView {
                    VStack(spacing: .spacing3) {
                        Text(WatchChatCopy.chats).font(.omP.weight(.semibold))
                            .frame(maxWidth: .infinity, alignment: .leading)
                        HStack(spacing: .spacing4) {
                            action("square.and.pencil", label: WatchStrings.newChat, id: "watch-new-chat-button") { guestChatID = guest.create(); creating = guestChatID != nil }
                            action("magnifyingglass", label: WatchChatCopy.search, id: "watch-chat-search-button") {
                                searching.toggle(); if !searching { search = "" }
                            }
                            action("gearshape.fill", label: WatchChatCopy.settings, id: "watch-chat-settings-button") {
                                settingsMessage = onSettings() ? WatchGuestCopy.settingsSent : WatchGuestCopy.phoneUnavailable
                            }
                        }
                        loginButton
                        if searching {
                            TextField(WatchChatCopy.search, text: $search)
                                .font(.omSmall).padding(.spacing2)
                                .background(WatchWorkspacePalette.surface, in: Capsule())
                                .accessibilityIdentifier("watch-chat-search-input")
                            Button { search = "" } label: { Text(WatchLocalization.text("common.cancel")).font(.omXs) }
                                .buttonStyle(.plain).accessibilityIdentifier("watch-public-search-clear")
                        }
                        if guest.notice == .storage { Text(WatchGuestCopy.storage).font(.omXs) }
                        ForEach(guest.chats.filter { search.isEmpty || $0.title.localizedCaseInsensitiveContains(search) }) { chat in
                            Button { guestChatID = chat.id; creating = true } label: {
                                WatchChatRow(chat: WatchChatSummary(id: chat.id,
                                    title: chat.title.isEmpty ? WatchStrings.untitledChat : chat.title,
                                    lastMessageAt: nil, preview: nil, isPinned: false,
                                    encryptedTitle: nil, encryptedPreview: nil, encryptedChatKey: nil))
                            }.buttonStyle(.plain).accessibilityIdentifier("watch-guest-local-\(chat.id)")
                        }
                        ForEach(catalog.search(search)) { chat in
                            Button { conversation = catalog.conversation(id: chat.id) } label: { WatchChatRow(chat: chat) }
                                .buttonStyle(.plain).accessibilityIdentifier("watch-chat-row-\(chat.id)")
                        }
                    }
                }.accessibilityIdentifier("watch-guest-chat-list")
            }
        }
        .padding(.horizontal, .spacing3).padding(.top, .spacing2)
        .foregroundStyle(WatchWorkspacePalette.foreground)
        .accessibilityElement(children: .contain).accessibilityIdentifier("watch-guest-workspace")
        .onDisappear { guest.suspend() }
        .onReceive(NotificationCenter.default.publisher(for: ServerConfiguration.didChangeNotification)) { _ in
            guest.suspend()
        }
    }
    @ViewBuilder private var guestConversation: some View {
        if let id = guestChatID, let chat = guest.chat(id) {
            VStack(spacing: .spacing2) {
                header(WatchStrings.newChat) { guest.suspend(); creating = false }
                ScrollView {
                    VStack(alignment: .leading, spacing: .spacing3) {
                        if chat.messages.isEmpty { Text(WatchChatCopy.welcomePrompt).font(.omSmall) }
                        Text(WatchLocalization.text("chat.anonymous_free_usage.feature_notice")).font(.omXs)
                        ForEach(chat.messages) { message in
                            guestBubble(message, chatID: id)
                                .accessibilityIdentifier("watch-guest-message-\(message.id)")
                        }
                        if let pending = chat.pending { Text(pending.text).font(.omSmall) }
                        if let percent = guest.budget?.dailyRemainingPercent, (0...100).contains(percent) {
                            Text(WatchGuestCopy.remaining(percent)).font(.omXs)
                                .accessibilityIdentifier("watch-guest-budget")
                        }
                        if let notice = guest.notice, notice != .uncertain {
                            Text(guestNotice(notice)).font(.omXs).accessibilityIdentifier("watch-guest-send-status")
                        }
                        if chat.pending != nil && !guest.busy {
                            Text(WatchGuestCopy.uncertain).font(.omXs).accessibilityIdentifier("watch-guest-send-status")
                            Button(WatchStrings.newChat) {
                                guestChatID = guest.create(); creating = guestChatID != nil
                            }.accessibilityIdentifier("watch-guest-continue-new-chat")
                        }
                    }
                }.accessibilityIdentifier("watch-guest-local-transcript")
                TextField(WatchStrings.messagePlaceholder, text: Binding(get: { guest.chat(id)?.draft ?? "" },
                    set: { guest.edit($0, chatID: id) }))
                    .font(.omSmall).disabled(guest.busy || chat.pending != nil)
                    .accessibilityIdentifier("watch-message-input")
                HStack {
                    Button(WatchStrings.retry) { Task { await guest.refreshBudget() } }
                        .disabled(guest.busy).accessibilityIdentifier("watch-guest-refresh-budget")
                    Button(guest.busy ? WatchStrings.pendingSend : WatchStrings.send) { guest.startSend(chatID: id) }
                        .disabled(guest.busy || chat.pending != nil || chat.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        .accessibilityIdentifier("watch-send-button")
                }.font(.omXs)
                loginButton
            }.task(id: id) { await guest.refreshBudget() }
                .overlay(alignment: .center) {
                    if zoomVisible { WatchMessageZoomControls(onClose: { zoomVisible = false }) }
                }
        }
    }
    private func guestBubble(_ message: WatchGuestChat.Message, chatID: String) -> some View {
        let parsed = BundledPublicExampleCatalog.extractEmbeds(from: message.content, fallbackAppId: "ai")
        let projected = WatchChatMessage(id: message.id, chatId: chatID,
            role: message.role == "user" ? .user : .assistant,
            content: parsed.content, encryptedContent: nil,
            embedRefs: parsed.refs.map { WatchEmbedRef(id: $0.id, type: $0.type, status: $0.status, data: $0.data) },
            createdAt: ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: TimeInterval(message.createdAt))),
            isPending: false)
        return WatchMessageBubble(message: projected, hydratedChildren: parsed.records,
            onShowZoom: { zoomVisible = true }, onOpenEmbed: { embed = $0 })
    }
    private func guestNotice(_ notice: WatchGuestChatWorkspace.Notice) -> String {
        switch notice {
        case .uncertain: return WatchGuestCopy.uncertain
        case .storage: return WatchGuestCopy.storage
        case .historyFull, .invalidDraft: return WatchGuestCopy.historyFull
        case .unavailable:
            return WatchGuestCopy.unavailable
        }
    }
    private var loginButton: some View {
        Button(action: onLogin) { Text(WatchGuestCopy.login).font(.omSmall.weight(.semibold))
            .frame(maxWidth: .infinity, minHeight: .spacing8).background(LinearGradient.primary, in: Capsule()) }
            .buttonStyle(.plain).accessibilityIdentifier("watch-guest-login")
    }
    private func header(_ title: String, back: @escaping () -> Void) -> some View {
        HStack(spacing: .spacing2) {
            Button(action: back) { Icon("back", size: .iconSizeSm).frame(width: .spacing8, height: .spacing8) }
                .buttonStyle(.plain).accessibilityLabel(WatchStrings.back).accessibilityIdentifier("watch-public-back")
            Text(title).font(.omSmall.weight(.semibold)).lineLimit(2)
            Spacer(minLength: 0)
        }
    }
    private func action(_ icon: String, label: String, id: String, perform: @escaping () -> Void) -> some View {
        Button(action: perform) { Image(systemName: icon).font(.omP).frame(maxWidth: .infinity, minHeight: .spacing8) }
            .buttonStyle(.plain).foregroundStyle(Color.buttonPrimary).accessibilityLabel(label).accessibilityIdentifier(id)
    }
}
