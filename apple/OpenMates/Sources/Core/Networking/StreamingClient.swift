// SSE/WebSocket streaming client for AI response consumption.
// Handles the dual-channel protocol: REST POST to send messages,
// WebSocket events for streaming chunks (ai_message_update).

import Foundation

actor StreamingClient {
    static let shared = StreamingClient()

    private var activeStreams: [String: AsyncStream<StreamEvent>.Continuation] = [:]

    private init() {}

    // MARK: - Stream events

    enum StreamEvent: @unchecked Sendable {
        case taskInitiated(chatId: String, taskId: String, userMessageId: String)
        case typingStarted(chatId: String, messageId: String, metadata: ChatMetadata?)
        case chunk(chatId: String, messageId: String, sequence: Int, content: String, isFinal: Bool)
        case thinkingChunk(chatId: String, messageId: String, content: String)
        case thinkingComplete(chatId: String, messageId: String)
        case messageReady(chatId: String, messageId: String)
        case preprocessingStep(chatId: String, step: String, data: [String: Any]?)
        case error(String)
    }

    struct ChatMetadata {
        let encryptedTitle: String?
        let encryptedIcon: String?
        let encryptedCategory: String?
        let encryptedChatKey: String?
    }

    // MARK: - Create stream for a chat

    func streamForChat(_ chatId: String) -> AsyncStream<StreamEvent> {
        if let existing = activeStreams[chatId] {
            existing.finish()
        }

        return AsyncStream { continuation in
            activeStreams[chatId] = continuation

            continuation.onTermination = { @Sendable _ in
                Task { await self.removeStream(chatId) }
            }
        }
    }

    func removeStream(_ chatId: String) {
        activeStreams.removeValue(forKey: chatId)
    }

    // MARK: - Dispatch events from WebSocket

    func dispatch(_ event: StreamEvent, for chatId: String) {
        activeStreams[chatId]?.yield(event)
    }

    func dispatchToAll(_ event: StreamEvent) {
        for (_, continuation) in activeStreams {
            continuation.yield(event)
        }
    }
}
