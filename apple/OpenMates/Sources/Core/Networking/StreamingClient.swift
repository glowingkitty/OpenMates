// Ordered, same-process fanout for the existing WebSocket streaming protocol.
// Each subscriber has independent cancellation. Replay retains one current-turn
// projection, never an array of cumulative response copies. It is not history.
import Foundation

struct StreamingSessionGeneration: Hashable, Sendable {
    fileprivate let id: UUID
}

fileprivate final class StreamingSessionGenerationGate: @unchecked Sendable {
    private let lock = NSLock()
    private var generation = StreamingSessionGeneration(id: UUID())
    var current: StreamingSessionGeneration {
        lock.lock(); defer { lock.unlock() }
        return generation
    }
    func advance() -> StreamingSessionGeneration {
        lock.lock(); defer { lock.unlock() }
        generation = StreamingSessionGeneration(id: UUID())
        return generation
    }
    func isCurrent(_ expected: StreamingSessionGeneration) -> Bool { current == expected }
}

fileprivate final class StreamingSubscriptionLifetime: @unchecked Sendable {
    let cancel: @Sendable () async -> Void
    init(cancel: @escaping @Sendable () async -> Void) { self.cancel = cancel }
    deinit {
        let cancel = cancel
        Task { await cancel() }
    }
}

actor StreamingClient {
    static let shared = StreamingClient()
    nonisolated private let sessionGate = StreamingSessionGenerationGate()
    nonisolated var sessionGeneration: StreamingSessionGeneration { sessionGate.current }
    nonisolated func isCurrentSession(_ generation: StreamingSessionGeneration) -> Bool {
        sessionGate.isCurrent(generation)
    }

    private struct ActiveStream {
        let continuation: AsyncStream<StreamEvent>.Continuation
    }
    private final class ReplayEntry {
        var snapshot = ChatStreamReplaySnapshot()
        var updatedAt: Date
        var access: UInt64
        init(updatedAt: Date, access: UInt64) {
            self.updatedAt = updatedAt
            self.access = access
        }
    }
    private var activeStreams: [String: [UUID: ActiveStream]] = [:]
    private var replay: [String: ReplayEntry] = [:]
    private var adoptedSession: StreamingSessionGeneration?
    private var accessCounter: UInt64 = 0
    private let maxInactiveReplayChats: Int
    private let replayLifetime: TimeInterval
    private let now: @Sendable () -> Date

    init(maxInactiveReplayChats: Int = 32, replayLifetime: TimeInterval = 300,
         now: @escaping @Sendable () -> Date = { Date() }) {
        self.maxInactiveReplayChats = max(0, maxInactiveReplayChats)
        self.replayLifetime = max(0, replayLifetime)
        self.now = now
    }

    /// Invalidates old producers/readers synchronously at the runtime boundary.
    /// Finishing actor-owned continuations is asynchronous, but their sequence
    /// wrappers reject already-buffered values as soon as this token changes.
    /// A delayed cleanup from A cannot clear B's newly adopted actor state.
    @discardableResult
    nonisolated func resetSession() -> Task<Void, Never> {
        let generation = sessionGate.advance()
        return Task { await self.clearInvalidatedSession(expected: generation) }
    }

    private func clearInvalidatedSession(expected: StreamingSessionGeneration) {
        guard sessionGate.isCurrent(expected) else { return }
        adoptCurrentSession()
    }
    private func adoptCurrentSession() {
        let generation = sessionGate.current
        guard adoptedSession != generation else { return }
        removeAllStreams()
        adoptedSession = generation
    }

    // The wrapper fences values already queued by AsyncStream.finish(). A plain
    // AsyncStream continues yielding its old buffer after finish, which is unsafe
    // across account/server changes even when every continuation was finished.
    struct Subscription: AsyncSequence, Sendable {
        typealias Element = StreamEvent
        fileprivate let stream: AsyncStream<StreamEvent>
        fileprivate let generation: StreamingSessionGeneration
        fileprivate let gate: StreamingSessionGenerationGate
        fileprivate let cancel: @Sendable () async -> Void
        struct AsyncIterator: AsyncIteratorProtocol {
            fileprivate var iterator: AsyncStream<StreamEvent>.Iterator
            fileprivate let generation: StreamingSessionGeneration
            fileprivate let gate: StreamingSessionGenerationGate
            fileprivate let lifetime: StreamingSubscriptionLifetime
            mutating func next() async -> StreamEvent? {
                guard !Task.isCancelled, gate.isCurrent(generation) else {
                    await lifetime.cancel()
                    return nil
                }
                let event = await iterator.next()
                guard !Task.isCancelled, gate.isCurrent(generation), event != nil else {
                    await lifetime.cancel()
                    return nil
                }
                return event
            }
        }
        func makeAsyncIterator() -> AsyncIterator {
            AsyncIterator(iterator: stream.makeAsyncIterator(), generation: generation, gate: gate,
                          lifetime: StreamingSubscriptionLifetime(cancel: cancel))
        }
    }
    enum StreamEvent: @unchecked Sendable {
        case taskInitiated(chatId: String, taskId: String, userMessageId: String)
        case typingStarted(chatId: String, messageId: String, metadata: ChatMetadata?)
        case chunk(chatId: String, messageId: String, sequence: Int, content: String, isFinal: Bool, userMessageId: String?, category: String?, modelName: String?, rejectionReason: String?)
        case thinkingChunk(chatId: String, messageId: String, content: String)
        case thinkingComplete(chatId: String, messageId: String)
        case messageReady(chatId: String, messageId: String)
        case preprocessingStep(chatId: String, step: String, data: [String: Any]?)
        case typingEnded(chatId: String, messageId: String?)
        case messageQueued(chatId: String, taskId: String?, userMessageId: String?, message: String?)
        case cancelRequested(chatId: String, taskId: String?)
        case postProcessingCompleted(chatId: String, taskId: String, followUpSuggestions: [String], newChatSuggestions: [String], chatSummary: String?, chatTags: [String], updatedTitle: String?)
        case error(String)
    }

    struct ChatMetadata: Sendable {
        let title: String?
        let iconNames: [String]
        let category: String?
        let modelName: String?
        let providerName: String?
        let serverRegion: String?
        let userMessageId: String?
        let encryptedChatKey: String?
    }

    func streamForChat(_ chatId: String, session: StreamingSessionGeneration? = nil,
                       replayBufferedState: Bool = true,
                       excludingMaterializedFinalMessageIDs: Set<String> = []) -> Subscription {
        adoptCurrentSession()
        let generation = session ?? sessionGate.current
        guard sessionGate.isCurrent(generation), adoptedSession == generation else {
            return Subscription(stream: AsyncStream { $0.finish() }, generation: generation, gate: sessionGate, cancel: {})
        }
        pruneReplay()
        let id = UUID()
        let stream = AsyncStream<StreamEvent> { continuation in
            activeStreams[chatId, default: [:]][id] = ActiveStream(continuation: continuation)
            if replayBufferedState, let snapshot = replay[chatId]?.snapshot {
                for event in snapshot.replayEvents(excludingMaterializedFinalMessageIDs: excludingMaterializedFinalMessageIDs) {
                    continuation.yield(event)
                }
            }
            continuation.onTermination = { @Sendable _ in
                Task { await self.removeSubscriber(chatId, id: id, generation: generation) }
            }
        }
        return Subscription(stream: stream, generation: generation, gate: sessionGate,
            cancel: { await self.removeSubscriber(chatId, id: id, generation: generation) })
    }

    /// Explicit chat deletion/teardown, not one window's unsubscribe operation.
    func removeStream(_ chatId: String) {
        let streams = activeStreams.removeValue(forKey: chatId) ?? [:]
        replay.removeValue(forKey: chatId)
        for stream in streams.values { stream.continuation.finish() }
    }
    func removeAllStreams() {
        let streams = activeStreams.values.flatMap { $0.values }
        activeStreams.removeAll()
        replay.removeAll()
        for stream in streams { stream.continuation.finish() }
    }
    private func removeSubscriber(_ chatId: String, id: UUID, generation: StreamingSessionGeneration) {
        guard sessionGate.isCurrent(generation), adoptedSession == generation else { return }
        let removed = activeStreams[chatId]?.removeValue(forKey: id)
        removed?.continuation.finish()
        if activeStreams[chatId]?.isEmpty == true { activeStreams.removeValue(forKey: chatId) }
        pruneReplay()
    }

    func dispatch(_ event: StreamEvent, for chatId: String, session: StreamingSessionGeneration? = nil) {
        adoptCurrentSession()
        let expected = session ?? sessionGate.current
        guard !Task.isCancelled, sessionGate.isCurrent(expected), adoptedSession == expected else { return }
        accessCounter &+= 1
        let entry = replay[chatId] ?? ReplayEntry(updatedAt: now(), access: accessCounter)
        entry.snapshot.apply(event)
        entry.updatedAt = now()
        entry.access = accessCounter
        replay[chatId] = entry
        if let streams = activeStreams[chatId] {
            for stream in streams.values { stream.continuation.yield(event) }
        }
        pruneReplay()
    }
    func dispatchToAll(_ event: StreamEvent, session: StreamingSessionGeneration? = nil) {
        adoptCurrentSession()
        let expected = session ?? sessionGate.current
        guard !Task.isCancelled, sessionGate.isCurrent(expected), adoptedSession == expected else { return }
        for streams in activeStreams.values {
            for stream in streams.values { stream.continuation.yield(event) }
        }
    }
    private func pruneReplay() {
        let date = now()
        let inactive = replay.filter { activeStreams[$0.key]?.isEmpty != false }
        for (chatID, entry) in inactive where date.timeIntervalSince(entry.updatedAt) >= replayLifetime {
            replay.removeValue(forKey: chatID)
        }
        let remaining = replay.filter { activeStreams[$0.key]?.isEmpty != false }
            .sorted { $0.value.access < $1.value.access }
        for entry in remaining.prefix(max(0, remaining.count - maxInactiveReplayChats)) {
            replay.removeValue(forKey: entry.key)
        }
    }

    struct ReplayStatistics: Equatable, Sendable {
        let chats: Int
        let subscribers: Int
        let retainedEvents: Int
        let cumulativeContentBytes: Int
        let thinkingBytes: Int
    }
    func replayStatistics() -> ReplayStatistics {
        adoptCurrentSession()
        pruneReplay()
        return ReplayStatistics(chats: replay.count,
            subscribers: activeStreams.values.reduce(0) { $0 + $1.count },
            retainedEvents: replay.values.reduce(0) { $0 + $1.snapshot.events.count },
            cumulativeContentBytes: replay.values.reduce(0) { $0 + $1.snapshot.cumulativeContentBytes },
            thinkingBytes: replay.values.reduce(0) { $0 + $1.snapshot.thinkingBytes })
    }
}

/// Coalesces only the replay representation. Live subscribers still receive the
/// original ordered events, including every thinking delta and terminal marker.
/// Reuses the real consumer lifecycle to reject stale/out-of-order replay chunks.
private struct ChatStreamReplaySnapshot {
    private enum Slot: Hashable {
        case task, typing, chunk, thinking, thinkingComplete, ready, preprocessing,
             ended, queued, cancel, postProcessing, error
    }
    private struct Entry { let order: UInt64; let event: StreamingClient.StreamEvent }
    private var entries: [Slot: Entry] = [:]
    private var order: UInt64 = 0
    private var lifecycle = ChatStreamingLifecycleState()
    private var taskID: String?
    private var messageID: String?
    private var userMessageID: String?
    private var category: String?
    private var modelName: String?
    private var rejectionReason: String?

    var events: [StreamingClient.StreamEvent] { entries.values.sorted { $0.order < $1.order }.map(\.event) }
    func replayEvents(excludingMaterializedFinalMessageIDs messageIDs: Set<String>) -> [StreamingClient.StreamEvent] {
        guard lifecycle.phase == .completed, messageID.map(messageIDs.contains) == true else { return events }
        // The row already renders from local history. Do not append it again as
        // plaintext, but keep newer suggestions/summary metadata observable.
        return entries[.postProcessing].map { [$0.event] } ?? []
    }
    var cumulativeContentBytes: Int {
        guard let event = entries[.chunk]?.event,
              case .chunk(_, _, _, let content, _, _, _, _, _) = event else { return 0 }
        return content.utf8.count
    }
    var thinkingBytes: Int { lifecycle.thinkingContent.utf8.count }

    mutating func apply(_ event: StreamingClient.StreamEvent) {
        if case .taskInitiated(_, let id, _) = event {
            // A duplicate initiation must not erase a later cumulative snapshot.
            if taskID == id { return }
            self = Self()
            taskID = id
        }
        // Release the replay alias before appending another thinking delta, so
        // the lifecycle accumulator can grow without copying its entire prefix
        // solely because this same snapshot retained the previous aggregate.
        if case .thinkingChunk = event { entries.removeValue(forKey: .thinking) }
        guard lifecycle.apply(event) else { return }
        if let incomingID = Self.messageID(in: event) {
            if let messageID, messageID != incomingID {
                for slot in [Slot.typing, .chunk, .thinking, .thinkingComplete, .ready, .ended] {
                    entries.removeValue(forKey: slot)
                }
                userMessageID = lifecycle.userMessageId
                category = nil; modelName = nil; rejectionReason = nil
                // A task can expose a newer assistant message without another
                // task-init frame. Replay describes that current message; its
                // predecessor belongs to the canonical chat history.
                if case .thinkingChunk = event {} else {
                    lifecycle.thinkingContent = ""
                    lifecycle.isThinkingStreaming = false
                }
            }
            messageID = incomingID
        }
        order &+= 1
        let slot: Slot
        var replayEvent = event
        switch event {
        case .taskInitiated(_, _, let user):
            slot = .task
            userMessageID = user.isEmpty ? nil : user
        case .typingStarted(let chat, let id, let metadata):
            slot = .typing
            let previous: StreamingClient.ChatMetadata?
            if let old = entries[.typing]?.event, case .typingStarted(_, _, let value) = old { previous = value }
            else { previous = nil }
            let merged = Self.merge(metadata, over: previous)
            replayEvent = .typingStarted(chatId: chat, messageId: id, metadata: merged)
            userMessageID = merged?.userMessageId ?? userMessageID
            category = merged?.category ?? category
            modelName = merged?.modelName ?? modelName
        case .chunk(let chat, let id, let sequence, let content, let final, let user, let category, let model, let rejection):
            slot = .chunk
            userMessageID = user ?? userMessageID
            self.category = category ?? self.category
            modelName = model ?? modelName
            rejectionReason = rejection ?? rejectionReason
            replayEvent = .chunk(chatId: chat, messageId: id, sequence: sequence, content: content,
                isFinal: final, userMessageId: userMessageID, category: self.category,
                modelName: modelName, rejectionReason: rejectionReason)
        case .thinkingChunk(let chat, let id, _):
            slot = .thinking
            replayEvent = .thinkingChunk(chatId: chat, messageId: id, content: lifecycle.thinkingContent)
        case .thinkingComplete: slot = .thinkingComplete
        case .messageReady: slot = .ready
        case .preprocessingStep: slot = .preprocessing
        case .typingEnded: slot = .ended
        case .messageQueued: slot = .queued
        case .cancelRequested: slot = .cancel
        case .postProcessingCompleted: slot = .postProcessing
        case .error: slot = .error
        }
        entries[slot] = Entry(order: order, event: replayEvent)
    }

    private static func messageID(in event: StreamingClient.StreamEvent) -> String? {
        switch event {
        case .typingStarted(_, let id, _), .chunk(_, let id, _, _, _, _, _, _, _),
             .thinkingChunk(_, let id, _), .thinkingComplete(_, let id), .messageReady(_, let id): return id
        case .typingEnded(_, let id): return id
        default: return nil
        }
    }

    private static func merge(_ incoming: StreamingClient.ChatMetadata?, over existing: StreamingClient.ChatMetadata?) -> StreamingClient.ChatMetadata? {
        guard let incoming else { return existing }
        guard let existing else { return incoming }
        return StreamingClient.ChatMetadata(title: incoming.title ?? existing.title,
            iconNames: incoming.iconNames.isEmpty ? existing.iconNames : incoming.iconNames,
            category: incoming.category ?? existing.category, modelName: incoming.modelName ?? existing.modelName,
            providerName: incoming.providerName ?? existing.providerName, serverRegion: incoming.serverRegion ?? existing.serverRegion,
            userMessageId: incoming.userMessageId ?? existing.userMessageId,
            encryptedChatKey: incoming.encryptedChatKey ?? existing.encryptedChatKey)
    }
}

/// A terminal display replay is unnecessary when local history already owns
/// the final encrypted row. Re-appending transient plaintext would remove its
/// encryption metadata. This is a display/persistence-deduplication predicate,
/// not proof of server commitment: recovery and legacy queues own delivery.
/// Explicitly pending rows still replay and retain their recovery behavior.
enum ChatStreamReplayPolicy {
    static func materializedFinalMessageIDs(in messages: [Message], chatID: String,
                                    pendingMessageIDs: Set<String>) -> Set<String> {
        Set(messages.compactMap { message in
            guard message.chatId == chatID,
                  message.role == .assistant || message.role == .system,
                  message.isStreaming != true,
                  message.encryptedContent?.isEmpty == false,
                  !pendingMessageIDs.contains(message.id) else { return nil }
            return message.id
        })
    }
}

@MainActor
final class OrderedStreamEventDispatcher {
    typealias Dispatch = @Sendable (StreamingClient.StreamEvent, String) async -> Void
    private let dispatch: @Sendable (StreamingClient.StreamEvent, String, StreamingSessionGeneration) async -> Void
    private let client: StreamingClient
    private var pendingEvents: [(event: StreamingClient.StreamEvent, chatId: String, session: StreamingSessionGeneration)] = []
    private var drainTask: Task<Void, Never>?
    private var generation = 0

    init(_ dispatch: Dispatch? = nil, client: StreamingClient = .shared) {
        self.client = client
        self.dispatch = { event, chatID, session in
            if let dispatch { await dispatch(event, chatID) }
            else { await client.dispatch(event, for: chatID, session: session) }
        }
    }
    func enqueue(_ event: StreamingClient.StreamEvent, for chatId: String) {
        pendingEvents.append((event, chatId, client.sessionGeneration))
        guard drainTask == nil else { return }
        let expectedGeneration = generation
        drainTask = Task { [weak self] in await self?.drain(expectedGeneration: expectedGeneration) }
    }
    /// Socket replacement/disconnect invalidates its queued and in-flight drain.
    /// A cancelled drain cannot consume a newer transport's queue or clear its task.
    func reset() {
        generation += 1
        pendingEvents.removeAll()
        drainTask?.cancel()
        drainTask = nil
    }
    func waitUntilIdle() async {
        while let drainTask { await drainTask.value }
    }
    private func drain(expectedGeneration: Int) async {
        while generation == expectedGeneration, !Task.isCancelled, !pendingEvents.isEmpty {
            let next = pendingEvents.removeFirst()
            guard client.isCurrentSession(next.session) else { continue }
            await dispatch(next.event, next.chatId, next.session)
        }
        if generation == expectedGeneration { drainTask = nil }
    }
}
