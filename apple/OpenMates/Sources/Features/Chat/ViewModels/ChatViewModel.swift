// Chat view model — manages messages, streaming, and embeds for a single chat.
// Handles the dual-channel protocol: REST POST to send, WebSocket for streaming.
// Subscribes to StreamingClient for real-time AI response chunks.

import Foundation
import SwiftUI

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var chat: Chat?
    @Published var messages: [Message] = []
    @Published var embedRecords: [String: EmbedRecord] = [:]
    @Published var isLoading = false
    @Published var isStreaming = false
    @Published var streamingContent = ""
    @Published var streamingMessageId: String?
    @Published var followUpSuggestions: [String] = []
    @Published var error: String?

    /// Number of messages to show initially and per page when scrolling up.
    private let messagesPageSize = 50
    /// All messages fetched from the server (full history).
    private var allMessages: [Message] = []
    /// Whether there are older messages above the currently visible window.
    @Published var hasOlderMessages = false
    @Published var isLoadingOlder = false

    private let api = APIClient.shared
    private var streamTask: Task<Void, Never>?

    func loadChat(id: String) async {
        isLoading = true
        error = nil

        do {
            chat = try await api.request(.get, path: "/v1/chats/\(id)")
            let messagesResponse: [Message] = try await api.request(.get, path: "/v1/chats/\(id)/messages")
            allMessages = messagesResponse

            // Show only the most recent page initially for fast rendering
            if allMessages.count > messagesPageSize {
                messages = Array(allMessages.suffix(messagesPageSize))
                hasOlderMessages = true
            } else {
                messages = allMessages
                hasOlderMessages = false
            }

            // Load embeds for visible messages
            await loadEmbeds(for: messages.map(\.id))

            // Start listening for streaming events
            subscribeToStream(chatId: id)
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }

    /// Load the next page of older messages above the current window.
    func loadOlderMessages() {
        guard hasOlderMessages, !isLoadingOlder else { return }
        isLoadingOlder = true

        let currentCount = messages.count
        let totalCount = allMessages.count
        let remaining = totalCount - currentCount

        if remaining > 0 {
            let nextPageSize = min(messagesPageSize, remaining)
            let startIndex = remaining - nextPageSize
            let olderBatch = Array(allMessages[startIndex..<remaining])
            messages.insert(contentsOf: olderBatch, at: 0)
            hasOlderMessages = startIndex > 0

            // Load embeds for newly visible messages
            Task {
                await loadEmbeds(for: olderBatch.map(\.id))
            }
        } else {
            hasOlderMessages = false
        }

        isLoadingOlder = false
    }

    // MARK: - Send message

    func sendMessage(_ content: String) async {
        guard let chatId = chat?.id else { return }

        let userMessageId = UUID().uuidString
        let userMessage = Message(
            id: userMessageId, chatId: chatId, role: .user,
            content: content, encryptedContent: nil, contentIv: nil,
            createdAt: ISO8601DateFormatter().string(from: Date()),
            updatedAt: nil, appId: nil, isStreaming: nil, embedRefs: nil
        )
        allMessages.append(userMessage)
        messages.append(userMessage)

        isStreaming = true
        streamingContent = ""

        do {
            let body: [String: Any] = [
                "chat_id": chatId,
                "message": [
                    "message_id": userMessageId,
                    "role": "user",
                    "content": content,
                    "created_at": Int(Date().timeIntervalSince1970),
                    "chat_has_title": (chat?.title != nil)
                ] as [String: Any]
            ]

            let _: Data = try await api.request(.post, path: "/v1/chat/message", body: body)
        } catch {
            self.error = error.localizedDescription
            isStreaming = false
        }
    }

    // MARK: - Stop streaming

    func stopStreaming() {
        streamTask?.cancel()
        isStreaming = false
        streamingContent = ""
        streamingMessageId = nil
    }

    // MARK: - Streaming subscription

    private func subscribeToStream(chatId: String) {
        streamTask?.cancel()
        streamTask = Task {
            let stream = await StreamingClient.shared.streamForChat(chatId)
            for await event in stream {
                guard !Task.isCancelled else { break }
                handleStreamEvent(event)
            }
        }
    }

    private func handleStreamEvent(_ event: StreamingClient.StreamEvent) {
        switch event {
        case .taskInitiated(_, _, _):
            isStreaming = true
            streamingContent = ""

        case .typingStarted(_, let messageId, _):
            streamingMessageId = messageId

        case .chunk(_, let messageId, _, let content, let isFinal):
            streamingMessageId = messageId
            streamingContent = content

            if isFinal {
                let assistantMessage = Message(
                    id: messageId, chatId: chat?.id ?? "", role: .assistant,
                    content: content, encryptedContent: nil, contentIv: nil,
                    createdAt: ISO8601DateFormatter().string(from: Date()),
                    updatedAt: nil, appId: chat?.appId, isStreaming: false, embedRefs: nil
                )
                allMessages.append(assistantMessage)
                messages.append(assistantMessage)
                isStreaming = false
                streamingContent = ""
                streamingMessageId = nil
            }

        case .thinkingChunk(_, _, _):
            break

        case .thinkingComplete(_, _):
            break

        case .messageReady(_, _):
            isStreaming = false

        case .preprocessingStep(_, _, _):
            break

        case .error(let msg):
            error = msg
            isStreaming = false
        }
    }

    // MARK: - Message actions

    func deleteMessage(_ messageId: String) async {
        guard let chatId = chat?.id else { return }
        do {
            let _: Data = try await api.request(
                .delete, path: "/v1/chats/\(chatId)/messages/\(messageId)"
            )
            messages.removeAll { $0.id == messageId }
        } catch {
            self.error = error.localizedDescription
        }
    }

    func forkFromMessage(_ messageId: String) async {
        guard let chatId = chat?.id else { return }
        do {
            let response: [String: AnyCodable] = try await api.request(
                .post, path: "/v1/chats/\(chatId)/fork",
                body: ["from_message_id": messageId]
            )
            if let newChatId = response["chat_id"]?.value as? String {
                ToastManager.shared.show("Conversation forked", type: .success)
                _ = newChatId
            }
        } catch {
            self.error = error.localizedDescription
        }
    }

    // MARK: - Embed loading

    func loadEmbeds(for messageIds: [String]) async {
        guard let chatId = chat?.id else { return }
        do {
            let response: [EmbedRecord] = try await api.request(
                .get, path: "/v1/chats/\(chatId)/embeds"
            )
            for embed in response {
                embedRecords[embed.id] = embed
            }
        } catch {
            print("[Chat] Failed to load embeds: \(error)")
        }
    }

    func embeds(for message: Message) -> [EmbedRecord] {
        message.embedRefs?.compactMap { ref in
            embedRecords[ref.id]
        } ?? []
    }

    func childEmbeds(for embed: EmbedRecord) -> [EmbedRecord] {
        embed.childEmbedIds.compactMap { embedRecords[$0] }
    }

    func isStreamingMessage(_ messageId: String) -> Bool {
        streamingMessageId == messageId && isStreaming
    }

    // MARK: - Attachment upload

    func uploadAttachment(data: Data, filename: String) async {
        guard let chatId = chat?.id else { return }

        let boundary = UUID().uuidString
        var body = Data()

        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: application/octet-stream\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"chat_id\"\r\n\r\n".data(using: .utf8)!)
        body.append(chatId.data(using: .utf8)!)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        do {
            let uploadURL = await APIClient.shared.baseURL
                .deletingLastPathComponent()
                .appendingPathComponent("upload/v1/files")
            var request = URLRequest(url: uploadURL)
            request.httpMethod = "POST"
            request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
            request.httpBody = body

            let (_, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse,
                  (200...299).contains(httpResponse.statusCode) else {
                print("[Chat] Upload failed")
                return
            }
        } catch {
            print("[Chat] Upload error: \(error)")
        }
    }

    func uploadFile(url: URL) async {
        guard let data = try? Data(contentsOf: url) else { return }
        await uploadAttachment(data: data, filename: url.lastPathComponent)
    }
}
