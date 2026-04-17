// Single chat view — message list with input field and streaming responses.
// Supports inline embed previews, markdown rendering, and fullscreen embed sheets.
// Mirrors the web app's chat view with message bubbles and typing indicators.

import SwiftUI

struct ChatView: View {
    let chatId: String
    @StateObject private var viewModel = ChatViewModel()
    @State private var messageText = ""
    @State private var selectedEmbed: EmbedRecord?
    @State private var showEmbedFullscreen = false
    @State private var showReminder = false
    @State private var showPIIPlaceholders = false
    @StateObject private var focusModeManager = FocusModeManager()
    @FocusState private var isInputFocused: Bool

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
        .navigationTitle(viewModel.chat?.displayTitle ?? "Chat")
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
                        Label("Set Reminder", systemImage: SFSymbol.bell)
                    }
                    PIIToggleButton(showPlaceholders: $showPIIPlaceholders)
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
            }
        }
        .sheet(isPresented: $showReminder) {
            ReminderCreationView(chatId: chatId)
        }
        .task {
            await viewModel.loadChat(id: chatId)
        }
        .sheet(isPresented: $showEmbedFullscreen) {
            if let embed = selectedEmbed {
                let messageEmbeds = viewModel.embeds(for: viewModel.messages.first { msg in
                    msg.embedRefs?.contains(where: { $0.id == embed.id }) == true
                } ?? viewModel.messages.last!)
                EmbedFullscreenContainer(
                    embeds: messageEmbeds.isEmpty ? [embed] : messageEmbeds,
                    initialEmbedId: embed.id,
                    allEmbedRecords: viewModel.embedRecords
                )
            }
        }
    }

    // MARK: - Message list

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: .spacing4) {
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
                                    ToastManager.shared.show("Copied", type: .success)
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
            Text("AI is responding...")
                .font(.omXs)
                .foregroundStyle(Color.fontSecondary)
            Spacer()
            Button("Stop") {
                viewModel.stopStreaming()
            }
            .font(.omXs)
            .foregroundStyle(Color.error)
            .accessibilityLabel("Stop AI response")
        }
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing2)
        .background(Color.grey10)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("AI is responding")
        .accessibilityValue("Streaming in progress")
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

                TextField("Message", text: $messageText, axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(.omP)
                    .lineLimit(1...6)
                    .padding(.horizontal, .spacing4)
                    .padding(.vertical, .spacing3)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
                    .focused($isInputFocused)
                    .onSubmit { sendMessage() }
                    .accessibilityLabel("Chat message input")
                    .accessibilityHint("Type a message to send")

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
                    .accessibilityLabel("Send message")
                    .accessibilityHint(messageText.isEmpty ? "Type a message first" : "Sends your message")
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
                // Message text
                if !displayContent.isEmpty {
                    MarkdownText(content: displayContent)
                        .padding(.horizontal, .spacing4)
                        .padding(.vertical, .spacing3)
                        .background(
                            isUser ? AnyShapeStyle(LinearGradient.primary) : AnyShapeStyle(Color.grey10)
                        )
                        .clipShape(RoundedRectangle(cornerRadius: .radius5))
                        .environment(\.isUserMessage, isUser)
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

// MARK: - Markdown text renderer

struct MarkdownText: View {
    let content: String
    @Environment(\.isUserMessage) var isUserMessage

    var body: some View {
        Text(attributedContent)
            .font(.omP)
            .foregroundStyle(isUserMessage ? Color.fontButton : Color.fontPrimary)
            .textSelection(.enabled)
    }

    private var attributedContent: AttributedString {
        (try? AttributedString(markdown: content, options: .init(
            interpretedSyntax: .inlineOnlyPreservingWhitespace
        ))) ?? AttributedString(content)
    }
}

// MARK: - Environment key for message role

private struct IsUserMessageKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    var isUserMessage: Bool {
        get { self[IsUserMessageKey.self] }
        set { self[IsUserMessageKey.self] = newValue }
    }
}

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
