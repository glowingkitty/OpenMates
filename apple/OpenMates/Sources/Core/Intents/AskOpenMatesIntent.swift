// "Ask OpenMates" Shortcut — sends a message to a new chat and returns the AI response.
// This is the primary Siri / Shortcuts integration: "Hey Siri, ask OpenMates..."
// Creates a new chat, sends the user's question, waits for the streaming response
// to complete, and returns the full answer as a string result.

import AppIntents
import Foundation

struct AskOpenMatesIntent: AppIntent {
    static let title: LocalizedStringResource = "Ask OpenMates"
    static let description: IntentDescription = "Send a question to OpenMates AI and get a response."
    static let openAppWhenRun = false

    @Parameter(title: "Question", description: "What would you like to ask?")
    var question: String

    @Parameter(title: "App", description: "Which app to use (e.g., ai, web, code, travel)", default: "ai")
    var appId: String

    static var parameterSummary: some ParameterSummary {
        Summary("Ask OpenMates \(\.$question)") {
            \.$appId
        }
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let response = try await performChatRequest()
        return .result(value: response)
    }

    @MainActor
    private func performChatRequest() async throws -> String {
        let authManager = AuthManager()
        await authManager.checkSession()
        guard authManager.state == .authenticated else {
            return "Open OpenMates and sign in before using this shortcut."
        }

        let chatId = UUID().uuidString.lowercased()
        let now = ChatSendPipeline.isoString(from: Date())
        let chatStore = ChatStore()
        let wsManager = WebSocketManager()
        let syncBridge = OfflineSyncBridge(chatStore: chatStore, wsManager: wsManager)
        chatStore.setBridge(syncBridge)

        let chat = Chat(
            id: chatId,
            title: nil,
            lastMessageAt: now,
            createdAt: now,
            updatedAt: now,
            isArchived: false,
            isPinned: false,
            appId: appId.isEmpty ? nil : appId,
            category: appId.isEmpty ? nil : appId,
            icon: nil,
            chatSummary: nil,
            encryptedTitle: nil,
            encryptedCategory: nil,
            encryptedIcon: nil,
            encryptedChatSummary: nil,
            encryptedChatKey: nil,
            messagesV: 0,
            titleV: 0
        )
        chatStore.upsertChat(chat)

        wsManager.connect(sessionId: AuthManager.nativeSessionId, token: authManager.webSocketToken)
        guard await waitUntilConnected(wsManager) else {
            return "OpenMates could not connect. Open the app and try again."
        }
        defer { wsManager.disconnect() }

        let pipeline = ChatSendPipeline()
        let stream = await StreamingClient.shared.streamForChat(chatId)
        let sent = try await pipeline.sendUserMessage(
            content: question,
            in: chat,
            existingMessages: [],
            wsManager: wsManager,
            chatStore: chatStore
        )
        var currentChat = sent.chat
        let pendingUserMessagesById: [String: Message] = [sent.message.id: sent.message]
        var userMessageIdByAssistantId: [String: String] = [:]
        var completedAnswer: String?
        var postProcessingCompleted = false
        var postProcessingTimeout: Task<Void, Never>?
        defer { postProcessingTimeout?.cancel() }

        for await event in stream {
            switch event {
            case .typingStarted(_, let assistantMessageId, let metadata):
                if let userMessageId = metadata?.userMessageId {
                    userMessageIdByAssistantId[assistantMessageId] = userMessageId
                }
                if let metadata,
                   let userMessageId = metadata.userMessageId ?? userMessageIdByAssistantId[assistantMessageId],
                   let userMessage = pendingUserMessagesById[userMessageId] {
                    currentChat = try await pipeline.sendEncryptedUserStoragePackage(
                        chat: currentChat,
                        userMessage: userMessage,
                        assistantTaskId: assistantMessageId,
                        metadata: metadata,
                        wsManager: wsManager,
                        chatStore: chatStore
                    )
                }

            case .chunk(let eventChatId, let messageId, _, let content, let isFinal, let userMessageId, let category, let modelName, let rejectionReason):
                if let userMessageId {
                    userMessageIdByAssistantId[messageId] = userMessageId
                }
                guard eventChatId == chatId, isFinal else { continue }
                let assistantMessage = Message(
                    id: messageId,
                    chatId: chatId,
                    role: rejectionReason == nil ? .assistant : .system,
                    content: content,
                    encryptedContent: nil,
                    createdAt: ChatSendPipeline.isoString(from: Date()),
                    updatedAt: nil,
                    appId: category ?? currentChat.category ?? currentChat.appId,
                    isStreaming: false,
                    embedRefs: nil,
                    modelName: modelName
                )
                let persisted = try await pipeline.persistCompletedAssistantMessage(
                    assistantMessage,
                    userMessageId: userMessageIdByAssistantId[messageId],
                    wsManager: wsManager,
                    chatStore: chatStore
                )
                completedAnswer = persisted.content ?? content
                if postProcessingCompleted { return completedAnswer ?? content }
                // Shortcuts should wait for the durable generated header while
                // still returning the answer if post-processing is unavailable.
                postProcessingTimeout?.cancel()
                postProcessingTimeout = Task {
                    try? await Task.sleep(for: .seconds(15))
                    guard !Task.isCancelled else { return }
                    await stream.finish()
                }

            case .postProcessingCompleted(let eventChatId, _, let followUps, let newSuggestions, let summary, let tags, let updatedTitle, let sourceTitleVersion, let sourceMetadataVersion):
                guard eventChatId == chatId else { continue }
                await pipeline.sendPostProcessingMetadata(
                    chatId: chatId,
                    followUpSuggestions: followUps,
                    newChatSuggestions: newSuggestions,
                    chatSummary: summary,
                    chatTags: tags,
                    updatedTitle: updatedTitle,
                    sourceTitleVersion: sourceTitleVersion,
                    sourceMetadataVersion: sourceMetadataVersion,
                    wsManager: wsManager,
                    chatStore: chatStore
                )
                postProcessingCompleted = true
                if let completedAnswer { return completedAnswer }

            case .error(let message):
                return completedAnswer ?? "OpenMates could not finish the response: \(message)"

            default:
                continue
            }
        }

        return completedAnswer ?? "Response is still processing. Open the app to see the full answer."
    }

    @MainActor
    private func waitUntilConnected(_ wsManager: WebSocketManager) async -> Bool {
        for _ in 0..<50 {
            if wsManager.connectionState == .connected {
                return true
            }
            try? await Task.sleep(for: .milliseconds(100))
        }
        return false
    }
}
