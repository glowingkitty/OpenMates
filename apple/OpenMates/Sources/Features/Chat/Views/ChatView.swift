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
            Divider()
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

                TextField(AppStrings.typeMessage, text: $messageText, axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(.omP)
                    .lineLimit(1...6)
                    .padding(.horizontal, .spacing4)
                    .padding(.vertical, .spacing3)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
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
                    Button(action: sendMessage) {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.system(size: 32))
                            .foregroundStyle(
                                messageText.isEmpty ? Color.fontTertiary : Color.buttonPrimary
                            )
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
    let embeds: [EmbedRecord]
    let streamingContent: String?
    let onEmbedTap: (EmbedRecord) -> Void

    var isUser: Bool { message.role == .user }

    var displayContent: String {
        if let streaming = streamingContent { return streaming }
        return message.content ?? ""
    }

    var body: some View {
        HStack(alignment: .top) {
            if isUser { Spacer(minLength: 40) }

            VStack(alignment: isUser ? .trailing : .leading, spacing: .spacing3) {
                // Message text — user messages use inline-only markdown,
                // assistant messages use full block-level rendering (code blocks, tables, etc.)
                if !displayContent.isEmpty {
                    if isUser {
                        InlineMarkdownText(content: displayContent, isUserMessage: true)
                            .padding(.horizontal, .spacing4)
                            .padding(.vertical, .spacing3)
                            .background(AnyShapeStyle(LinearGradient.primary))
                            .clipShape(RoundedRectangle(cornerRadius: .radius5))
                    } else {
                        RichMarkdownView(content: displayContent, isUserMessage: false)
                            .padding(.horizontal, .spacing4)
                            .padding(.vertical, .spacing3)
                            .background(AnyShapeStyle(Color.grey10))
                            .clipShape(RoundedRectangle(cornerRadius: .radius5))
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

            if !isUser { Spacer(minLength: 40) }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(isUser ? "You" : "AI"): \(displayContent.prefix(200))")
        .accessibilityHint("Long press for options")
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
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius5))

            Spacer()
        }
        .onReceive(timer) { _ in
            dotCount = (dotCount + 1) % 3
        }
    }
}
