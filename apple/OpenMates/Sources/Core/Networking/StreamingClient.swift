// SSE/WebSocket streaming client for AI response consumption.
// Handles the dual-channel chat protocol: plaintext WebSocket send for AI,
// encrypted WebSocket persistence events for cross-device sync.

import Foundation

actor StreamingClient {
    static let shared = StreamingClient()

    private var activeStreams: [String: AsyncStream<StreamEvent>.Continuation] = [:]
    private var bufferedEvents: [String: [StreamEvent]] = [:]
    private let maxBufferedEventsPerChat = 80

    private init() {}

    // MARK: - Stream events

    enum StreamEvent: @unchecked Sendable {
        case taskInitiated(chatId: String, taskId: String, userMessageId: String)
        case typingStarted(chatId: String, messageId: String, metadata: ChatMetadata?)
        case chunk(chatId: String, messageId: String, sequence: Int, content: String, isFinal: Bool, userMessageId: String?, category: String?, modelName: String?, rejectionReason: String?)
        case thinkingChunk(chatId: String, messageId: String, content: String)
        case thinkingComplete(chatId: String, messageId: String)
        case messageReady(chatId: String, messageId: String)
        case preprocessingStep(chatId: String, step: String, data: [String: Any]?)
        case postProcessingCompleted(chatId: String, taskId: String, followUpSuggestions: [String], newChatSuggestions: [String], chatSummary: String?, chatTags: [String], updatedTitle: String?)
        case error(String)
    }

    struct ChatMetadata {
        let title: String?
        let iconNames: [String]
        let category: String?
        let modelName: String?
        let providerName: String?
        let serverRegion: String?
        let userMessageId: String?
        let encryptedChatKey: String?
    }

    // MARK: - Create stream for a chat

    func streamForChat(_ chatId: String) -> AsyncStream<StreamEvent> {
        if let existing = activeStreams[chatId] {
            existing.finish()
        }

        return AsyncStream { continuation in
            activeStreams[chatId] = continuation
            if let buffered = bufferedEvents.removeValue(forKey: chatId) {
                for event in buffered {
                    continuation.yield(event)
                }
            }

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
        if let continuation = activeStreams[chatId] {
            continuation.yield(event)
            return
        }
        var events = bufferedEvents[chatId] ?? []
        events.append(event)
        if events.count > maxBufferedEventsPerChat {
            events.removeFirst(events.count - maxBufferedEventsPerChat)
        }
        bufferedEvents[chatId] = events
    }

    func dispatchToAll(_ event: StreamEvent) {
        for (_, continuation) in activeStreams {
            continuation.yield(event)
        }
    }
}
