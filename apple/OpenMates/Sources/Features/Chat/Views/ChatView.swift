// Single chat view — message list with input field and streaming responses.
// Supports block-level markdown rendering (code blocks, tables, blockquotes),
// inline embed previews, and fullscreen embed sheets. Advertises the current
// chat for Handoff so users can continue on another Apple device.

import SwiftUI

struct ChatView: View {
    let chatId: String
    @StateObject private var viewModel = ChatViewModel()
    @StateObject private var handoffManager = HandoffManager()
    @State private var messageText = ""
    @State private var selectedEmbed: EmbedRecord?
    @State private var showEmbedFullscreen = false
    @State private var showReminder = false
    @State private var showPIIPlaceholders = false
    @StateObject private var focusModeManager = FocusModeManager()
    @FocusState private var isInputFocused: Bool
    @Environment(\.accessibilityReduceMotion) var reduceMotion

    var body: some View {
        VStack(spacing: 0) {
            messageList

            if !viewModel.followUpSuggestions.isEmpty && !viewModel.isStreaming {
                FollowUpSuggestions(suggestions: viewModel.followUpSuggestions) { suggestion in
                    messageText = suggestion
                }
            }

            FocusModePill(focusModeManager: focusModeManager)

            if viewModel.isStreaming {
                streamingBanner
            }
            inputBar
        }
        .background(Color.grey0)
        .navigationTitle(viewModel.chat?.displayTitle ?? AppStrings.chats)
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Menu {
                    if let appId = viewModel.chat?.appId {
                        Label("App: \(appId)", systemImage: "app")
                    }
                    Button { showReminder = true } label: {
                        Label(AppStrings.setReminder, systemImage: SFSymbol.bell)
                    }
                    PIIToggleButton(showPlaceholders: $showPIIPlaceholders)
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
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
        .sheet(isPresented: $showReminder) {
            ReminderCreationView(chatId: chatId)
        }
        .task {
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
        .sheet(isPresented: $showEmbedFullscreen) {
            if let embed = selectedEmbed {
                embedFullscreenSheet(for: embed)
            }
        }
    }

    // MARK: - Embed fullscreen helper

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
                                    Image(systemName: "arrow.up")
                                        .font(.caption)
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
                            appId: viewModel.chat?.appId,
                            embeds: viewModel.embeds(for: message),
                            streamingContent: viewModel.isStreamingMessage(message.id) ? viewModel.streamingContent : nil,
                            onEmbedTap: { embed in
                                selectedEmbed = embed
                                showEmbedFullscreen = true
                            }
                        )
                        .id(message.id)
                        .contextMenu {
                            MessageContextMenu(
                                message: message,
                                onCopy: {
                                    #if os(iOS)
                                    UIPasteboard.general.string = message.content ?? ""
                                    #elseif os(macOS)
                                    NSPasteboard.general.clearContents()
                                    NSPasteboard.general.setString(message.content ?? "", forType: .string)
                                    #endif
                                    ToastManager.shared.show(AppStrings.copied, type: .success)
                                },
                                onEdit: {
                                    // Message editing would require inline editor state
                                },
                                onDelete: {
                                    Task { await viewModel.deleteMessage(message.id) }
                                },
                                onFork: {
                                    Task { await viewModel.forkFromMessage(message.id) }
                                }
                            )
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
                withAnimation {
                    proxy.scrollTo(viewModel.messages.last?.id, anchor: .bottom)
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
        .background(Color.grey10)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(AppStrings.aiResponding)
    }

    // MARK: - Input bar

    private var inputBar: some View {
        VStack(spacing: 0) {
            HStack(alignment: .bottom, spacing: .spacing3) {
                AttachmentPicker(
                    isPresented: .constant(false),
                    onImageSelected: { data, filename in
                        Task { await viewModel.uploadAttachment(data: data, filename: filename) }
                    },
                    onFileSelected: { url in
                        Task { await viewModel.uploadFile(url: url) }
                    }
                )

                // Pill-shaped input field matching web app's fields.css:
                // border-radius: 24px, border: 2px, orange focus ring
                TextField(AppStrings.typeMessage, text: $messageText, axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(.omP)
                    .lineLimit(1...6)
                    .padding(.horizontal, .spacing8)
                    .padding(.vertical, .spacing6)
                    .background(Color.grey0)
                    .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                    .overlay(
                        RoundedRectangle(cornerRadius: .radiusFull)
                            .stroke(
                                isInputFocused ? Color.buttonPrimary : Color.grey0,
                                lineWidth: 2
                            )
                    )
                    .shadow(
                        color: isInputFocused
                            ? Color.buttonPrimary.opacity(0.22)
                            : .clear,
                        radius: 3, x: 0, y: 0
                    )
                    .shadow(
                        color: isInputFocused
                            ? .black.opacity(0.08)
                            : .black.opacity(0.05),
                        radius: isInputFocused ? 12 : 2,
                        x: 0, y: 4
                    )
                    .tint(Color.buttonPrimary)
                    .focused($isInputFocused)
                    .onSubmit { sendMessage() }
                    .accessibilityLabel(AppStrings.chatMessageInput)
                    .accessibilityHint(AppStrings.typeMessage)

                if messageText.isEmpty && !viewModel.isStreaming {
                    VoiceRecordingButton { url in
                        Task {
                            if let data = try? Data(contentsOf: url) {
                                await viewModel.uploadAttachment(data: data, filename: url.lastPathComponent)
                            }
                        }
                    }
                } else {
                    // Circular send button — orange fill when text present,
                    // grey when empty (matching web app)
                    Button(action: sendMessage) {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(
                                messageText.isEmpty ? Color.fontTertiary : Color.fontButton
                            )
                            .frame(width: 32, height: 32)
                            .background(
                                messageText.isEmpty ? Color.grey20 : Color.buttonPrimary
                            )
                            .clipShape(Circle())
                    }
                    .disabled(messageText.isEmpty || viewModel.isStreaming)
                    .accessibilityLabel(AppStrings.sendMessage)
                    .accessibilityHint(AppStrings.typeMessage)
                    #if os(macOS)
                    .keyboardShortcut(.return, modifiers: .command)
                    #endif
                }
            }
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing3)
        }
        .background(Color.grey0)
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
    let appId: String?
    let embeds: [EmbedRecord]
    let streamingContent: String?
    let onEmbedTap: (EmbedRecord) -> Void
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    @State private var hasAppeared = false

    var isUser: Bool { message.role == .user }

    var displayContent: String {
        if let streaming = streamingContent { return streaming }
        return message.content ?? ""
    }

    // MARK: - Assistant avatar with AI badge

    private var assistantAvatar: some View {
        AppIconView(appId: appId ?? "ai", size: 60)
            .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
            .overlay(alignment: .bottomTrailing) {
                // White 24px circle housing a 16px AI gradient icon
                Circle()
                    .fill(Color.white)
                    .frame(width: 24, height: 24)
                    .overlay {
                        Circle()
                            .fill(LinearGradient.appAi)
                            .frame(width: 16, height: 16)
                            .overlay {
                                Image(systemName: "sparkles")
                                    .font(.system(size: 7, weight: .bold))
                                    .foregroundStyle(.white)
                            }
                    }
                    .shadow(color: .black.opacity(0.15), radius: 2, x: 0, y: 1)
            }
    }

    var body: some View {
        HStack(alignment: .top, spacing: .spacing3) {
            if isUser {
                Spacer(minLength: 100)
            } else {
                assistantAvatar
            }

            VStack(alignment: isUser ? .trailing : .leading, spacing: .spacing3) {
                // Message text — user messages use inline-only markdown,
                // assistant messages use full block-level rendering (code blocks, tables, etc.)
                if !displayContent.isEmpty {
                    if isUser {
                        // User bubble: grey-blue bg, speech tail on right, drop shadow
                        InlineMarkdownText(content: displayContent, isUserMessage: true)
                            .foregroundStyle(Color.grey100)
                            .padding(.spacing6)
                            .background(Color.greyBlue)
                            .clipShape(RoundedRectangle(cornerRadius: 13))
                            .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                            .overlay(alignment: .bottomTrailing) {
                                SpeechTailView(side: .trailing, color: Color.greyBlue)
                            }
                    } else {
                        // Assistant bubble: white/grey0 bg, speech tail on left, drop shadow
                        RichMarkdownView(content: displayContent, isUserMessage: false)
                            .foregroundStyle(Color.fontPrimary)
                            .padding(.spacing6)
                            .background(Color.grey0)
                            .clipShape(RoundedRectangle(cornerRadius: 13))
                            .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
                            .overlay(alignment: .topLeading) {
                                SpeechTailView(side: .leading, color: Color.grey0)
                            }
                    }
                }

                // Inline embed previews (grouped by type)
                if !embeds.isEmpty {
                    let groups = EmbedGrouper.group(embeds)
                    ForEach(groups) { group in
                        GroupedEmbedView(group: group) { embed in
                            onEmbedTap(embed)
                        }
                    }
                }
            }

            if !isUser { Spacer(minLength: 70) }
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
