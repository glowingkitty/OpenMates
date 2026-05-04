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

// ChatBannerView and ChatBannerState are defined in ChatBannerView.swift

struct ChatView: View {
    let chatId: String
    /// Optional gradient banner state. Provide `.loaded` for demo/example chats;
    /// omit (nil) for regular user chats where no banner should appear.
    var bannerState: ChatBannerState? = nil
    var bannerCreatedAt: Date? = nil
    /// Navigation callbacks for prev/next chat arrows on the banner.
    var onPreviousChat: (() -> Void)? = nil
    var onNextChat: (() -> Void)? = nil

    @StateObject private var viewModel = ChatViewModel()
    @StateObject private var handoffManager = HandoffManager()
    @State private var messageText = ""
    @State private var selectedEmbed: EmbedRecord?
    @State private var showEmbedFullscreen = false
    @State private var showReminder = false
    @State private var showPIIPlaceholders = false
    @State private var showAttachmentMenu = false
    @State private var actionMessage: Message?
    @StateObject private var focusModeManager = FocusModeManager()
    @FocusState private var isInputFocused: Bool
    @Environment(\.accessibilityReduceMotion) var reduceMotion

    /// True for demo/intro/legal chats that show "New chat" CTA instead of input field
    private var isDemoOrLegalChat: Bool {
        chatId.hasPrefix("demo-") || chatId.hasPrefix("legal-") || chatId.hasPrefix("announcements-")
    }

    var body: some View {
        ZStack {
            VStack(spacing: 0) {
                if bannerState == nil {
                    chatTopBar
                }

                messageList

                // Hide for demo/example chats — they have static content, no streaming state
                if !viewModel.followUpSuggestions.isEmpty && !viewModel.isStreaming && bannerState == nil {
                    FollowUpSuggestions(suggestions: viewModel.followUpSuggestions) { suggestion in
                        messageText = suggestion
                    }
                }

                FocusModePill(focusModeManager: focusModeManager)

                if viewModel.isStreaming {
                    streamingBanner
                }

                // Web: intro/legal chats show a full-width "New chat" CTA instead of the input field
                if isDemoOrLegalChat {
                    newChatCTA
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
                customOverlay(title: "", isPresented: $showEmbedFullscreen, showHeader: false) {
                    embedFullscreenSheet(for: embed)
                }
            }

            if let actionMessage {
                messageActionsOverlay(for: actionMessage)
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
        .task(id: chatId) {
            await viewModel.loadChat(id: chatId)
            // Advertise this chat for Handoff to other Apple devices
            handoffManager.advertiseChatViewing(
                chatId: chatId,
                chatTitle: viewModel.chat?.displayTitle
            )
            // Clear notification badge when viewing a chat
            PushNotificationManager.shared.clearBadge()
        }
        .onDisappear {
            handoffManager.stopAdvertising()
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
    }

    // MARK: - Embed fullscreen helper

    private var chatTopBar: some View {
        HStack(spacing: .spacing3) {
            ChatHeaderView(chat: viewModel.chat, isLoading: viewModel.isLoading)

            Spacer()

            if let appId = viewModel.chat?.appId {
                Text(appId)
                    .font(.omTiny)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontSecondary)
                    .padding(.horizontal, .spacing3)
                    .padding(.vertical, .spacing2)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
            }

            OMIconButton(icon: "reminder", label: AppStrings.setReminder, size: 34, iconSize: 17) {
                showReminder = true
            }

            OMIconButton(
                icon: showPIIPlaceholders ? "anonym" : "visible",
                label: AppStrings.hidePersonalData,
                size: 34,
                iconSize: 17,
                isProminent: showPIIPlaceholders
            ) {
                showPIIPlaceholders.toggle()
            }
        }
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing3)
        .background(Color.grey20)
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(Color.grey20)
                .frame(height: 1)
        }
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
        let matchingMessage = viewModel.messages.first { msg in
            msg.embedRefs?.contains(where: { $0.id == embed.id }) == true
        }
        let fallbackMessage = matchingMessage ?? viewModel.messages.last
        let messageEmbeds: [EmbedRecord] = if let msg = fallbackMessage {
            viewModel.embeds(for: msg)
        } else {
            []
        }
        EmbedFullscreenContainer(
            embeds: messageEmbeds.isEmpty ? [embed] : messageEmbeds,
            initialEmbedId: embed.id,
            allEmbedRecords: viewModel.embedRecords
        )
    }

    // MARK: - Message list

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: .spacing4) {
                    // Gradient banner — shown for demo/example chats (ChatHeader.svelte equivalent)
                    if let banner = bannerState {
                        ChatBannerView(
                            state: banner,
                            createdAt: bannerCreatedAt,
                            isExampleChat: chatId.hasPrefix("example-"),
                            isIntroChat: chatId == "demo-for-everyone",
                            teaserVideoURL: chatId == "demo-for-everyone"
                                ? Bundle.main.url(forResource: "intro-teaser", withExtension: "mp4")
                                : nil,
                            fullVideoURL: chatId == "demo-for-everyone"
                                ? URL(string: "https://vod.api.video/vod/vi43o2FOchAMACeh5blHumCa/mp4/source.mp4")
                                : nil,
                            onPrevious: onPreviousChat,
                            onNext: onNextChat
                        )
                            .padding(.horizontal, 0)
                            .padding(.top, 0)
                            .id("banner")
                    }

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
                            appId: viewModel.chat?.appId,
                            embeds: viewModel.embeds(for: message),
                            streamingContent: viewModel.isStreamingMessage(message.id) ? viewModel.streamingContent : nil,
                            onEmbedTap: { embed in
                                selectedEmbed = embed
                                showEmbedFullscreen = true
                            }
                        )
                        .id(message.id)
                        .onLongPressGesture {
                            actionMessage = message
                        }
                    }

                    if viewModel.isStreaming && viewModel.streamingContent.isEmpty {
                        StreamingIndicator()
                            .id("streaming")
                    }
                }
                .padding(.horizontal, .spacing4)
                .padding(.vertical, .spacing4)
                // Cap message area width on iPad/Mac, centered
                .frame(maxWidth: 1000)
                .frame(maxWidth: .infinity)
            }
            .onChange(of: viewModel.messages.count) { _, _ in
                // Demo/example chats (with banner) start at the top; real chats scroll to bottom
                if bannerState != nil {
                    proxy.scrollTo("banner", anchor: .top)
                } else {
                    withAnimation {
                        proxy.scrollTo(viewModel.messages.last?.id, anchor: .bottom)
                    }
                }
            }
            .onChange(of: viewModel.streamingContent) { _, _ in
                if let lastId = viewModel.messages.last?.id {
                    proxy.scrollTo(lastId, anchor: .bottom)
                }
            }
        }
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
                    .foregroundStyle(Color.fontSecondary)
                    .padding(.horizontal, .spacing4)
                    .padding(.top, .spacing3)

                messageActionRow(icon: "copy", title: AppStrings.copy) {
                    copyMessage(message)
                    actionMessage = nil
                }

                messageActionRow(icon: "copy", title: AppStrings.forkConversation) {
                    Task { await viewModel.forkFromMessage(message.id) }
                    actionMessage = nil
                }

                messageActionRow(icon: "delete", title: AppStrings.delete, isDestructive: true) {
                    Task { await viewModel.deleteMessage(message.id) }
                    actionMessage = nil
                }
            }
            .padding(.vertical, .spacing2)
            .frame(width: 260)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius7))
            .overlay(
                RoundedRectangle(cornerRadius: .radius7)
                    .stroke(Color.grey20, lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.18), radius: 18, x: 0, y: 10)
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
            .accessibilityLabel(AppStrings.stopResponse)
        }
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing2)
        .background(Color.grey0)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(AppStrings.aiResponding)
    }

    // MARK: - New chat CTA (replaces input for demo/intro/legal chats)

    private var newChatCTA: some View {
        Button {
            NotificationCenter.default.post(name: .newChat, object: nil)
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
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing3)
        .background(Color.grey20)
    }

    // MARK: - Input bar

    private var inputBar: some View {
        VStack(spacing: 0) {
            ZStack(alignment: .bottom) {
                TextField(AppStrings.typeMessage, text: $messageText, axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(.omP)
                    .lineLimit(1...6)
                    .tint(Color.buttonPrimary)
                    .focused($isInputFocused)
                    .onSubmit { sendMessage() }
                    .accessibilityLabel(AppStrings.chatMessageInput)
                    .accessibilityHint(AppStrings.typeMessage)
                    .padding(.horizontal, .spacing6)
                    .padding(.top, .spacing6)
                    .padding(.bottom, .spacing32)
                    .frame(maxWidth: .infinity, minHeight: 100, alignment: .topLeading)

                HStack(spacing: .spacing5) {
                    AttachmentPicker(
                        isPresented: $showAttachmentMenu,
                        onImageSelected: { data, filename in
                            Task { await viewModel.uploadAttachment(data: data, filename: filename) }
                        },
                        onFileSelected: { url in
                            Task { await viewModel.uploadFile(url: url) }
                        }
                    )
                    .accessibilityLabel(AppStrings.attachFiles)

                    inputActionButton(icon: "maps", label: AppStrings.shareLocation, gradient: .appMaps) {
                        ToastManager.shared.show(AppStrings.shareLocation, type: .info)
                    }

                    inputActionButton(icon: "modify", label: AppStrings.sketchAction, gradient: .appDesign) {
                        ToastManager.shared.show(AppStrings.sketchAction, type: .info)
                    }

                    Spacer()

                    #if os(iOS)
                    inputActionButton(icon: "take_photo", label: AppStrings.takePhoto, gradient: .appPhotos) {
                        ToastManager.shared.show(AppStrings.takePhoto, type: .info)
                    }
                    #endif

                    if messageText.isEmpty && !viewModel.isStreaming {
                        VoiceRecordingButton { url in
                            Task {
                                if let data = try? Data(contentsOf: url) {
                                    await viewModel.uploadAttachment(data: data, filename: url.lastPathComponent)
                                }
                            }
                        }
                    } else {
                        Button(action: sendMessage) {
                            Text(AppStrings.sendAction)
                                .font(.omP)
                                .fontWeight(.medium)
                                .foregroundStyle(Color.fontButton)
                                .padding(.horizontal, .spacing8)
                                .padding(.vertical, .spacing4)
                                .frame(height: 40)
                                .background(Color.buttonPrimary)
                                .clipShape(RoundedRectangle(cornerRadius: .radius8))
                        }
                        .buttonStyle(.plain)
                        .disabled(messageText.isEmpty || viewModel.isStreaming)
                        .opacity(messageText.isEmpty ? 0.6 : 1.0)
                        .accessibilityLabel(AppStrings.sendMessage)
                        .accessibilityHint(AppStrings.typeMessage)
                        #if os(macOS)
                        .keyboardShortcut(.return, modifiers: .command)
                        #endif
                    }
                }
                .padding(.horizontal, .spacing5)
                .padding(.bottom, .spacing4)
            }
            .background(Color.greyBlue)
            .clipShape(RoundedRectangle(cornerRadius: 24))
            .shadow(color: .black.opacity(0.08), radius: 12, x: 0, y: 4)
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing3)
        }
        .background(Color.grey0)
    }

    private func inputActionButton(icon: String, label: String, gradient: LinearGradient = .primary, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Icon(icon, size: 22)
                .foregroundStyle(gradient)
                .frame(width: 36, height: 36)
                .background(Color.grey0.opacity(0.72))
                .clipShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }

    private func sendMessage() {
        let text = messageText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        messageText = ""

        Task {
            await viewModel.sendMessage(text)
        }
    }
}

// MARK: - Message bubble with embed support

struct MessageBubble: View {
    let message: Message
    let chatId: String
    let appId: String?
    let embeds: [EmbedRecord]
    let streamingContent: String?
    let onEmbedTap: (EmbedRecord) -> Void
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var hasAppeared = false

    var isUser: Bool { message.role == .user }
    /// Web: ≤500px uses stacked layout (avatar above message). Map to compact size class.
    private var useStackedLayout: Bool { sizeClass == .compact }

    var displayContent: String {
        if let streaming = streamingContent { return streaming }
        return message.content ?? ""
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
        return (appId == nil || appId == "ai") ? .primary : AppIconView.gradient(forAppId: appId!)
    }

    // Web: .mate-profile = 60px; .mate-profile-small-mobile (≤500px container) = 25px
    private var avatarSize: CGFloat { useStackedLayout ? 25 : 60 }
    private var avatarIconSize: CGFloat { useStackedLayout ? 12 : 30 }
    // Web: AI badge — normal: 24/16px, small-mobile: 12/8px
    private var badgeSize: CGFloat { useStackedLayout ? 12 : 24 }
    private var badgeIconSize: CGFloat { useStackedLayout ? 8 : 16 }
    private var badgeAiIconSize: CGFloat { useStackedLayout ? 4 : 8 }

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
                Circle()
                    .fill(avatarGradient)
                    .frame(width: avatarSize, height: avatarSize)
                    .overlay {
                        Icon(AppIconView.iconName(forAppId: appId ?? "ai"), size: avatarIconSize)
                            .foregroundStyle(.white)
                    }
                    .overlay(alignment: .bottomTrailing) {
                        Circle()
                            .fill(Color.grey0)
                            .frame(width: badgeSize, height: badgeSize)
                            .overlay {
                                Circle()
                                    .fill(LinearGradient.primary)
                                    .frame(width: badgeIconSize, height: badgeIconSize)
                                    .overlay {
                                        Icon("ai", size: badgeAiIconSize)
                                            .foregroundStyle(.white)
                                    }
                            }
                            .shadow(color: .black.opacity(0.10), radius: 2, x: 0, y: 1)
                    }
            }
        }
        .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
    }

    private var userBubble: some View {
        VStack(alignment: .trailing, spacing: .spacing3) {
            if !displayContent.isEmpty {
                InlineMarkdownText(content: displayContent, isUserMessage: true)
                    .foregroundStyle(Color.grey100)
                    .padding(.spacing6)
                    .background(Color.greyBlue)
                    .clipShape(RoundedRectangle(cornerRadius: 13))
                    .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                    .overlay(alignment: .bottomTrailing) {
                        SpeechTailView(side: .trailing, color: Color.greyBlue)
                    }
            }
        }
    }

    private var assistantContent: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if !displayContent.isEmpty {
                VStack(alignment: .leading, spacing: .spacing3) {
                    if isOpenMatesOfficial {
                        Text(AppStrings.openMatesName)
                            .font(.omH3)
                            .fontWeight(.bold)
                            .foregroundStyle(LinearGradient.primary)
                    }

                    RichMarkdownView(content: displayContent, isUserMessage: false)
                }
                .foregroundStyle(Color.grey100)
                .padding(.spacing6)
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: 13))
                .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                .overlay(alignment: .topLeading) {
                    SpeechTailView(side: .leading, color: Color.grey0)
                }
            }
            if !embeds.isEmpty {
                let groups = EmbedGrouper.group(embeds)
                ForEach(groups) { group in
                    GroupedEmbedView(group: group) { embed in
                        onEmbedTap(embed)
                    }
                }
            }
        }
    }

    var body: some View {
        Group {
            if isUser {
                // User message: right-aligned, spacer on left
                HStack(alignment: .top, spacing: .spacing3) {
                    Spacer(minLength: useStackedLayout ? 20 : 100)
                    userBubble
                }
            } else if useStackedLayout {
                // Web ≤500px: assistant avatar stacked above message
                VStack(alignment: .leading, spacing: .spacing2) {
                    assistantAvatar
                    assistantContent
                }
            } else {
                // Desktop: assistant avatar left of message
                HStack(alignment: .top, spacing: .spacing3) {
                    assistantAvatar
                    assistantContent
                    Spacer(minLength: 70)
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
    }
}

// MARK: - Speech bubble tail overlay

private enum BubbleTailSide { case leading, trailing }

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
        .offset(
            x: side == .trailing ? tailWidth : -tailWidth,
            y: side == .trailing ? -10 : 20
        )
        .allowsHitTesting(false)
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
    }
}
