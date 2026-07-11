// Single chat view — message list with input field and streaming responses.
// Supports block-level markdown rendering (code blocks, tables, blockquotes),
// inline embed previews, and fullscreen embed sheets. Advertises the current
// chat for Handoff so users can continue on another Apple device.

// ─── Web source ─────────────────────────────────────────────────────
// MessageBubble:
//   Svelte:  frontend/packages/ui/src/components/ChatMessage.svelte
//   CSS:     frontend/packages/ui/src/styles/chat.css
//            .mate-message-content  { background:var(--color-grey-0); border-radius:13px;
//              filter:drop-shadow(0 4px 4px rgba(0,0,0,.25)); padding:12px }
//            .user-message-content  { background:var(--color-grey-blue); color:var(--color-grey-100) }
//            .user-message-content::before / .mate-message-content::before  (SVG tail)
//            speechbubble.svg       { viewBox: 0 0 7 11 → rendered 12×20pt }
//
// inputBar:
//   Svelte:  frontend/packages/ui/src/components/enter_message/MessageInput.svelte
//   Swift:   MessageComposerView -> NativeComposerEditorView editable surface
//   CSS:     frontend/packages/ui/src/components/enter_message/MessageInput.styles.css
//            .message-field { background-color:var(--color-grey-blue); border-radius:24px;
//              min-height:100px; padding:0 0 60px 0;
//              box-shadow:0 4px 12px rgba(0,0,0,0.08); /* no border, no focus ring */ }
//   CSS:     frontend/packages/ui/src/components/enter_message/ActionButtons.svelte
//            .send-button { color:white; padding:spacing-4 spacing-8; border-radius:radius-8;
//              height:40px; font-weight:500 }
//            .action-buttons { position:absolute; bottom:1rem; left:1rem; right:1rem }
//
// messageList / StreamingIndicator:
//   Svelte:  frontend/packages/ui/src/components/ChatHistory.svelte
//   CSS:     frontend/packages/ui/src/styles/chat.css
//            .chat-history-content { max-width:1000px; margin:0 auto }
//
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

// ChatBannerView and ChatBannerState are defined in ChatBannerView.swift

private enum ChatScrollSentinelEdge: Hashable {
    case top
    case bottom
}

private enum ComposerOverlay: Equatable {
    case location
    case sketch
    case recording
}

private struct ComposerDeferredSendContext {
    let excludedPIIIds: Set<String>
    let broadcastToSiblings: Bool
}

private enum ComposerDeferredSendError: Error {
    case missingContext
    case sendFailed
}

private struct ChatScrollSentinelPreferenceKey: PreferenceKey {
    static let defaultValue: [ChatScrollSentinelEdge: CGFloat] = [:]

    static func reduce(value: inout [ChatScrollSentinelEdge: CGFloat], nextValue: () -> [ChatScrollSentinelEdge: CGFloat]) {
        value.merge(nextValue(), uniquingKeysWith: { _, new in new })
    }
}

private struct ChatMessageFramePreferenceKey: PreferenceKey {
    static let defaultValue: [String: CGRect] = [:]

    static func reduce(value: inout [String: CGRect], nextValue: () -> [String: CGRect]) {
        value.merge(nextValue(), uniquingKeysWith: { _, new in new })
    }
}

private enum ChatResponsiveBreakpoint {
    /// Web `ChatMessage.svelte`: assistant messages use `.mobile-stacked`
    /// when the measured chat container width is <= 500 px.
    static let assistantStacked: CGFloat = 500
    /// Web `ActiveChat.svelte`: input-adjacent New chat label hides at
    /// `@container chat-side (max-width: 550px)`.
    static let inlineNewChatCompact: CGFloat = 550
}

private enum ChatMessageLayoutMetric {
    /// Web `chat.css`: `.chat-message { gap: 6px; }`.
    static let rowGap: CGFloat = 6
    /// Web `chat.css`: `.mobile-stacked .mate-profile { margin-bottom: 8px; }`.
    static let stackedAvatarGap: CGFloat = 8
    /// Web `chat.css`: `.message-align-right { max-width: calc(100% - 100px); }`.
    static let userDesktopReserve: CGFloat = 100
    /// Web `chat.css`: `.message-align-right.mobile-compact { max-width: calc(100% - 20px); }`.
    static let userCompactReserve: CGFloat = 20
    /// Web `chat.css`: `.message-align-left { max-width: calc(100% - 70px); }`.
    static let assistantDesktopReserve: CGFloat = 70
}

struct ChatView: View {
    let chatId: String
    /// Optional gradient banner state. Provide `.loaded` for demo/example chats;
    /// omit (nil) for regular user chats where no banner should appear.
    var bannerState: ChatBannerState? = nil
    var bannerCreatedAt: Date? = nil
    /// Synced user chat data from the app shell. Public/example chats still load
    /// from PublicChatContent, so both paths share this one ChatView + ViewModel.
    var initialChat: Chat? = nil
    var initialMessages: [Message] = []
    var initialEmbeds: [EmbedRecord] = []
    var wsManager: WebSocketManager? = nil
    var chatStore: ChatStore? = nil
    var inputFocusRequest = 0
    var cameraCaptureRequest = 0
    var searchTarget: ChatSearchSelection? = nil
    /// Mirrors web `.chat-container.menu-open`; used by the banner header to
    /// collapse from viewport-responsive height to the fixed adjacent-panel height.
    var isSettingsOpen = false
    var onShareChat: (() -> Void)? = nil
    /// Navigation callbacks for prev/next chat arrows on the banner.
    var onPreviousChat: (() -> Void)? = nil
    var onNextChat: (() -> Void)? = nil
    /// Mirrors web `demoChatSelected`: embedded public chat cards ask the app shell
    /// to select and load a different bundled demo/example chat.
    var onOpenPublicChat: ((String) -> Void)? = nil
    /// Opens another user chat in the owning app shell.
    var onOpenChat: ((String) -> Void)? = nil
    /// Opens the new-chat surface in the owning app shell window.
    var onNewChat: (() -> Void)? = nil
    /// Opens the app-owned issue report settings pane with an optional prefill.
    var onReportIssue: ((ReportIssuePrefill) -> Void)? = nil
    /// Sends the last visible message ID to the app shell for cross-device sync.
    var onScrollPositionChanged: ((String) -> Void)? = nil

    @StateObject private var viewModel = ChatViewModel()
    @StateObject private var handoffManager = HandoffManager()
    @StateObject private var piiPrivacySettingsStore = PIIPrivacySettingsStore.shared
    @StateObject private var enhancedPIIModelController = EnhancedPIIModelDownloadController.shared
    @StateObject private var enhancedPIIRecommendationStore = EnhancedPIIRecommendationStore.shared
    @StateObject private var composerSession = NativeComposerSession()
    @State private var selectedEmbed: EmbedRecord?
    @State private var showEmbedFullscreen = false
    @State private var showReminder = false
    @State private var isPIIRevealed = false
    @State private var showAttachmentMenu = false
    @State private var showCameraCapture = false
    @State private var composerOverlay: ComposerOverlay?
    @State private var isComposerExpanded = false
    @State private var micPermissionState: MicPermissionState = .unknown
    @State private var recordHintVisible = false
    @State private var recordDragOffsetX: CGFloat = 0
    @State private var recordAttemptActive = false
    @State private var recordStartedFromKeyboard = false
    @State private var suppressKeyboardRecordSpaceUntilKeyUp = false
    @State private var recordStartTask: Task<Void, Never>?
    @State private var recordHintTask: Task<Void, Never>?
    @State private var detectedPIIMatches: [PIIMatch] = []
    @State private var piiExclusions: Set<String> = []
    @State private var enhancedPIIDetectionTask: Task<Void, Never>?
    @State private var mentionQuery: String?
    @State private var actionMessage: Message?
    @State private var chatViewportHeight: CGFloat = 0
    @State private var chatContainerWidth: CGFloat = 0
    @State private var isAtTop = true
    @State private var isAtBottom = false
    @State private var hasRestoredInitialScroll = false
    @State private var isRestoringScroll = false
    @State private var handledInputFocusRequest = 0
    @State private var handledCameraCaptureRequest = 0
    @State private var lastReportedVisibleMessageId: String?
    @State private var assistantFeedbackMessageId: String?
    @State private var selectedAssistantRating: Int?
    @State private var assistantFeedbackSubmitted = false
    @State private var scrollPositionDebounceTask: Task<Void, Never>?
    @State private var draftSaveTask: Task<Void, Never>?
    @State private var broadcastToSiblingSubChats = false
    @StateObject private var focusModeManager = FocusModeManager()
    @StateObject private var composerRecorder = VoiceRecorder()
    @StateObject private var pendingUploads = PendingUploadStore.shared
    @State private var composerEmbedLifecycle = ComposerEmbedLifecycle()
    @State private var composerPendingSendCoordinator = ComposerPendingSendCoordinator()
    @State private var deferredComposerSendContexts: [String: ComposerDeferredSendContext] = [:]
    @State private var deferredComposerSendNodeIDs: [String: Set<String>] = [:]
    @State private var resolvedComposerEmbeds: [String: ComposerPendingEmbed] = [:]
    @State private var deferredComposerSendRevisions: Set<Int> = []
    @State private var isInputFocused = false
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.scenePhase) private var scenePhase

    private var messageText: String {
        get { composerSession.canonicalMarkdown }
        nonmutating set { composerSession.replaceMarkdown(newValue) }
    }

    private var composerHasEmbed: Bool {
        composerSession.controller.document.nodes.contains { node in
            node.kind == "embed" && node.status != AppleComposerEmbedLifecycleState.cancelled.rawValue
        }
    }

    /// True for demo/intro/legal chats that show "New chat" CTA instead of input field
    private var isDemoOrLegalChat: Bool {
        chatId.hasPrefix("demo-") || chatId.hasPrefix("legal-") || chatId.hasPrefix("announcements-")
    }

    private var isExampleChat: Bool {
        chatId.hasPrefix("example-")
    }

    private var latestAssistantMessageId: String? {
        viewModel.messages.last { message in
            message.role == .assistant && !(message.content ?? "").isEmpty
        }?.id
    }

    private var showAssistantFeedback: Bool {
        latestAssistantMessageId != nil && !viewModel.isStreaming
    }

    private var activeProcessingSteps: [ProcessingDetailsView.ProcessingStep] {
        guard viewModel.streamingLifecycle.shouldShowProcessingDetails,
              let step = viewModel.streamingLifecycle.preprocessingStep else {
            return []
        }
        return [.fromPreprocessing(step)]
    }

    private var introTeaserVideoURL: URL? {
        Bundle.main.url(forResource: "intro-teaser", withExtension: "mp4", subdirectory: "Videos")
            ?? Bundle.main.url(forResource: "intro-teaser", withExtension: "mp4")
    }

    var body: some View {
        GeometryReader { geo in
            ZStack {
                Color.clear
                    .accessibilityElement()
                    .accessibilityIdentifier("chat-view-\(chatId)")
                    .allowsHitTesting(false)

                VStack(spacing: 0) {
                    if bannerState == nil {
                        if effectiveBannerState == nil {
                            chatTopBar
                        }
                    }

                    if IncognitoChatSession.isIncognitoChatId(chatId) {
                        incognitoSessionBanner
                    }

                    messageList
                        .simultaneousGesture(
                            TapGesture().onEnded {
                                dismissInputIfNeeded()
                            }
                        )

                    subChatLifecyclePanel

                    returnToParentButton

                    FocusModePill(focusModeManager: focusModeManager) { _ in
                        Task { await viewModel.deactivateActiveFocusMode() }
                    }

                    if viewModel.isStreaming {
                        streamingBanner
                    }

                    // Web: intro/legal chats show a full-width "New chat" CTA instead of the input field
                    if isDemoOrLegalChat {
                        newChatCTA
                    } else if isExampleChat || !viewModel.messages.isEmpty {
                        exampleChatInputRow
                    } else {
                        inputBar
                    }
                }
                .background(Color.grey20)

                if showReminder {
                    customOverlay(title: AppStrings.setReminder, isPresented: $showReminder) {
                        ReminderCreationView(chatId: chatId)
                    }
                }

                if showEmbedFullscreen, let embed = selectedEmbed {
                    embedFullscreenSheet(for: embed)
                    .ignoresSafeArea()
                }

                if let actionMessage {
                    messageActionsOverlay(for: actionMessage)
                }
            }
            .onAppear {
                chatViewportHeight = geo.size.height
                chatContainerWidth = geo.size.width
            }
            .onChange(of: geo.size.height) { _, height in
                chatViewportHeight = height
            }
            .onChange(of: geo.size.width) { _, width in
                chatContainerWidth = width
            }
        }
        .chatKeyboardShortcuts(
            onStopStreaming: { viewModel.stopStreaming() },
            onToggleIncognito: {
                // Incognito toggle is posted as a notification — handled by MainAppView
                // which owns the IncognitoManager instance
                NotificationCenter.default.post(name: .toggleIncognito, object: nil)
            }
        )
        .onKeyPress(.space, phases: [.down, .repeat, .up]) { press in
            handleKeyboardRecordSpace(press)
        }
        .onKeyPress(.escape, phases: .down) { _ in
            handleKeyboardRecordEscape()
        }
        #if os(iOS)
        .fullScreenCover(isPresented: $showCameraCapture) {
            CameraCaptureView(
                onCapture: { data, filename in
                    showCameraCapture = false
                    enqueueAttachmentUpload(data: data, filename: filename)
                },
                onCancel: { showCameraCapture = false }
            )
            .ignoresSafeArea()
        }
        #endif
        .onAppear {
            applyUITestRecordingOverlayIfNeeded()
            applyInputFocusRequestIfNeeded()
            applyCameraCaptureRequestIfNeeded()
        }
        .onChange(of: inputFocusRequest) { _, _ in
            applyInputFocusRequestIfNeeded()
        }
        .onChange(of: cameraCaptureRequest) { _, _ in
            applyCameraCaptureRequestIfNeeded()
        }
        .task(id: chatId) {
            draftSaveTask?.cancel()
            await invalidateDeferredComposerSends()
            composerSession.clear()
            await ApplePrivacySettingsService.shared.load()
            isPIIRevealed = false
            viewModel.configure(wsManager: wsManager, chatStore: chatStore)
            await viewModel.loadChat(id: chatId, initialChat: initialChat, initialMessages: initialMessages, initialEmbeds: initialEmbeds)
            await restoreEncryptedDraft()
            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("--ui-test-seed-pending-composer-embed") {
                if let embed = viewModel.seedUITestPendingComposerEmbed() {
                    insertResolvedUITestEmbed(embed)
                }
            }
            if ProcessInfo.processInfo.arguments.contains("--ui-test-force-recording-overlay") {
                micPermissionState = .granted
                composerOverlay = .recording
                isInputFocused = true
            }
            #endif
            // Advertise this chat for Handoff to other Apple devices
            handoffManager.advertiseChatViewing(
                chatId: chatId,
                chatTitle: viewModel.chat?.displayTitle
            )
            // Clear notification badge when viewing a chat
            PushNotificationManager.shared.clearBadge()
        }
        .onDisappear {
            scrollPositionDebounceTask?.cancel()
            handoffManager.stopAdvertising()
            Task { await invalidateDeferredComposerSends() }
        }
        .onChange(of: viewModel.forkedChatId) {
            guard let newChatId = viewModel.forkedChatId else { return }
            // Navigate to forked chat via deep link notification
            NotificationCenter.default.post(
                name: .deepLinkReceived,
                object: nil,
                userInfo: ["url": URL(string: "openmates://chat/\(newChatId)")!]
            )
            viewModel.forkedChatId = nil
        }
        .onChange(of: latestAssistantMessageId) { _, newMessageId in
            guard assistantFeedbackMessageId != newMessageId else { return }
            assistantFeedbackMessageId = newMessageId
            selectedAssistantRating = nil
            assistantFeedbackSubmitted = false
        }
        .onChange(of: initialMessageSyncSignature) { _, _ in
            Task {
                await viewModel.applySynced(chat: initialChat, messages: initialMessages, embeds: initialEmbeds)
            }
        }
        .onChange(of: initialEmbedSyncSignature) { _, _ in
            Task {
                await viewModel.applySyncedEmbeds(initialEmbeds)
            }
        }
        .onChange(of: messageText) { _, newValue in
            updatePIIMatches(for: newValue)
            updateMentionQuery(for: newValue)
        }
        .onChange(of: composerSession.revision) { _, _ in
            scheduleEncryptedDraftSave()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active { flushEncryptedDraft() }
        }
        .onDisappear {
            draftSaveTask?.cancel()
            flushEncryptedDraft()
        }
        .onChange(of: piiPrivacySettingsStore.settings) { _, _ in
            updatePIIMatches(for: messageText)
        }
        .onReceive(NotificationCenter.default.publisher(for: .pendingDeferredSendRequested)) { notification in
            handleComposerDeferredSend(notification)
        }
        .onChange(of: viewModel.chat?.activeFocusId) { _, focusId in
            if let focusId, !focusId.isEmpty {
                focusModeManager.activate(.init(
                    id: focusId,
                    appId: focusId.components(separatedBy: "-").first ?? "ai",
                    name: focusId
                ))
            } else {
                focusModeManager.deactivate()
            }
        }
    }

    private var initialMessageSyncSignature: String {
        [
            initialChat?.id ?? "",
            initialChat?.updatedAt ?? "",
            initialChat?.displayTitle ?? "",
            initialChat?.category ?? "",
            initialChat?.icon ?? "",
            initialChat?.chatSummary ?? "",
            String(initialMessages.count),
            initialMessages.last?.id ?? ""
        ].joined(separator: "|")
    }

    private var initialEmbedSyncSignature: String {
        [
            initialChat?.id ?? "",
            String(initialEmbeds.count),
            initialEmbeds.map(\.id).max() ?? ""
        ].joined(separator: "|")
    }

    private var effectiveBannerState: ChatBannerState? {
        if let bannerState { return bannerState }
        guard let chat = viewModel.chat,
              let title = chat.title,
              let category = chat.category,
              !title.isEmpty,
              !category.isEmpty else { return nil }
        return .loaded(title: title, appId: category, summary: chat.chatSummary)
    }

    private var effectiveBannerCreatedAt: Date? {
        bannerCreatedAt ?? viewModel.chat?.createdDate ?? viewModel.chat?.updatedDate
    }

    private var followUpSuggestionCategory: String? {
        if case .loaded(_, let appId, _) = effectiveBannerState {
            return appId
        }
        return viewModel.chat?.category ?? viewModel.chat?.appId
    }

    private var followUpSuggestionIcon: String? {
        publicChatIconName(for: chatId) ?? viewModel.chat?.icon
    }

    // MARK: - Embed fullscreen helper

    private var chatTopBar: some View {
        HStack(spacing: .spacing3) {
            ChatHeaderView(chat: viewModel.chat, isLoading: viewModel.isLoading)

            Spacer()

            if chatHasPIIMappings {
                chatFloatingAction(
                    icon: isPIIRevealed ? "hidden" : "visible",
                    label: isPIIRevealed ? AppStrings.piiHide : AppStrings.piiShow,
                    accessibilityIdentifier: "chat-pii-toggle"
                ) {
                    isPIIRevealed.toggle()
                }
            }
        }
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing3)
        .background(Color.grey20)
        .accessibilityIdentifier("active-chat-header")
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(Color.grey20)
                .frame(height: 1)
        }
    }

    private var chatHasPIIMappings: Bool {
        viewModel.messages.contains { ($0.piiMappings?.isEmpty == false) || ($0.encryptedPIIMappings?.isEmpty == false) }
    }

    private var cumulativePIIMappings: [PIIMapping] {
        var byPlaceholder: [String: PIIMapping] = [:]
        for message in viewModel.messages where message.role == .user {
            for mapping in message.piiMappings ?? [] {
                byPlaceholder[mapping.placeholder] = mapping
            }
        }
        return Array(byPlaceholder.values)
    }

    private var displayedEmbedRecords: [String: EmbedRecord] {
        guard isPIIRevealed else { return viewModel.embedRecords }
        return viewModel.embedRecords.mapValues { displayEmbed($0) }
    }

    private func displayEmbed(_ embed: EmbedRecord) -> EmbedRecord {
        guard isPIIRevealed else { return embed }
        return PIIDetector.restorePII(in: embed, mappings: cumulativePIIMappings)
    }

    private func displayedEmbeds(for message: Message) -> [EmbedRecord] {
        viewModel.embeds(for: message).map(displayEmbed)
    }

    private var incognitoSessionBanner: some View {
        HStack(spacing: .spacing3) {
            Icon("hidden", size: 14)
                .accessibilityHidden(true)
            Text(AppStrings.incognitoModeActive)
                .font(.omXs)
                .fontWeight(.medium)
            Spacer()
        }
        .foregroundStyle(Color.fontButton)
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing2)
        .background(Color.grey80)
        .accessibilityElement(children: .combine)
        .help(Text(AppStrings.incognitoModeActive))
        .accessibilityLabel(AppStrings.incognitoModeActive)
        .accessibilityIdentifier("incognito-mode-banner")
    }

    private func customOverlay<Content: View>(
        title: String,
        isPresented: Binding<Bool>,
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
                    HStack {
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
                }

                content()
            }
            .frame(maxWidth: 760, maxHeight: 760)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .overlay(
                RoundedRectangle(cornerRadius: .radius8)
                    .stroke(Color.grey20, lineWidth: 1)
            )
            .padding(.spacing8)
        }
    }

    @ViewBuilder
    private func embedFullscreenSheet(for embed: EmbedRecord) -> some View {
        let displayedSelectedEmbed = displayEmbed(embed)
        let matchingMessage = viewModel.messages.first { msg in
            msg.embedRefs?.contains(where: { $0.id == embed.id }) == true
        }
        let fallbackMessage = matchingMessage ?? viewModel.messages.last
        let messageEmbeds: [EmbedRecord] = if let msg = fallbackMessage {
            displayedEmbeds(for: msg)
        } else {
            []
        }
        let fullscreenEmbeds = messageEmbeds.contains(where: { $0.id == displayedSelectedEmbed.id })
            ? messageEmbeds
            : [displayedSelectedEmbed]
        EmbedFullscreenContainer(
            embeds: fullscreenEmbeds,
            initialEmbedId: displayedSelectedEmbed.id,
            allEmbedRecords: displayedEmbedRecords,
            chatId: chatId,
            onClose: {
                showEmbedFullscreen = false
            }
        )
    }

    // MARK: - Message list

    private var messageList: some View {
        GeometryReader { scrollGeo in
            ScrollViewReader { proxy in
                ZStack {
                    ScrollView {
                        VStack(spacing: 0) {
                            scrollSentinel(id: "scroll-top", edge: .top)

                            // Gradient banner — shown for demo/example chats (ChatHeader.svelte equivalent)
                            if let banner = effectiveBannerState {
                                ChatBannerView(
                                    state: banner,
                                    createdAt: effectiveBannerCreatedAt,
                                    isExampleChat: chatId.hasPrefix("example-"),
                                    isIntroChat: chatId == "demo-for-everyone",
                                    teaserVideoURL: chatId == "demo-for-everyone"
                                        ? introTeaserVideoURL
                                        : nil,
                                    fullVideoURL: chatId == "demo-for-everyone"
                                        ? URL(string: "https://vod.api.video/vod/vi43o2FOchAMACeh5blHumCa/mp4/source.mp4")
                                        : nil,
                                    iconName: publicChatIconName(for: chatId) ?? viewModel.chat?.icon,
                                    isSettingsOpen: isSettingsOpen,
                                    viewportHeight: chatViewportHeight,
                                    onPrevious: onPreviousChat,
                                    onNext: onNextChat
                                )
                                    .id("banner")
                            }

                            LazyVStack(spacing: .spacing4) {
                                // Load older messages button at the top
                                if viewModel.hasOlderMessages {
                                    Button {
                                        let topMessageId = viewModel.messages.first?.id
                                        viewModel.loadOlderMessages()
                                        // Keep scroll position at the previously-top message
                                        if let topId = topMessageId {
                                            proxy.scrollTo(topId, anchor: .top)
                                        }
                                    } label: {
                                        HStack(spacing: .spacing2) {
                                            if viewModel.isLoadingOlder {
                                                ProgressView()
                                                    .scaleEffect(0.7)
                                            } else {
                                                Icon("up", size: 12)
                                            }
                                            Text(AppStrings.loadEarlierMessages)
                                                .font(.omXs)
                                        }
                                        .foregroundStyle(Color.fontSecondary)
                                        .padding(.vertical, .spacing3)
                                        .frame(maxWidth: .infinity)
                                    }
                                    .buttonStyle(.plain)
                                    .id("load-older")
                                }

                                ForEach(viewModel.messages) { message in
                                    MessageBubble(
                                        message: message,
                                        chatId: chatId,
                                        appId: viewModel.chat?.category ?? viewModel.chat?.appId,
                                        embeds: displayedEmbeds(for: message),
                                        allEmbedRecords: displayedEmbedRecords,
                                        streamingContent: viewModel.isStreamingMessage(message.id) ? viewModel.streamingContent : nil,
                                        piiMappings: cumulativePIIMappings,
                                        isPIIRevealed: isPIIRevealed,
                                        containerWidth: scrollGeo.size.width,
                                        isSearchTarget: searchTarget?.messageId == message.id,
                                        searchHighlightQuery: searchTarget?.messageId == message.id ? searchTarget?.query : nil,
                                        onEmbedTap: { embed in
                                            selectedEmbed = embed
                                            showEmbedFullscreen = true
                                        },
                                        onOpenPublicChat: onOpenPublicChat,
                                        onInteractiveQuestionSubmit: { content in
                                            Task { await viewModel.sendMessage(content) }
                                        },
                                        onShowActions: {
                                            actionMessage = message
                                        }
                                    )
                                    .id(message.id)
                                    .background(
                                        GeometryReader { messageGeo in
                                            Color.clear.preference(
                                                key: ChatMessageFramePreferenceKey.self,
                                                value: [message.id: messageGeo.frame(in: .named("chat-scroll"))]
                                            )
                                        }
                                    )
                                }

                                if !activeProcessingSteps.isEmpty {
                                    ProcessingDetailsView(steps: activeProcessingSteps, isComplete: false)
                                        .padding(.leading, scrollGeo.size.width > ChatResponsiveBreakpoint.assistantStacked ? 86 : 0)
                                        .padding(.trailing, scrollGeo.size.width > ChatResponsiveBreakpoint.assistantStacked ? 12 : 0)
                                        .id("processing-details")
                                }

                                if viewModel.streamingLifecycle.shouldShowThinkingDetails {
                                    ThinkingSectionView(
                                        content: viewModel.streamingLifecycle.thinkingContent,
                                        isStreaming: viewModel.streamingLifecycle.isThinkingStreaming
                                    )
                                    .padding(.leading, scrollGeo.size.width > ChatResponsiveBreakpoint.assistantStacked ? 86 : 0)
                                    .padding(.trailing, scrollGeo.size.width > ChatResponsiveBreakpoint.assistantStacked ? 12 : 0)
                                    .id("thinking-section")
                                }

                                if viewModel.isStreaming && viewModel.streamingContent.isEmpty && !viewModel.streamingLifecycle.shouldShowThinkingDetails {
                                    StreamingIndicator()
                                        .id("streaming")
                                }

                                if showAssistantFeedback {
                                    AssistantResponseFeedbackView(
                                        selectedRating: $selectedAssistantRating,
                                        submitted: assistantFeedbackSubmitted,
                                        onSubmit: handleAssistantFeedbackSubmit,
                                        onRequestFeature: {
                                            onReportIssue?(.featureRequest())
                                        }
                                    )
                                    .padding(.leading, scrollGeo.size.width > ChatResponsiveBreakpoint.assistantStacked ? 75 : 0)
                                    .padding(.trailing, scrollGeo.size.width > ChatResponsiveBreakpoint.assistantStacked ? 20 : 0)
                                    .id("assistant-response-feedback")
                                }

                                if !viewModel.followUpSuggestions.isEmpty && !viewModel.isStreaming {
                                    FollowUpSuggestions(
                                        suggestions: viewModel.followUpSuggestions,
                                        category: followUpSuggestionCategory,
                                        icon: followUpSuggestionIcon
                                    ) { suggestion in
                                        messageText = suggestion
                                    }
                                    .padding(.leading, scrollGeo.size.width > ChatResponsiveBreakpoint.assistantStacked ? 75 : 0)
                                    .padding(.trailing, scrollGeo.size.width > ChatResponsiveBreakpoint.assistantStacked ? 20 : 0)
                                    .id("follow-up-suggestions")
                                }
                            }
                            .padding(.horizontal, .spacing4)
                            .padding(.vertical, .spacing4)
                            // Cap message area width on iPad/Mac, centered
                            .frame(maxWidth: 1000)
                            .frame(maxWidth: .infinity)

                            scrollSentinel(id: "scroll-bottom", edge: .bottom)
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .coordinateSpace(name: "chat-scroll")
                    .contentShape(Rectangle())
                    .onTapGesture {
                        dismissInputIfNeeded()
                    }
                    .onPreferenceChange(ChatScrollSentinelPreferenceKey.self) { values in
                        updateScrollNavState(values: values, viewportHeight: scrollGeo.size.height)
                    }
                    .onPreferenceChange(ChatMessageFramePreferenceKey.self) { frames in
                        trackVisibleMessage(frames: frames, viewportHeight: scrollGeo.size.height)
                    }

                    if !viewModel.messages.isEmpty && !isAtTop {
                        scrollNavButton(isTop: true) {
                            withAnimation(.easeInOut(duration: 0.25)) {
                                proxy.scrollTo("scroll-top", anchor: .top)
                            }
                        }
                        .padding(.top, 18)
                        .frame(maxHeight: .infinity, alignment: .top)
                    }

                    if !viewModel.messages.isEmpty && !isAtBottom {
                        scrollNavButton(isTop: false) {
                            withAnimation(.easeInOut(duration: 0.25)) {
                                proxy.scrollTo("scroll-bottom", anchor: .bottom)
                            }
                        }
                        .frame(maxHeight: .infinity, alignment: .bottom)
                    }

                    if effectiveBannerState != nil {
                        chatFloatingActions
                            .padding(.top, .spacing4)
                            .padding(.horizontal, .spacing6)
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                    }
                }
                .onAppear {
                    resetScrollRestoration()
                    proxy.scrollTo("scroll-top", anchor: .top)
                }
                .onChange(of: chatId) { _, _ in
                    resetScrollRestoration()
                    proxy.scrollTo("scroll-top", anchor: .top)
                }
                .onChange(of: viewModel.messages.map(\.id)) { _, _ in
                    restoreInitialScrollIfNeeded(proxy: proxy)
                    scrollToSearchTargetIfNeeded(proxy: proxy)
                }
                .onChange(of: searchTarget) { _, _ in
                    scrollToSearchTargetIfNeeded(proxy: proxy)
                }
            }
        }
    }

    private func scrollToSearchTargetIfNeeded(proxy: ScrollViewProxy) {
        guard let targetMessageId = searchTarget?.messageId else { return }
        if viewModel.messages.contains(where: { $0.id == targetMessageId }) {
            withAnimation(.easeInOut(duration: 0.25)) {
                proxy.scrollTo(targetMessageId, anchor: UnitPoint(x: 0.5, y: 0.18))
            }
            NativeSyncPerfLog.info("phase=chatSearchScroll chat=\(chatId.prefix(8)) message=\(targetMessageId.prefix(8)) mode=visible")
            return
        }

        guard viewModel.hasOlderMessages, !viewModel.isLoadingOlder else { return }
        viewModel.loadOlderMessages()
    }

    private func scrollSentinel(id: String, edge: ChatScrollSentinelEdge) -> some View {
        GeometryReader { geo in
            Color.clear.preference(
                key: ChatScrollSentinelPreferenceKey.self,
                value: [edge: edge == .top
                    ? geo.frame(in: .named("chat-scroll")).minY
                    : geo.frame(in: .named("chat-scroll")).maxY
                ]
            )
        }
        .frame(height: 1)
        .id(id)
    }

    private func updateScrollNavState(values: [ChatScrollSentinelEdge: CGFloat], viewportHeight: CGFloat) {
        if let top = values[.top] {
            isAtTop = top >= -8
        }
        if let bottom = values[.bottom] {
            isAtBottom = bottom <= viewportHeight + 8
        }
    }

    private func resetScrollRestoration() {
        hasRestoredInitialScroll = false
        isRestoringScroll = true
        lastReportedVisibleMessageId = nil
        scrollPositionDebounceTask?.cancel()
        scrollPositionDebounceTask = nil
    }

    private func handleAssistantFeedbackSubmit() {
        guard let selectedAssistantRating else { return }
        assistantFeedbackSubmitted = true

        if selectedAssistantRating <= 3 {
            onReportIssue?(.assistantResponseQuality())
        }
    }

    private func restoreInitialScrollIfNeeded(proxy: ScrollViewProxy) {
        guard !hasRestoredInitialScroll, !viewModel.messages.isEmpty else { return }
        hasRestoredInitialScroll = true
        isRestoringScroll = true

        let targetId = viewModel.chat?.lastVisibleMessageId
        let hasTargetMessage = targetId.map { id in viewModel.messages.contains { $0.id == id } } ?? false

        if bannerState != nil || isDemoOrLegalChat {
            proxy.scrollTo("scroll-top", anchor: .top)
            NativeSyncPerfLog.info("phase=chatScrollRestore chat=\(chatId.prefix(8)) mode=publicTop messages=\(viewModel.messages.count)")
        } else if let targetId, hasTargetMessage {
            proxy.scrollTo(targetId, anchor: UnitPoint(x: 0.5, y: 0.12))
            NativeSyncPerfLog.info("phase=chatScrollRestore chat=\(chatId.prefix(8)) mode=saved message=\(targetId.prefix(8)) messages=\(viewModel.messages.count)")
        } else {
            proxy.scrollTo("scroll-top", anchor: .top)
            NativeSyncPerfLog.info("phase=chatScrollRestore chat=\(chatId.prefix(8)) mode=noSavedTop messages=\(viewModel.messages.count)")
        }

        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 120_000_000)
            isRestoringScroll = false
        }
    }

    private func trackVisibleMessage(frames: [String: CGRect], viewportHeight: CGFloat) {
        guard !isRestoringScroll, onScrollPositionChanged != nil, !viewModel.messages.isEmpty else { return }
        let visibleIds = Set(frames.compactMap { id, frame in
            frame.maxY > 0 && frame.minY < viewportHeight ? id : nil
        })
        guard let lastVisibleId = viewModel.messages.last(where: { visibleIds.contains($0.id) })?.id,
              lastVisibleId != lastReportedVisibleMessageId else { return }

        lastReportedVisibleMessageId = lastVisibleId
        scrollPositionDebounceTask?.cancel()
        scrollPositionDebounceTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 500_000_000)
            guard !Task.isCancelled, !isRestoringScroll else { return }
            onScrollPositionChanged?(lastVisibleId)
            NativeSyncPerfLog.info("phase=chatScrollPositionSend chat=\(chatId.prefix(8)) message=\(lastVisibleId.prefix(8))")
        }
    }

    private func scrollNavButton(isTop: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Icon("dropdown", size: 12)
                .foregroundStyle(Color.grey60)
                .rotationEffect(isTop ? .degrees(180) : .degrees(0))
                .frame(width: 120, height: 36)
                .contentShape(RoundedRectangle(cornerRadius: 18))
        }
        .buttonStyle(.plain)
        .opacity(0.7)
        .help(Text(isTop ? AppStrings.scrollToTop : AppStrings.scrollToBottom))
        .accessibilityLabel(isTop ? AppStrings.scrollToTop : AppStrings.scrollToBottom)
        .accessibilityIdentifier(isTop ? "scroll-to-top-button" : "scroll-to-bottom-button")
    }

    private var chatFloatingActions: some View {
        HStack(spacing: .spacing2) {
            HStack(spacing: .spacing2) {
                chatFloatingAction(icon: "share", label: AppStrings.share, accessibilityIdentifier: "chat-share-button") {
                    onShareChat?()
                }
                chatFloatingAction(icon: "bug", label: AppStrings.settingsReportIssue) {
                    onReportIssue?(.assistantResponseQuality())
                }
            }

            Spacer(minLength: .spacing6)

            chatFloatingAction(icon: "reminder", label: AppStrings.setReminder) {
                showReminder = true
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func chatFloatingAction(
        icon: String,
        label: String,
        accessibilityIdentifier: String? = nil,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Icon(icon, size: 22)
                .foregroundStyle(LinearGradient.primary)
                .frame(width: 44, height: 44)
                .background(Color.grey0.opacity(0.92))
                .clipShape(Circle())
                .shadow(color: .black.opacity(0.18), radius: 12, x: 0, y: 4)
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .ignore)
        .help(Text(label))
        .accessibilityLabel(label)
        .accessibilityIdentifier(accessibilityIdentifier ?? "chat-floating-action-\(icon)")
        .accessibilityAddTraits(.isButton)
    }

    // MARK: - Streaming banner

    private func messageActionsOverlay(for message: Message) -> some View {
        ZStack {
            Color.black.opacity(0.28)
                .ignoresSafeArea()
                .onTapGesture {
                    actionMessage = nil
                }

            VStack(alignment: .leading, spacing: .spacing2) {
                Text(message.role == .user ? "You" : "OpenMates")
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.grey100)
                    .padding(.horizontal, .spacing4)
                    .padding(.top, .spacing3)

                messageActionRow(icon: "copy", title: AppStrings.copyMessage) {
                    copyMessage(message)
                    actionMessage = nil
                }

                messageActionRow(icon: "copy", title: AppStrings.forkConversation) {
                    Task { await viewModel.forkFromMessage(message.id) }
                    actionMessage = nil
                }

                messageActionRow(icon: "delete", title: AppStrings.deleteMessage, isDestructive: true) {
                    Task { await viewModel.deleteMessage(message.id) }
                    actionMessage = nil
                }
            }
            .padding(.spacing4)
            .frame(minWidth: 140, maxWidth: 260)
            .background(Color.greyBlue)
            .clipShape(RoundedRectangle(cornerRadius: .radius5))
            .shadow(color: .black.opacity(0.22), radius: 16, x: 0, y: 8)
        }
    }

    private func messageActionRow(
        icon: String,
        title: String,
        isDestructive: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: .spacing3) {
                Icon(icon, size: 17)
                    .foregroundStyle(isDestructive ? Color.error : Color.grey100)
                Text(title)
                    .font(.omSmall)
                    .fontWeight(.medium)
                    .foregroundStyle(isDestructive ? Color.error : Color.grey100)
                Spacer()
            }
            .frame(minHeight: 44)
            .padding(.horizontal, .spacing8)
            .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
            .contentShape(RoundedRectangle(cornerRadius: .radiusFull))
        }
        .buttonStyle(.plain)
    }

    private func copyMessage(_ message: Message) {
        #if os(iOS)
        UIPasteboard.general.string = message.content ?? ""
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(message.content ?? "", forType: .string)
        #endif
        ToastManager.shared.show(AppStrings.copied, type: .success)
    }

    private var streamingBanner: some View {
        HStack(spacing: .spacing3) {
            ProgressView()
                .scaleEffect(0.8)
            Text(AppStrings.aiResponding)
                .font(.omXs)
                .foregroundStyle(Color.fontSecondary)
            Spacer()
            Button(AppStrings.stop) {
                viewModel.stopStreaming()
            }
            .font(.omXs)
            .foregroundStyle(Color.error)
            .help(Text(AppStrings.stopResponse))
            .accessibilityLabel(AppStrings.stopResponse)
        }
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing2)
        .background(Color.grey0)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(AppStrings.aiResponding)
        .accessibilityIdentifier("streaming-banner")
    }

    // MARK: - New chat CTA (replaces input for demo/intro/legal chats)

    private var newChatCTA: some View {
        Button {
            openNewChat()
        } label: {
            HStack(spacing: .spacing3) {
                Icon("create", size: 18)
                    .foregroundStyle(Color.fontButton)
                Text(AppStrings.newChat)
                    .font(.omP)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontButton)
            }
            .frame(maxWidth: .infinity)
            .frame(height: 48)
            .background(Color.buttonPrimary)
            .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("new-chat-button")
        .frame(maxWidth: MessageComposerMetric.mainAppMaxWidth)
        .frame(maxWidth: .infinity)
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing3)
        .background(Color.grey20)
    }

    // MARK: - Input bar

    private var exampleChatInputRow: some View {
        VStack(spacing: isInputFocused ? .spacing3 : 0) {
            HStack(alignment: .bottom, spacing: .spacing3) {
                newChatInlineButton
                    .frame(width: isInputFocused ? 0 : (useCompactInlineNewChat ? 48 : nil), height: 48)
                    .opacity(isInputFocused ? 0 : 1)
                    .clipped()
                    .allowsHitTesting(!isInputFocused)

                inputField(
                    compact: !isInputFocused && messageText.isEmpty,
                    placeholder: AppStrings.typeFollowup,
                    expandedMinHeight: MessageComposerMetric.expandedMinHeight
                )
            }

            if isInputFocused {
                inputDismissButton
                    .transition(.opacity)
            }
        }
        .frame(maxWidth: 1000)
        .frame(maxWidth: .infinity)
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing3)
        .background(Color.grey0)
        .animation(.easeInOut(duration: 0.25), value: isInputFocused)
    }

    private var inputBar: some View {
        VStack(spacing: .spacing3) {
            subChatBroadcastToggle
            inputField(compact: false, placeholder: AppStrings.typeMessage)
        }
            .frame(maxWidth: MessageComposerMetric.mainAppMaxWidth)
            .frame(maxWidth: .infinity)
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing3)
            .background(Color.grey0)
    }

    @ViewBuilder
    private var subChatLifecyclePanel: some View {
        if let request = viewModel.subChatApprovalRequest {
            subChatApprovalCard(request)
        } else if let progress = viewModel.subChatProgress {
            subChatProgressBar(progress)
        }
    }

    @ViewBuilder
    private var returnToParentButton: some View {
        if let parentId = viewModel.chat?.parentId {
            Button {
                onOpenChat?(parentId)
            } label: {
                HStack(spacing: .spacing4) {
                    Icon("arrow-left", size: 14)
                        .foregroundStyle(Color.buttonPrimary)
                    Text(LocalizationManager.shared.text("chat.sub_chats.return_to_parent"))
                        .font(.omXs)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.fontSecondary)
                    Spacer()
                }
                .padding(.horizontal, .spacing8)
                .padding(.vertical, .spacing3)
                .background(Color.grey0)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("return-to-parent-button")
        }
    }

    private func subChatApprovalCard(_ request: SubChatApprovalRequest) -> some View {
        let count = request.subChats?.count ?? 0
        return VStack(alignment: .leading, spacing: .spacing5) {
            Text(LocalizationManager.shared.text("chat.sub_chats.confirmation_title", replacements: ["count": String(count)]))
                .font(.omP)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)
            Text(LocalizationManager.shared.text(
                "chat.sub_chats.confirmation_description",
                replacements: [
                    "auto": String(request.maxAutoSubChats ?? 0),
                    "max": String(request.maxDirectSubChats ?? count)
                ]
            ))
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
            subChatPromptPreview(request.subChats ?? [])
            HStack(spacing: .spacing4) {
                subChatActionButton(
                    title: LocalizationManager.shared.text("chat.sub_chats.start_all", replacements: ["count": String(count)]),
                    primary: true,
                    identifier: "sub-chat-approve-button"
                ) {
                    Task { await viewModel.approveSubChatRequest() }
                }
                subChatActionButton(
                    title: AppStrings.cancel,
                    primary: false,
                    identifier: "sub-chat-cancel-button"
                ) {
                    Task { await viewModel.cancelSubChatRequest() }
                }
            }
        }
        .padding(.spacing8)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius8))
        .padding(.horizontal, .spacing8)
        .padding(.bottom, .spacing4)
        .accessibilityIdentifier("sub-chat-approval-card")
    }

    private func subChatPromptPreview(_ subChats: [SpawnedSubChat]) -> some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            ForEach(subChats.prefix(3)) { child in
                Text(child.title ?? child.prompt)
                    .font(.omXs)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)
            }
        }
    }

    private func subChatActionButton(title: String, primary: Bool, identifier: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.omSmall)
                .fontWeight(.semibold)
                .foregroundStyle(primary ? Color.fontButton : Color.fontPrimary)
                .padding(.horizontal, .spacing8)
                .padding(.vertical, .spacing4)
                .background(primary ? Color.buttonPrimary : Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius8))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(identifier)
    }

    private func subChatProgressBar(_ progress: SubChatProgress) -> some View {
        HStack(spacing: .spacing5) {
            Text(subChatProgressLabel(progress))
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
            Spacer()
            Button {
                Task { await viewModel.stopSubChats() }
            } label: {
                Text(LocalizationManager.shared.text("chat.sub_chats.stop_queue"))
                    .font(.omXs)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                    .padding(.horizontal, .spacing6)
                    .padding(.vertical, .spacing3)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("sub-chat-stop-button")
        }
        .padding(.horizontal, .spacing8)
        .padding(.vertical, .spacing4)
        .background(Color.grey0)
        .accessibilityIdentifier("sub-chat-progress-bar")
    }

    @ViewBuilder
    private var subChatBroadcastToggle: some View {
        if viewModel.chat?.isSubChat == true {
            Button {
                broadcastToSiblingSubChats.toggle()
            } label: {
                HStack(spacing: .spacing4) {
                    if broadcastToSiblingSubChats {
                        Icon("select", size: 14)
                            .foregroundStyle(Color.buttonPrimary)
                    } else {
                        Circle()
                            .stroke(Color.fontTertiary, lineWidth: 1.5)
                            .frame(width: 14, height: 14)
                    }
                    Text(LocalizationManager.shared.text("chat.sub_chats.broadcast_to_siblings"))
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                    Spacer()
                }
                .padding(.horizontal, .spacing5)
                .padding(.vertical, .spacing3)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("sub-chat-broadcast-toggle")
        }
    }

    private func subChatProgressLabel(_ progress: SubChatProgress) -> String {
        if progress.status == "stopping" {
            return LocalizationManager.shared.text("chat.sub_chats.progress_stopping")
        }
        return LocalizationManager.shared.text(
            "chat.sub_chats.progress_label",
            replacements: [
                "completed": String(progress.completed ?? 0),
                "total": String(progress.total ?? 0)
            ]
        )
    }

    private func inputField(compact: Bool, placeholder: String, expandedMinHeight: CGFloat = 100) -> some View {
        let overlayActive = composerOverlay != nil || isUITestRecordingOverlayForced
        let activePIIMatches = detectedPIIMatches.filter { !piiExclusions.contains($0.id) }
        let maximumViewportFieldHeight = max(expandedMinHeight, chatViewportHeight - .spacing20)
        let overlayHeight = min(400, maximumViewportFieldHeight)
        return VStack(spacing: .spacing2) {
            MessageComposerView(
                session: composerSession,
                isFocused: $isInputFocused,
                compact: compact && !overlayActive,
                placeholder: placeholder,
                expandedMinHeight: isComposerExpanded
                    ? maximumViewportFieldHeight
                    : (overlayActive ? overlayHeight : expandedMinHeight),
                maxWidth: MessageComposerMetric.mainAppMaxWidth,
                accessibilityHint: AppStrings.typeMessage,
                isComposerEditable: deferredComposerSendContexts.isEmpty,
                onSubmit: sendMessage,
                inlineFieldContent: nil
            ) {
                PIIWarningBanner(matches: activePIIMatches) {
                    piiExclusions.formUnion(detectedPIIMatches.map(\.id))
                }

                if enhancedPIIModelController.isDownloadConfigured,
                   enhancedPIIRecommendationStore.shouldRecommend(
                       regexMatches: activePIIMatches,
                       modelStatus: enhancedPIIModelController.status
                   ) {
                    EnhancedPIIModelSuggestionBanner(
                        onDownload: { Task { await enhancedPIIModelController.performPrimaryAction() } },
                        onDismiss: { enhancedPIIRecommendationStore.dismiss() }
                    )
                }

                PIIHighlightStrip(matches: activePIIMatches) { match in
                    piiExclusions.insert(match.id)
                }

                if let chatId = viewModel.chat?.id {
                    UploadProgressBar(uploads: pendingUploads.uploadsForChat(chatId))
                }
                if let mentionQuery {
                    MentionDropdownView(
                        query: mentionQuery,
                        onSelect: insertMention,
                        onDismiss: { self.mentionQuery = nil }
                    )
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, .spacing5)
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
                }
            } overlayContent: {
                if let overlay = composerOverlayView() {
                    overlay
                }
            } actionButtons: {
                HStack(spacing: .spacing6) {
                AttachmentPicker(
                    isPresented: $showAttachmentMenu,
                    onImageSelected: { data, filename in
                        enqueueAttachmentUpload(data: data, filename: filename)
                    },
                    onFileSelected: { data, filename in
                        enqueueAttachmentUpload(data: data, filename: filename)
                    }
                )
                .help(Text(AppStrings.attachFiles))
                .accessibilityLabel(AppStrings.attachFiles)
                .accessibilityIdentifier("attach-files-button")

                MessageComposerActionIcon(icon: "maps", label: AppStrings.shareLocation) {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        composerOverlay = .location
                        isInputFocused = false
                    }
                }

                MessageComposerActionIcon(icon: "whiteboard", label: AppStrings.sketchAction) {
                    #if os(iOS)
                    withAnimation(.easeInOut(duration: 0.2)) {
                        composerOverlay = .sketch
                        isInputFocused = false
                    }
                    #else
                    ToastManager.shared.show(AppStrings.sketchAction, type: .info)
                    #endif
                }

                Spacer()

                #if os(iOS)
                MessageComposerActionIcon(icon: "camera", label: AppStrings.takePhoto, identifier: "take-photo-button") {
                    showCameraCapture = true
                }
                #endif

                if messageText.isEmpty && !viewModel.hasPendingComposerEmbeds && !composerHasEmbed && !viewModel.isStreaming {
                    recordActionControls
                } else {
                    MessageComposerSendButton(
                        title: AppStrings.sendAction,
                        disabled: messageText.isEmpty && !viewModel.hasPendingComposerEmbeds && !composerHasEmbed,
                        accessibilityLabel: AppStrings.sendMessage,
                        action: sendMessage
                    )
                    .accessibilityHint(AppStrings.typeMessage)
                    #if os(macOS)
                    .keyboardShortcut(.return, modifiers: .command)
                    #endif
                }
                }
                .padding(.horizontal, .spacing5)
                .padding(.bottom, .spacing6)
            }
            .overlay(alignment: .topTrailing) {
                if !overlayActive && (isInputFocused || !messageText.isEmpty || composerHasEmbed || isComposerExpanded) {
                    Button {
                        isComposerExpanded.toggle()
                        isInputFocused = false
                    } label: {
                        Icon(isComposerExpanded ? "minimize" : "fullscreen", size: 20)
                            .foregroundStyle(LinearGradient.primary)
                            .frame(width: 30, height: 30)
                    }
                    .buttonStyle(.plain)
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
                    .padding(.top, 10)
                    .padding(.trailing, 15)
                    .help(Text(isComposerExpanded ? AppStrings.exitFullscreen : AppStrings.enterFullscreen))
                    .accessibilityLabel(isComposerExpanded ? AppStrings.exitFullscreen : AppStrings.enterFullscreen)
                    .accessibilityIdentifier("message-input-fullscreen-button")
                    .zIndex(10)
                }
            }

            if let queuedMessageText = viewModel.streamingLifecycle.queuedMessageText {
                Text(queuedMessageText)
                    .font(.omXs)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, .spacing5)
                    .padding(.vertical, .spacing2)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radius8))
                    .padding(.horizontal, .spacing5)
                    .accessibilityIdentifier("queued-message-indicator")
            }

            if let recordPermissionHintText {
                Text(recordPermissionHintText)
                    .font(.omXs)
                    .foregroundStyle(micPermissionState == .denied ? Color.error : Color.fontTertiary)
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .padding(.horizontal, .spacing5)
                    .transition(.opacity)
            }
        }
        .frame(maxWidth: MessageComposerMetric.mainAppMaxWidth)
    }

    private func composerOverlayView() -> AnyView? {
        #if DEBUG
        if composerOverlay == nil, isUITestRecordingOverlayForced {
            return recordingOverlayView()
        }
        #endif
        guard let composerOverlay else { return nil }
        switch composerOverlay {
        case .location:
            return AnyView(
                ComposerLocationOverlay(
                    isFullscreen: $isComposerExpanded,
                    onShare: insertSharedLocation,
                    onCancel: { self.composerOverlay = nil }
                )
            )
        case .sketch:
            #if os(iOS)
            return AnyView(
                SketchComposerOverlay(
                    isFullscreen: $isComposerExpanded,
                    onSave: { data, filename in
                        self.composerOverlay = nil
                        enqueueAttachmentUpload(data: data, filename: filename)
                    },
                    onCancel: { self.composerOverlay = nil }
                )
            )
            #else
            return nil
            #endif
        case .recording:
            return recordingOverlayView()
        }
    }

    private func recordingOverlayView() -> AnyView {
        AnyView(
            ComposerRecordingOverlay(
                recorder: composerRecorder,
                dragOffsetX: recordDragOffsetX,
                startedFromKeyboard: recordStartedFromKeyboard,
                onStop: { url in
                    self.composerOverlay = nil
                    self.recordAttemptActive = false
                    self.recordStartedFromKeyboard = false
                    self.recordDragOffsetX = 0
                    Task {
                        await enqueueRecordingUpload(url: url, duration: composerRecorder.duration)
                    }
                },
                onCancel: {
                    composerRecorder.cancelRecording()
                    self.composerOverlay = nil
                    self.recordAttemptActive = false
                    self.recordStartedFromKeyboard = false
                    self.recordDragOffsetX = 0
                }
            )
        )
    }

    private var isUITestRecordingOverlayForced: Bool {
        #if DEBUG
        return ProcessInfo.processInfo.arguments.contains("--ui-test-force-recording-overlay")
            || ProcessInfo.processInfo.arguments.contains("--ui-test-force-keyboard-recording-overlay")
            || ProcessInfo.processInfo.environment["UI_TEST_FORCE_RECORDING_OVERLAY"] == "1"
            || ProcessInfo.processInfo.environment["UI_TEST_FORCE_KEYBOARD_RECORDING_OVERLAY"] == "1"
        #else
        return false
        #endif
    }

    private var isUITestKeyboardRecordingOverlayForced: Bool {
        #if DEBUG
        return ProcessInfo.processInfo.arguments.contains("--ui-test-force-keyboard-recording-overlay")
            || ProcessInfo.processInfo.environment["UI_TEST_FORCE_KEYBOARD_RECORDING_OVERLAY"] == "1"
        #else
        return false
        #endif
    }

    private func applyUITestRecordingOverlayIfNeeded() {
        #if DEBUG
        guard isUITestRecordingOverlayForced else { return }
        micPermissionState = .granted
        recordStartedFromKeyboard = isUITestKeyboardRecordingOverlayForced
        composerOverlay = .recording
        isInputFocused = true
        #endif
    }

    private var newChatInlineButton: some View {
        Button {
            openNewChat()
        } label: {
            HStack(spacing: .spacing4) {
                Icon("create", size: 20)
                    .foregroundStyle(Color.fontButton)
                if !useCompactInlineNewChat {
                    Text(AppStrings.newChat)
                        .font(.omP)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.fontButton)
                }
            }
            .frame(width: useCompactInlineNewChat ? 48 : nil, height: 48)
            .padding(.horizontal, useCompactInlineNewChat ? 0 : .spacing8)
            .background(Color.buttonPrimary)
            .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
            .shadow(color: .black.opacity(0.15), radius: 8, x: 0, y: 2)
        }
        .buttonStyle(.plain)
        .help(Text(AppStrings.newChat))
        .accessibilityLabel(AppStrings.newChat)
        .accessibilityIdentifier("new-chat-button")
    }

    private func enqueueAttachmentUpload(data: Data, filename: String) {
        let nodeID = "composer:embed:\(UUID().uuidString.lowercased())"
        do {
            try composerSession.insertPendingEmbed(
                nodeID: nodeID,
                embedType: composerEmbedType(for: filename),
                title: filename,
                localPreviewData: data
            )
            let record = composerEmbedLifecycle.register(nodeId: nodeID)
            try composerSession.configureEmbedActions(
                nodeID: nodeID,
                onOpen: { _ in },
                onRetry: { _ in
                    Task { @MainActor in retryAttachmentUpload(nodeID: nodeID, data: data, filename: filename) }
                },
                onRemove: { durableID in handleComposerEmbedRemoval(nodeID: nodeID, durableID: durableID) }
            )
            guard transitionComposerEmbed(
                nodeID: nodeID,
                generation: record.generation,
                to: .uploading
            ) != nil else { return }
        } catch {
            NativeDiagnostics.error("Composer attachment insertion failed: \(type(of: error))", category: "apple_composer")
            return
        }

        guard let generation = composerEmbedLifecycle.record(nodeId: nodeID)?.generation else { return }
        Task { @MainActor in
            guard let embed = await viewModel.uploadAttachment(data: data, filename: filename) else {
                _ = transitionComposerEmbed(nodeID: nodeID, generation: generation, to: .error)
                return
            }
            resolveComposerEmbed(nodeID: nodeID, generation: generation, embed: embed)
        }
    }

    private func insertSharedLocation(_ selection: ComposerLocationSelection) {
        let embed = selection.makePendingEmbed()
        let nodeID = "composer:embed:\(UUID().uuidString.lowercased())"
        do {
            try composerSession.insertPendingEmbed(
                nodeID: nodeID,
                embedType: "maps",
                title: selection.name
            )
            try composerSession.resolveEmbed(
                nodeID: nodeID,
                durableEmbedID: embed.id,
                referenceType: embed.referenceType,
                status: AppleComposerEmbedLifecycleState.finished.rawValue,
                embedRecord: embed.record
            )
            try composerSession.configureEmbedActions(
                nodeID: nodeID,
                onOpen: { _ in },
                onRetry: { _ in },
                onRemove: { _ in resolvedComposerEmbeds.removeValue(forKey: nodeID) }
            )
            resolvedComposerEmbeds[nodeID] = embed
            composerOverlay = nil
        } catch {
            NativeDiagnostics.error(
                "Composer location insertion failed: \(type(of: error))",
                category: "apple_composer"
            )
        }
    }

    private func retryAttachmentUpload(nodeID: String, data: Data, filename: String) {
        guard let generation = retryComposerEmbed(nodeID: nodeID, to: .uploading) else { return }
        Task { @MainActor in
            guard let embed = await viewModel.uploadAttachment(data: data, filename: filename) else {
                _ = transitionComposerEmbed(nodeID: nodeID, generation: generation, to: .error)
                return
            }
            resolveComposerEmbed(nodeID: nodeID, generation: generation, embed: embed)
        }
    }

    private func enqueueRecordingUpload(url: URL, duration: TimeInterval) async {
        let nodeID = "composer:embed:\(UUID().uuidString.lowercased())"
        do {
            try composerSession.insertPendingEmbed(
                nodeID: nodeID,
                embedType: "recording",
                title: url.lastPathComponent
            )
            let record = composerEmbedLifecycle.register(nodeId: nodeID)
            try composerSession.configureEmbedActions(
                nodeID: nodeID,
                onOpen: { _ in },
                onRetry: { _ in
                    Task { @MainActor in await retryRecordingUpload(nodeID: nodeID, url: url, duration: duration) }
                },
                onRemove: { durableID in handleComposerEmbedRemoval(nodeID: nodeID, durableID: durableID) }
            )
            guard transitionComposerEmbed(
                nodeID: nodeID,
                generation: record.generation,
                to: .uploading
            ) != nil,
            transitionComposerEmbed(
                nodeID: nodeID,
                generation: record.generation,
                to: .transcribing
            ) != nil else { return }
        } catch {
            NativeDiagnostics.error("Composer recording insertion failed: \(type(of: error))", category: "apple_composer")
            return
        }

        guard let generation = composerEmbedLifecycle.record(nodeId: nodeID)?.generation else { return }
        guard let embed = await viewModel.uploadRecording(url: url, duration: duration) else {
            _ = transitionComposerEmbed(nodeID: nodeID, generation: generation, to: .error)
            return
        }
        resolveComposerEmbed(nodeID: nodeID, generation: generation, embed: embed)
    }

    private func retryRecordingUpload(nodeID: String, url: URL, duration: TimeInterval) async {
        guard let generation = retryComposerEmbed(nodeID: nodeID, to: .transcribing) else { return }
        guard let embed = await viewModel.uploadRecording(url: url, duration: duration) else {
            _ = transitionComposerEmbed(nodeID: nodeID, generation: generation, to: .error)
            return
        }
        resolveComposerEmbed(nodeID: nodeID, generation: generation, embed: embed)
    }

    private func resolveComposerEmbed(nodeID: String, generation: Int, embed: ComposerPendingEmbed) {
        if let current = composerEmbedLifecycle.record(nodeId: nodeID),
           (current.generation != generation || current.state == .cancelled) {
            // The service may have registered a stale result before this callback.
            // Remove it from the send boundary without recreating the visible atom.
            viewModel.removePendingComposerEmbed(id: embed.id)
            return
        }
        let state = AppleComposerEmbedLifecycleState(rawValue: embed.status) ?? .finished
        guard transitionComposerEmbed(
            nodeID: nodeID,
            generation: generation,
            to: state,
            durableEmbedID: embed.id
        ) != nil else { return }
        do {
            try composerSession.resolveEmbed(
                nodeID: nodeID,
                durableEmbedID: embed.id,
                referenceType: embed.referenceType,
                status: state.rawValue,
                embedRecord: embed.record,
                localPreviewData: embed.localData
            )
            resolvedComposerEmbeds[nodeID] = embed
        } catch {
            NativeDiagnostics.error("Composer attachment resolution failed: \(type(of: error))", category: "apple_composer")
        }
    }

    @discardableResult
    private func transitionComposerEmbed(
        nodeID: String,
        generation: Int,
        to state: AppleComposerEmbedLifecycleState,
        durableEmbedID: String? = nil
    ) -> ComposerEmbedLifecycleRecord? {
        guard case .applied(let record) = composerEmbedLifecycle.transition(
            nodeId: nodeID,
            generation: generation,
            to: state,
            durableEmbedId: durableEmbedID
        ) else { return nil }
        do {
            try composerSession.updateEmbed(nodeID: nodeID, status: state.rawValue)
        } catch {
            NativeDiagnostics.error("Composer embed lifecycle update failed: \(type(of: error))", category: "apple_composer")
            return nil
        }
        reportComposerEmbedState(record)
        return record
    }

    private func retryComposerEmbed(
        nodeID: String,
        to state: AppleComposerEmbedLifecycleState
    ) -> Int? {
        guard let current = composerEmbedLifecycle.record(nodeId: nodeID),
              case .applied(let record) = composerEmbedLifecycle.retry(
                  nodeId: nodeID,
                  generation: current.generation,
                  to: state
              ) else { return nil }
        do {
            try composerSession.updateEmbed(nodeID: nodeID, status: state.rawValue)
        } catch {
            NativeDiagnostics.error("Composer embed retry update failed: \(type(of: error))", category: "apple_composer")
            return nil
        }
        let requestIDs = Array(deferredComposerSendContexts.keys)
        Task { @MainActor in
            for requestID in requestIDs {
                await composerPendingSendCoordinator.replaceBlockerGeneration(
                    requestId: requestID,
                    nodeId: nodeID,
                    generation: record.generation
                )
            }
            await composerPendingSendCoordinator.updateNode(
                nodeId: record.nodeId,
                generation: record.generation,
                state: record.state
            )
            await resumeDeferredComposerSends()
        }
        return record.generation
    }

    private func handleComposerEmbedRemoval(nodeID: String, durableID: String) {
        if let current = composerEmbedLifecycle.record(nodeId: nodeID),
           case .applied(let record) = composerEmbedLifecycle.remove(
               nodeId: nodeID,
               generation: current.generation
           ) {
            reportComposerEmbedState(record)
        }
        viewModel.removePendingComposerEmbed(id: durableID)
        Task { await invalidateDeferredComposerSends() }
    }

    private func reportComposerEmbedState(_ record: ComposerEmbedLifecycleRecord) {
        Task { @MainActor in
            await composerPendingSendCoordinator.updateNode(
                nodeId: record.nodeId,
                generation: record.generation,
                state: record.state
            )
            await resumeDeferredComposerSends()
        }
    }

    private func queueDeferredComposerSend(document: ComposerDocumentV1) {
        guard let destinationID = viewModel.chat?.id,
              !deferredComposerSendRevisions.contains(composerSession.revision) else { return }
        let blockers = composerBlockers(in: document)
        guard !blockers.isEmpty else { return }
        let blockerNodeIDs = Set(blockers.map(\.nodeId))
        guard !deferredComposerSendNodeIDs.values.contains(where: { !$0.isDisjoint(with: blockerNodeIDs) }) else {
            return
        }

        let requestID = UUID().uuidString.lowercased()
        let snapshot = ComposerSendSnapshot(
            requestId: requestID,
            messageId: UUID().uuidString.lowercased(),
            destinationId: destinationID,
            documentRevision: composerSession.revision,
            document: document,
            blockers: blockers
        )
        deferredComposerSendRevisions.insert(snapshot.documentRevision)
        deferredComposerSendContexts[requestID] = ComposerDeferredSendContext(
            excludedPIIIds: piiExclusions,
            broadcastToSiblings: broadcastToSiblingSubChats
        )
        deferredComposerSendNodeIDs[requestID] = Set(document.nodes.map(\.id))
        viewModel.error = nil

        Task { @MainActor in
            guard await composerPendingSendCoordinator.enqueue(snapshot) else {
                deferredComposerSendRevisions.remove(snapshot.documentRevision)
                deferredComposerSendContexts.removeValue(forKey: requestID)
                return
            }
            await resumeDeferredComposerSends()
        }
    }

    private func composerBlockers(in document: ComposerDocumentV1) -> [ComposerEmbedBlocker] {
        document.nodes.compactMap { node in
            guard node.kind == "embed",
                  let status = node.status,
                  let state = AppleComposerEmbedLifecycleState(rawValue: status),
                  ComposerEmbedLifecycle.isBlocking(state) else { return nil }
            let record = composerEmbedLifecycle.record(nodeId: node.id)
                ?? composerEmbedLifecycle.register(nodeId: node.id, state: state)
            reportComposerEmbedState(record)
            return ComposerEmbedBlocker(nodeId: node.id, generation: record.generation)
        }
    }

    private func resumeDeferredComposerSends() async {
        await composerPendingSendCoordinator.resumeReady { snapshot in
            try await dispatchDeferredComposerSend(snapshot)
        }
    }

    private func retryDeferredComposerSendIfNeeded() -> Bool {
        guard !deferredComposerSendContexts.isEmpty else { return false }
        Task { @MainActor in
            for requestID in deferredComposerSendContexts.keys {
                if await composerPendingSendCoordinator.retryFailed(requestId: requestID) {
                    await resumeDeferredComposerSends()
                    return
                }
            }
        }
        return true
    }

    @MainActor
    private func dispatchDeferredComposerSend(_ snapshot: ComposerSendSnapshot) async throws {
        guard let context = deferredComposerSendContexts[snapshot.requestId] else {
            throw ComposerDeferredSendError.missingContext
        }
        let snapshotNodeIDs = deferredComposerSendNodeIDs[snapshot.requestId] ?? []
        let embeds = snapshotNodeIDs.compactMap { resolvedComposerEmbeds[$0] }
        let markdown = try ComposerMarkdownAdapter.serialize(snapshot.document)
        let redaction = await enhancedRedactionResult(in: markdown, excludedIds: context.excludedPIIIds)
        viewModel.error = nil
        await viewModel.sendMessage(
            redaction.redactedText,
            piiMappings: redaction.mappings,
            broadcastToSiblings: context.broadcastToSiblings,
            composerEmbeds: embeds
        )
        guard viewModel.error == nil else { throw ComposerDeferredSendError.sendFailed }

        try composerSession.removeSentSnapshotNodes(snapshot.document)
        detectedPIIMatches = []
        piiExclusions = []
        mentionQuery = nil
        deferredComposerSendRevisions.remove(snapshot.documentRevision)
        deferredComposerSendContexts.removeValue(forKey: snapshot.requestId)
        deferredComposerSendNodeIDs.removeValue(forKey: snapshot.requestId)
        for nodeID in snapshotNodeIDs {
            resolvedComposerEmbeds.removeValue(forKey: nodeID)
        }
        try? await DraftService.shared.clearDraft(chatId: snapshot.destinationId)
    }

    @MainActor
    private func invalidateDeferredComposerSends() async {
        deferredComposerSendContexts.removeAll()
        deferredComposerSendNodeIDs.removeAll()
        resolvedComposerEmbeds.removeAll()
        deferredComposerSendRevisions.removeAll()
        await composerPendingSendCoordinator.invalidateAllForTermination()
    }

    #if DEBUG
    private func insertResolvedUITestEmbed(_ embed: ComposerPendingEmbed) {
        let nodeID = "composer:embed:ui-test"
        do {
            try composerSession.insertPendingEmbed(
                nodeID: nodeID,
                embedType: "image",
                title: embed.filename,
                localPreviewData: embed.localData
            )
            let record = composerEmbedLifecycle.register(nodeId: nodeID)
            resolveComposerEmbed(nodeID: nodeID, generation: record.generation, embed: embed)
        } catch {
            NativeDiagnostics.error("Composer UI fixture insertion failed: \(type(of: error))", category: "apple_composer")
        }
    }
    #endif

    private func composerEmbedType(for filename: String) -> String {
        switch URL(fileURLWithPath: filename).pathExtension.lowercased() {
        case "jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "svg": return "image"
        case "pdf": return "pdf"
        case "m4a", "mp4", "webm", "ogg", "mp3", "wav", "aac": return "recording"
        default: return "docs-doc"
        }
    }

    private var useCompactInlineNewChat: Bool {
        if chatContainerWidth > 0 {
            return chatContainerWidth <= ChatResponsiveBreakpoint.inlineNewChatCompact
        }
        return sizeClass == .compact
    }

    private func openNewChat() {
        if let onNewChat {
            onNewChat()
        } else {
            NotificationCenter.default.post(name: .newChat, object: nil)
        }
    }

    private var inputDismissButton: some View {
        Button {
            flushEncryptedDraft()
            dismissInputIfNeeded()
        } label: {
            Text(messageText.isEmpty ? AppStrings.cancel : AppStrings.saveDraft)
                .font(.omSmall)
                .fontWeight(.medium)
                .foregroundStyle(Color.fontSecondary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, .spacing3)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                .overlay(
                    RoundedRectangle(cornerRadius: .radiusFull)
                        .stroke(Color.grey30, lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
        .help(Text(messageText.isEmpty ? AppStrings.cancel : AppStrings.saveDraft))
        .accessibilityLabel(messageText.isEmpty ? AppStrings.cancel : AppStrings.saveDraft)
    }

    private var recordActionControls: some View {
        HStack(spacing: .spacing4) {
            if recordHintVisible && micPermissionState == .granted {
                Text(AppStrings.pressAndHoldToRecord)
                    .font(.omXs)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontTertiary)
                    .lineLimit(1)
                    .transition(.opacity)
                    .accessibilityIdentifier("press-hold-label")
            }

            recordGestureButton
        }
    }

    private var recordGestureButton: some View {
        Button(action: {}) {
            Icon("recordaudio", size: 25)
                .foregroundStyle(recordAttemptActive ? AnyShapeStyle(Color.error) : AnyShapeStyle(LinearGradient.primary))
                .frame(width: 25, height: 25)
        }
            .buttonStyle(.plain)
            .contentShape(Circle())
            .simultaneousGesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { value in
                        handleRecordGestureChanged(value)
                    }
                    .onEnded { _ in
                        finishRecordAttempt()
                    }
            )
            .help(Text(AppStrings.recordAudio))
            .accessibilityLabel(AppStrings.recordAudio)
            .accessibilityIdentifier("record-audio-button")
    }

    private var recordPermissionHintText: String? {
        if micPermissionState == .denied {
            return AppStrings.microphoneBlocked
        }
        if recordHintVisible && micPermissionState != .granted {
            return AppStrings.allowMicrophoneAccess
        }
        return nil
    }

    private func dismissInputIfNeeded() {
        guard isInputFocused else { return }
        isInputFocused = false
        showAttachmentMenu = false
    }

    private func handleRecordGestureChanged(_ value: DragGesture.Value) {
        if !recordAttemptActive {
            beginRecordAttempt(startLocation: value.startLocation)
        }

        guard composerOverlay == .recording else { return }
        recordDragOffsetX = min(0, value.translation.width)
        let distance = hypot(value.translation.width, value.translation.height)
        if distance > 100 && value.translation.width < -60 {
            cancelRecordAttempt()
        }
    }

    private func beginRecordAttempt(startLocation _: CGPoint) {
        recordStartedFromKeyboard = false
        recordAttemptActive = true
        recordDragOffsetX = 0
        recordStartTask?.cancel()

        if micPermissionState == .denied {
            showRecordHint()
            return
        }

        if micPermissionState == .unknown {
            Task { @MainActor in
                let granted = await composerRecorder.requestPermission()
                micPermissionState = granted ? .granted : .denied
                recordAttemptActive = false
                showRecordHint(duration: granted ? 2500 : 0)
            }
            return
        }

        recordStartTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(200))
            guard !Task.isCancelled, recordAttemptActive, micPermissionState == .granted else { return }
            composerRecorder.startRecording()
            guard composerRecorder.error == nil else {
                micPermissionState = .denied
                recordAttemptActive = false
                showRecordHint(duration: 0)
                return
            }
            withAnimation(.easeInOut(duration: 0.15)) {
                composerOverlay = .recording
                isInputFocused = true
            }
        }
    }

    private func finishRecordAttempt() {
        recordStartTask?.cancel()
        recordStartTask = nil

        if composerOverlay == .recording, let url = composerRecorder.stopRecording() {
            composerOverlay = nil
            recordAttemptActive = false
            recordStartedFromKeyboard = false
            recordDragOffsetX = 0
            Task {
                await enqueueRecordingUpload(url: url, duration: composerRecorder.duration)
            }
            return
        }

        if recordAttemptActive && micPermissionState == .granted {
            showRecordHint()
        }
        recordAttemptActive = false
        recordStartedFromKeyboard = false
        recordDragOffsetX = 0
    }

    private func cancelRecordAttempt() {
        recordStartTask?.cancel()
        recordStartTask = nil
        composerRecorder.cancelRecording()
        composerOverlay = nil
        recordAttemptActive = false
        recordStartedFromKeyboard = false
        recordDragOffsetX = 0
    }

    private func beginKeyboardRecordAttempt() {
        recordStartedFromKeyboard = true
        recordAttemptActive = true
        recordDragOffsetX = 0
        recordStartTask?.cancel()

        if micPermissionState == .denied {
            showRecordHint()
            return
        }

        if micPermissionState == .unknown {
            Task { @MainActor in
                let granted = await composerRecorder.requestPermission()
                micPermissionState = granted ? .granted : .denied
                recordAttemptActive = false
                recordStartedFromKeyboard = false
                showRecordHint(duration: granted ? 2500 : 0)
            }
            return
        }

        recordStartTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(200))
            guard !Task.isCancelled, recordAttemptActive, recordStartedFromKeyboard, micPermissionState == .granted else { return }
            composerRecorder.startRecording()
            guard composerRecorder.error == nil else {
                micPermissionState = .denied
                recordAttemptActive = false
                recordStartedFromKeyboard = false
                showRecordHint(duration: 0)
                return
            }
            withAnimation(.easeInOut(duration: 0.15)) {
                composerOverlay = .recording
                isInputFocused = true
            }
        }
    }

    private func handleKeyboardRecordSpace(_ press: KeyPress) -> KeyPress.Result {
        guard press.modifiers.isEmpty else { return .ignored }

        if press.phase == .up {
            if suppressKeyboardRecordSpaceUntilKeyUp {
                suppressKeyboardRecordSpaceUntilKeyUp = false
                return .handled
            }
            guard recordStartedFromKeyboard else { return .ignored }
            finishRecordAttempt()
            return .handled
        }

        if suppressKeyboardRecordSpaceUntilKeyUp || recordStartedFromKeyboard {
            return .handled
        }

        guard !isInputFocused else { return .ignored }
        beginKeyboardRecordAttempt()
        return .handled
    }

    private func handleKeyboardRecordEscape() -> KeyPress.Result {
        guard recordStartedFromKeyboard else { return .ignored }
        suppressKeyboardRecordSpaceUntilKeyUp = true
        cancelRecordAttempt()
        return .handled
    }

    private func showRecordHint(duration: Int = 2500) {
        recordHintVisible = true
        recordHintTask?.cancel()
        guard duration > 0 else { return }
        recordHintTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(duration))
            guard !Task.isCancelled else { return }
            recordHintVisible = false
        }
    }

    private func sendMessage() {
        guard !retryDeferredComposerSendIfNeeded() else { return }
        let document = composerSession.controller.document
        let decision = ComposerSubmitPolicy.decision(
            document: document,
            platform: .desktop,
            trigger: .sendButton,
            modifiers: [],
            markedTextRange: nil,
            conversionInFlight: false
        )
        if case .deferred = decision {
            queueDeferredComposerSend(document: document)
            return
        }
        guard decision == .submit else { return }

        let text: String
        do {
            text = try composerSession.canonicalMarkdownForSend()
        } catch {
            NativeDiagnostics.error(
                "Composer send serialization failed: \(type(of: error))",
                category: "apple_composer"
            )
            viewModel.error = AppStrings.error
            return
        }
        let excludedIds = piiExclusions
        let documentNodeIDs = document.nodes.filter { $0.kind == "embed" }.map(\.id)
        let composerEmbeds = documentNodeIDs.compactMap { resolvedComposerEmbeds[$0] }
        messageText = ""
        viewModel.error = nil
        detectedPIIMatches = []
        piiExclusions = []
        mentionQuery = nil

        Task { @MainActor in
            let redaction = await enhancedRedactionResult(in: text, excludedIds: excludedIds)
            let sanitizedText = redaction.redactedText
            let piiMappings = redaction.mappings
            await viewModel.sendMessage(
                sanitizedText,
                piiMappings: piiMappings,
                broadcastToSiblings: broadcastToSiblingSubChats,
                composerEmbeds: composerEmbeds.isEmpty ? nil : composerEmbeds
            )
            if viewModel.error != nil {
                messageText = text
            } else {
                for nodeID in documentNodeIDs {
                    resolvedComposerEmbeds.removeValue(forKey: nodeID)
                }
                try? await DraftService.shared.clearDraft(chatId: chatId)
            }
        }
    }

    private func restoreEncryptedDraft() async {
        guard !isDemoOrLegalChat, !isExampleChat else { return }
        do {
            if let draft = try await DraftService.shared.loadDraft(chatId: chatId),
               composerSession.canonicalMarkdown.isEmpty {
                composerSession.replaceMarkdown(draft.canonicalMarkdown)
            }
        } catch ComposerDraftError.masterKeyUnavailable {
            return
        } catch {
            NativeDiagnostics.warning("Encrypted composer draft restore failed: \(type(of: error))", category: "apple_composer")
        }
    }

    private func scheduleEncryptedDraftSave() {
        guard !isDemoOrLegalChat, !isExampleChat else { return }
        draftSaveTask?.cancel()
        let markdown = composerSession.canonicalMarkdown
        let revision = composerSession.revision
        let draftVersion = viewModel.chat?.draftV ?? 0
        draftSaveTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(500))
            guard !Task.isCancelled else { return }
            await saveEncryptedDraft(markdown: markdown, revision: revision, draftVersion: draftVersion)
        }
    }

    private func flushEncryptedDraft() {
        guard !isDemoOrLegalChat, !isExampleChat else { return }
        draftSaveTask?.cancel()
        let markdown = composerSession.canonicalMarkdown
        let revision = composerSession.revision
        let draftVersion = viewModel.chat?.draftV ?? 0
        Task { @MainActor in
            await saveEncryptedDraft(markdown: markdown, revision: revision, draftVersion: draftVersion)
        }
    }

    private func saveEncryptedDraft(markdown: String, revision: Int, draftVersion: Int) async {
        do {
            try await DraftService.shared.saveDraft(
                canonicalMarkdown: markdown,
                preview: String(markdown.prefix(160)),
                chatId: chatId,
                revision: revision,
                draftVersion: draftVersion
            )
        } catch ComposerDraftError.masterKeyUnavailable {
            return
        } catch {
            NativeDiagnostics.warning("Encrypted composer draft save failed: \(type(of: error))", category: "apple_composer")
        }
    }

    private func applyInputFocusRequestIfNeeded() {
        guard inputFocusRequest > 0, handledInputFocusRequest != inputFocusRequest else { return }
        handledInputFocusRequest = inputFocusRequest
        Task { @MainActor in
            await Task.yield()
            isInputFocused = true
        }
    }

    private func applyCameraCaptureRequestIfNeeded() {
        guard cameraCaptureRequest > 0, handledCameraCaptureRequest != cameraCaptureRequest else { return }
        handledCameraCaptureRequest = cameraCaptureRequest
        #if os(iOS)
        Task { @MainActor in
            await Task.yield()
            showCameraCapture = true
        }
        #endif
    }

    private func handleComposerDeferredSend(_ notification: Notification) {
        guard let routeThroughComposer = notification.userInfo?["dispatchThroughActiveComposer"] as? Bool,
              routeThroughComposer,
              let deferredChatId = notification.userInfo?["chatId"] as? String,
              deferredChatId == viewModel.chat?.id,
              let content = notification.userInfo?["content"] as? String else { return }
        let piiMappings = notification.userInfo?["piiMappings"] as? [PIIMapping] ?? []
        Task {
            await viewModel.sendMessage(
                content,
                piiMappings: piiMappings,
                broadcastToSiblings: broadcastToSiblingSubChats
            )
        }
    }

    private func updatePIIMatches(for text: String) {
        let options = piiPrivacySettingsStore.detectionOptions()
        let regexMatches = PIIDetector.detect(in: text, options: options)
        detectedPIIMatches = regexMatches
        let currentIds = Set(detectedPIIMatches.map(\.id))
        piiExclusions = piiExclusions.intersection(currentIds)

        enhancedPIIDetectionTask?.cancel()
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              enhancedPIIModelController.modelDetector != nil else { return }
        let snapshot = text
        enhancedPIIDetectionTask = Task { @MainActor in
            let result = await enhancedDetector.detect(in: snapshot, options: options)
            guard !Task.isCancelled, snapshot == messageText else { return }
            detectedPIIMatches = result.matches
            let currentIds = Set(result.matches.map(\.id))
            piiExclusions = piiExclusions.intersection(currentIds)
        }
    }

    private var enhancedDetector: EnhancedPIIDetector {
        EnhancedPIIDetector(modelDetector: enhancedPIIModelController.modelDetector)
    }

    private func enhancedRedactionResult(in text: String, excludedIds: Set<String>) async -> PIIRedactionResult {
        let options = piiPrivacySettingsStore.detectionOptions()
        let detection = await enhancedDetector.detect(in: text, options: options)
        return PIIDetector.redactionResult(
            in: text,
            matches: detection.matches,
            excludedIds: excludedIds,
            options: options
        )
    }

    private func updateMentionQuery(for text: String) {
        mentionQuery = extractMentionQuery(from: text)
    }

    private func extractMentionQuery(from text: String) -> String? {
        guard let atIndex = text.lastIndex(of: "@") else { return nil }
        if atIndex != text.startIndex {
            let previousIndex = text.index(before: atIndex)
            let previousCharacter = text[previousIndex]
            guard previousCharacter == " " || previousCharacter == "\n" || previousCharacter == "\t" else {
                return nil
            }
        }
        let queryStart = text.index(after: atIndex)
        let query = String(text[queryStart...])
        guard !query.contains(" "), !query.contains("\n"), !query.contains("\t") else { return nil }
        return query
    }

    private func insertMention(_ item: MentionItem) {
        guard let atIndex = messageText.lastIndex(of: "@") else {
            messageText += messageText.isEmpty ? "\(item.mentionSyntax) " : " \(item.mentionSyntax) "
            mentionQuery = nil
            return
        }
        messageText.replaceSubrange(atIndex..<messageText.endIndex, with: "\(item.mentionSyntax) ")
        mentionQuery = nil
        isInputFocused = true
    }

    private func publicChatIconName(for chatId: String) -> String? {
        switch chatId {
        case "demo-for-developers", "example-beautiful-single-page-html":
            return "code"
        case "demo-who-develops-openmates":
            return "user"
        case "announcements-introducing-openmates-v09":
            return "megaphone"
        case "legal-privacy":
            return "shield-check"
        case "legal-terms":
            return "file-text"
        case "legal-imprint":
            return "building"
        case "example-gigantic-airplanes", "example-flights-berlin-bangkok":
            return "plane"
        case "example-artemis-ii-mission":
            return "rocket"
        case "example-eu-chat-control-law":
            return "shield"
        case "example-creativity-drawing-meetups-berlin":
            return "pencil"
        default:
            return nil
        }
    }
}

private struct AssistantResponseFeedbackView: View {
    @Binding var selectedRating: Int?
    let submitted: Bool
    let onSubmit: () -> Void
    let onRequestFeature: () -> Void

    private let ratings = [1, 2, 3, 4, 5]

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if submitted {
                Text(AppStrings.assistantFeedbackThanks)
                    .font(.omSmall)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("assistant-feedback-thanks")
            } else {
                HStack(alignment: .center, spacing: .spacing3) {
                    Text(AppStrings.assistantFeedbackRateLabel)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)

                    HStack(spacing: .spacing1) {
                        ForEach(ratings, id: \.self) { rating in
                            Button {
                                selectedRating = rating
                            } label: {
                                Text(verbatim: "★")
                                    .font(.omP)
                                    .foregroundStyle(starColor(for: rating))
                            }
                            .buttonStyle(.plain)
                            .help(Text(AppStrings.assistantFeedbackStarLabel(count: rating)))
                            .accessibilityLabel(AppStrings.assistantFeedbackStarLabel(count: rating))
                            .accessibilityIdentifier("assistant-feedback-star-\(rating)")
                        }
                    }

                    if selectedRating != nil {
                        Button(action: onSubmit) {
                            Text(submitLabel)
                                .font(.omXs.weight(.semibold))
                                .foregroundStyle(Color.fontButton)
                                .padding(.horizontal, .spacing4)
                                .padding(.vertical, .spacing2)
                                .background(Color.buttonPrimary)
                                .clipShape(RoundedRectangle(cornerRadius: .radius8))
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("assistant-feedback-submit")
                    }
                }
            }

            Button(action: onRequestFeature) {
                Text(AppStrings.requestFeature)
                    .font(.omXs)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontSecondary)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("chat-history-request-feature")
        }
        .padding(.top, .spacing2)
        .accessibilityIdentifier("assistant-response-feedback")
    }

    private var submitLabel: String {
        guard let selectedRating, selectedRating <= 3 else {
            return AppStrings.assistantFeedbackSubmit
        }
        return AppStrings.settingsReportIssue
    }

    private func starColor(for rating: Int) -> Color {
        guard let selectedRating, rating <= selectedRating else {
            return Color.grey50
        }
        return Color.buttonPrimary
    }
}

// MARK: - Message bubble with embed support

struct MessageBubble: View {
    let message: Message
    let chatId: String
    let appId: String?
    let embeds: [EmbedRecord]
    let allEmbedRecords: [String: EmbedRecord]
    let streamingContent: String?
    let piiMappings: [PIIMapping]
    let isPIIRevealed: Bool
    let containerWidth: CGFloat
    let isSearchTarget: Bool
    let searchHighlightQuery: String?
    let onEmbedTap: (EmbedRecord) -> Void
    let onOpenPublicChat: ((String) -> Void)?
    let onInteractiveQuestionSubmit: ((String) -> Void)?
    let onShowActions: (() -> Void)?
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var hasAppeared = false

    var isUser: Bool { message.role == .user }
    /// Web: ≤500px uses stacked layout (avatar above message).
    private var useStackedLayout: Bool {
        if containerWidth > 0 {
            return containerWidth <= ChatResponsiveBreakpoint.assistantStacked
        }
        return sizeClass == .compact
    }
    private var assistantCategory: String? { message.appId ?? appId }

    var displayContent: String {
        let content = streamingContent ?? message.content ?? ""
        guard isPIIRevealed else { return content }
        return PIIDetector.restorePII(in: content, mappings: piiMappings)
    }

    private var viewAllowsInteractiveQuestionSubmit: Bool {
        !isUser && streamingContent == nil
    }

    private var topLevelAppSkillEmbeds: [EmbedRecord] {
        let directParents = embeds.filter { $0.isAppSkillUse }
        if !directParents.isEmpty { return directParents }

        return EmbedRecord.deduplicatedById(
            Array(allEmbedRecords.values),
            context: "chatView.topLevelAppSkillEmbeds"
        )
        .filter { record in
            record.isAppSkillUse && displayContent.contains(record.id)
        }
    }

    private var hiddenInlineEmbedIds: Set<String> {
        Set(topLevelAppSkillEmbeds.map(\.id))
    }

    // MARK: - Assistant avatar with AI badge

    private static let openMatesOfficialChatIds: Set<String> = [
        "demo-for-everyone",
        "demo-for-developers",
        "demo-who-develops-openmates",
        "announcements-introducing-openmates-v09",
        "legal-privacy",
        "legal-terms",
        "legal-imprint"
    ]

    /// True for openmates_official chats — shows OpenMates favicon, hides AI badge.
    private var isOpenMatesOfficial: Bool {
        Self.openMatesOfficialChatIds.contains(chatId)
    }

    /// Gradient for the avatar — openmates_official and default "ai" use .primary (blue/purple).
    private var avatarGradient: LinearGradient {
        if isOpenMatesOfficial { return .primary }
        return (assistantCategory == nil || assistantCategory == "ai") ? .primary : AppIconView.gradient(forAppId: assistantCategory!)
    }

    // Web: .mate-profile = 60px; .mate-profile-small-mobile (≤500px container) = 25px
    private var avatarSize: CGFloat { useStackedLayout ? 25 : 60 }
    private var avatarIconSize: CGFloat { useStackedLayout ? 12 : 30 }
    // Web: AI badge — normal: 24/16px, small-mobile: 12/8px
    private var badgeSize: CGFloat { useStackedLayout ? 12 : 24 }
    private var badgeIconSize: CGFloat { useStackedLayout ? 8 : 16 }

    private var assistantAvatar: some View {
        Group {
            if isOpenMatesOfficial {
                // Web: .mate-profile.openmates_official — favicon as background-image,
                // background-size:contain, border-radius:50%, no AI badge.
                // Use the PNG brand asset because Xcode distorts this colorful SVG.
                Image("openmates-brand")
                    .renderingMode(.original)
                    .resizable()
                    .scaledToFill()
                    .frame(width: avatarSize, height: avatarSize)
                    .clipShape(Circle())
            } else {
                assistantCategoryAvatar
                    .overlay(alignment: .bottomTrailing) {
                        Circle()
                            .fill(Color.grey0)
                            .frame(width: badgeSize, height: badgeSize)
                            .overlay {
                                Icon("ai", size: badgeIconSize)
                                    .foregroundStyle(LinearGradient.primary)
                            }
                            .shadow(color: .black.opacity(0.10), radius: 2, x: 0, y: 1)
                    }
            }
        }
        .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
    }

    @ViewBuilder
    private var assistantCategoryAvatar: some View {
        if let assistantCategory, let image = categoryProfileImage(for: assistantCategory) {
            image
                .renderingMode(.original)
                .resizable()
                .scaledToFill()
                .frame(width: avatarSize, height: avatarSize)
                .clipShape(Circle())
        } else {
            Circle()
                .fill(avatarGradient)
                .frame(width: avatarSize, height: avatarSize)
                .overlay {
                    Icon(AppIconView.iconName(forAppId: assistantCategory ?? "ai"), size: avatarIconSize)
                        .foregroundStyle(.white)
                }
        }
    }

    private func categoryProfileImage(for category: String) -> Image? {
        guard CategoryMapping.isKnownCategory(category) else { return nil }
        #if os(iOS)
        let path = Bundle.main.path(forResource: category, ofType: "jpeg", inDirectory: "mates")
            ?? Bundle.main.path(forResource: category, ofType: "jpeg", inDirectory: "Mates")
            ?? Bundle.main.path(forResource: category, ofType: "jpeg")
        guard let path, let image = UIImage(contentsOfFile: path) else { return nil }
        return Image(uiImage: image)
        #elseif os(macOS)
        let path = Bundle.main.path(forResource: category, ofType: "jpeg", inDirectory: "mates")
            ?? Bundle.main.path(forResource: category, ofType: "jpeg", inDirectory: "Mates")
            ?? Bundle.main.path(forResource: category, ofType: "jpeg")
        guard let path, let image = NSImage(contentsOfFile: path) else { return nil }
        return Image(nsImage: image)
        #endif
    }

    private var assistantDisplayName: String {
        if isOpenMatesOfficial {
            return AppStrings.openMatesName
        }
        guard let assistantCategory else {
            return AppStrings.openMatesName
        }
        let key = "mates.\(assistantCategory)"
        let localized = AppStrings.localized(key)
        return localized == key ? AppStrings.openMatesName : localized
    }

    private var userBubble: some View {
        VStack(alignment: .trailing, spacing: .spacing3) {
            if !displayContent.isEmpty {
                RichMarkdownView(
                    content: displayContent,
                    isUserMessage: true,
                    allEmbedRecords: allEmbedRecords,
                    onEmbedTap: onEmbedTap,
                    searchHighlightQuery: searchHighlightQuery
                )
                    .foregroundStyle(Color.fontPrimary)
                    .padding(.spacing6)
                    .background(Color.greyBlue)
                    .clipShape(RoundedRectangle(cornerRadius: 13))
                    .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                    .overlay(alignment: .bottomTrailing) {
                        SpeechTailView(side: .trailing, color: Color.greyBlue)
                    }
                    .searchTargetOutline(isSearchTarget)
                    .onLongPressGesture {
                        onShowActions?()
                    }
            }
        }
    }

    private var assistantContent: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if !displayContent.isEmpty {
                VStack(alignment: .leading, spacing: 0) {
                    VStack(alignment: .leading, spacing: .spacing3) {
                        Text(assistantDisplayName)
                            .font(.omP)
                            .fontWeight(.medium)
                            .foregroundStyle(LinearGradient.primary)
                            .padding(.bottom, .spacing1)

                        if !topLevelAppSkillEmbeds.isEmpty {
                            VStack(alignment: .leading, spacing: .spacing3) {
                                Text("\(topLevelAppSkillEmbeds.count) app skill\(topLevelAppSkillEmbeds.count == 1 ? "" : "s") used:")
                                    .font(.omXs)
                                    .fontWeight(.bold)
                                    .foregroundStyle(Color.fontTertiary)

                                ScrollView(.horizontal, showsIndicators: false) {
                                    LazyHStack(spacing: .spacing3) {
                                        ForEach(Array(topLevelAppSkillEmbeds.reversed())) { embed in
                                            EmbedPreviewCard(embed: embed, allEmbedRecords: allEmbedRecords) {
                                                onEmbedTap(embed)
                                            }
                                            .frame(width: 300, height: 200)
                                        }
                                    }
                                }
                                .frame(height: 200)
                            }
                            .padding(.bottom, .spacing2)
                        }

                        RichMarkdownView(
                            content: displayContent,
                            isUserMessage: false,
                            onOpenPublicChat: onOpenPublicChat,
                            embedLookup: EmbedRecord.dictionaryById(embeds, context: "chatView.richMarkdown"),
                            allEmbedRecords: allEmbedRecords,
                            hiddenEmbedIds: hiddenInlineEmbedIds,
                            onEmbedTap: onEmbedTap,
                            onInteractiveQuestionSubmit: viewAllowsInteractiveQuestionSubmit ? onInteractiveQuestionSubmit : nil,
                            searchHighlightQuery: searchHighlightQuery
                        )
                    }
                    .foregroundStyle(Color.grey100)
                    .padding(.spacing6)
                    .background(Color.grey0)
                    .clipShape(RoundedRectangle(cornerRadius: 13))
                    .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                    .overlay(alignment: .topLeading) {
                        SpeechTailView(side: useStackedLayout ? .top : .leading, color: Color.grey0)
                    }
                    .searchTargetOutline(isSearchTarget)
                    .onLongPressGesture {
                        onShowActions?()
                    }

                    if let modelName = message.modelName, !modelName.isEmpty {
                        generatedByContainer(modelName: modelName)
                    }
                }
            }
        }
    }

    private func generatedByContainer(modelName: String) -> some View {
        Text(AppStrings.generatedBy(modelName))
            .font(.omSmall)
            .fontWeight(.medium)
            .foregroundStyle(Color.grey60)
            .padding(.top, .spacing3)
            .padding(.leading, .spacing6)
            .padding(.bottom, .spacing5)
    }

    var body: some View {
        Group {
            if isUser {
                // User message: right-aligned, spacer on left
                HStack(alignment: .top, spacing: ChatMessageLayoutMetric.rowGap) {
                    Spacer(
                        minLength: useStackedLayout
                            ? ChatMessageLayoutMetric.userCompactReserve
                            : ChatMessageLayoutMetric.userDesktopReserve
                    )
                    userBubble
                }
            } else if useStackedLayout {
                // Web ≤500px: assistant avatar stacked above message
                VStack(alignment: .leading, spacing: ChatMessageLayoutMetric.stackedAvatarGap) {
                    assistantAvatar
                    assistantContent
                }
            } else {
                // Desktop: assistant avatar left of message
                HStack(alignment: .top, spacing: ChatMessageLayoutMetric.rowGap) {
                    assistantAvatar
                    assistantContent
                    Spacer(minLength: ChatMessageLayoutMetric.assistantDesktopReserve)
                }
            }
        }
        // Fade-in animation matching web CSS: opacity 0→1, translateY 10→0, 0.4s easeIn
        .opacity(hasAppeared ? 1 : 0)
        .offset(y: hasAppeared ? 0 : 10)
        .onAppear {
            if reduceMotion {
                hasAppeared = true
            } else {
                withAnimation(.easeIn(duration: 0.4)) {
                    hasAppeared = true
                }
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(isUser ? "You" : "AI"): \(displayContent.prefix(200))")
        .accessibilityHint("Long press for options")
        .accessibilityIdentifier(isUser ? "message-user" : "message-assistant")
    }
}

private extension View {
    func searchTargetOutline(_ isActive: Bool) -> some View {
        overlay {
            if isActive {
                RoundedRectangle(cornerRadius: 16)
                    .stroke(Color.buttonPrimary, lineWidth: 2)
                    .padding(-4)
                    .allowsHitTesting(false)
            }
        }
    }
}

// MARK: - Speech bubble tail overlay

private enum BubbleTailSide { case leading, trailing, top }

/// Renders the triangular speech tail as an overlay, positioned to extend
/// beyond the bubble's clipped edge. Uses the SVG curve shape.
private struct SpeechTailView: View {
    let side: BubbleTailSide
    let color: Color

    /// Tail dimensions matching web CSS (12×20px)
    private let tailWidth: CGFloat = 12
    private let tailHeight: CGFloat = 20

    var body: some View {
        Canvas { context, _ in
            // Draw the SVG path: M0 9.926c0 .992 3.191 1.814 7 0V0C5.093 4.893 0 8.933 0 9.926z
            // Scaled from 7×11 viewBox to 12×20pt
            let sx = tailWidth / 7.0
            let sy = tailHeight / 11.0

            var path = Path()
            path.move(to: CGPoint(x: 0, y: 9.926 * sy))
            // First curve: c0 .992 3.191 1.814 7 0
            path.addCurve(
                to: CGPoint(x: 7 * sx, y: 9.926 * sy),
                control1: CGPoint(x: 0, y: (9.926 + 0.992) * sy),
                control2: CGPoint(x: 3.191 * sx, y: (9.926 + 1.814) * sy)
            )
            // V0 — line to top
            path.addLine(to: CGPoint(x: 7 * sx, y: 0))
            // C5.093 4.893 0 8.933 0 9.926
            path.addCurve(
                to: CGPoint(x: 0, y: 9.926 * sy),
                control1: CGPoint(x: 5.093 * sx, y: 4.893 * sy),
                control2: CGPoint(x: 0, y: 8.933 * sy)
            )
            path.closeSubpath()

            context.fill(path, with: .color(color))
        }
        .frame(width: tailWidth, height: tailHeight)
        .rotationEffect(side == .top ? .degrees(90) : .degrees(0))
        .offset(
            x: tailOffsetX,
            y: tailOffsetY
        )
        .allowsHitTesting(false)
    }

    private var tailOffsetX: CGFloat {
        switch side {
        case .leading: -tailWidth
        case .trailing: tailWidth
        case .top: 20
        }
    }

    private var tailOffsetY: CGFloat {
        switch side {
        case .leading: 20
        case .trailing: -10
        case .top: -16
        }
    }
}

// MarkdownText and IsUserMessage environment removed — replaced by
// RichMarkdownView / InlineMarkdownText in RichMarkdownRenderer.swift

// MARK: - Streaming indicator

struct StreamingIndicator: View {
    @State private var dotCount = 0
    let timer = Timer.publish(every: 0.4, on: .main, in: .common).autoconnect()

    var body: some View {
        HStack {
            HStack(spacing: .spacing1) {
                ForEach(0..<3, id: \.self) { index in
                    Circle()
                        .fill(Color.fontTertiary)
                        .frame(width: 6, height: 6)
                        .opacity(index <= dotCount ? 1 : 0.3)
                }
            }
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing4)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: 13))
            .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)

            Spacer()
        }
        .onReceive(timer) { _ in
            dotCount = (dotCount + 1) % 3
        }
        .accessibilityIdentifier("streaming-indicator")
    }
}
