// Revision-aware queued follow-up state and composer ownership.
// Web: frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts
// Specification: specifications/features/chat-queued-followups/specification.yml
// Assertions: chat-queued-followups.editing.stable-revision, chat-queued-followups.editing.cancel,
// chat-queued-followups.steering.safe-boundary, chat-queued-followups.access.scoped
import Foundation

struct ChatQueuedFollowupState: Equatable, Sendable, Identifiable {
    enum Phase: String, Sendable { case queued, processing, paused }
    let chatID: String
    let messageID: String
    let revision: Int
    let mode: ChatQueuedRevisionRequest.Mode
    let phase: Phase
    var id: String { messageID }
    var editable: Bool { phase == .queued }

    static func parse(_ fields: [String: Any], chatID: String? = nil) -> Self? {
        guard let chat = fields["chat_id"] as? String ?? chatID, !chat.isEmpty,
              let message = fields["message_id"] as? String ?? fields["user_message_id"] as? String, !message.isEmpty,
              let revision = fields["queue_revision"] as? Int, revision >= 1,
              let mode = fields["queue_mode"] as? String, let mode = ChatQueuedRevisionRequest.Mode(rawValue: mode) else { return nil }
        return Self(chatID: chat, messageID: message, revision: revision, mode: mode, phase: .queued)
    }
    static func from(_ message: Message) -> Self? {
        guard message.role == .user, let revision = message.queueRevision, revision >= 1,
              let rawMode = message.queueMode ?? message.queueDispatchMode, let mode = ChatQueuedRevisionRequest.Mode(rawValue: rawMode),
              message.queueDispatchStatus == "queued" || message.deliveryStatus == "queued" else { return nil }
        return Self(chatID: message.chatId, messageID: message.id, revision: revision, mode: mode, phase: .queued)
    }
    /// A newer queue label cannot grant edit authority over an older row.
    /// Equal revisions require byte-identical protected content when supplied.
    func acceptsProtectedRow(_ row: Message, incomingCiphertext: String?, incomingEncryptedMappings: String? = nil) -> Bool {
        guard row.id == messageID, row.chatId == chatID, row.role == .user,
              (row.queueRevision ?? 0) <= revision else { return false }
        if let incomingCiphertext {
            guard !incomingCiphertext.isEmpty else { return false }
            return row.queueRevision != revision || (row.encryptedContent == incomingCiphertext && row.encryptedPIIMappings == incomingEncryptedMappings)
        }
        return row.queueRevision == revision || (row.queueRevision == nil && revision == 1)
    }
    func mayAccept(_ next: Self, hasCiphertext: Bool) -> Bool {
        phase == .queued && chatID == next.chatID && messageID == next.messageID
            && next.revision >= revision && (next.revision != revision || next.mode == mode)
            && (next.revision <= revision + 1 || hasCiphertext)
    }
}

struct ChatQueuedEditSession: Equatable, Sendable {
    let state: ChatQueuedFollowupState
    let scope: UUID
    let teamEpoch: UInt64
    let originalContent: String
    var previousDraft: ComposerDocumentV1
    var ownedDraft: ComposerDocumentV1
    var ownedRevision: Int

    /// Cancel restores only the composer snapshot still owned by this edit.
    /// Newer typing is kept, including a same-text ABA with another revision.
    func draftOnCancel(current: ComposerDocumentV1, revision: Int) -> ComposerDocumentV1 {
        current == ownedDraft && revision == ownedRevision ? previousDraft : current
    }
    func isUnchanged(_ content: String) -> Bool { content == originalContent }
}

extension Message {
    func afterQueuedDispatch(_ phase: ChatQueuedFollowupState.Phase) -> Message {
        Message(id: id, chatId: chatId, role: role, content: content, encryptedContent: encryptedContent,
            createdAt: createdAt, updatedAt: updatedAt, appId: appId, isStreaming: isStreaming, embedRefs: embedRefs,
            modelName: modelName, senderName: senderName, category: category, encryptedSenderName: encryptedSenderName,
            encryptedCategory: encryptedCategory, encryptedModelName: encryptedModelName, piiMappings: piiMappings,
            encryptedPIIMappings: encryptedPIIMappings, thinkingContent: thinkingContent, encryptedThinkingContent: encryptedThinkingContent,
            encryptedThinkingSignature: encryptedThinkingSignature, thinkingTokenCount: thinkingTokenCount,
            serverMessageId: serverMessageId, userMessageId: userMessageId, queueDispatchStatus: phase.rawValue, deliveryStatus: "synced")
    }
    func replacingQueuedContent(_ content: String?, ciphertext: String?, mappings: [PIIMapping]?, encryptedMappings: String?,
                                queue: ChatQueuedFollowupState) -> Message {
        Message(id: id, chatId: chatId, role: role, content: content ?? self.content, encryptedContent: ciphertext ?? encryptedContent,
            createdAt: createdAt, updatedAt: updatedAt, appId: appId, isStreaming: isStreaming, embedRefs: embedRefs,
            modelName: modelName, senderName: senderName, category: category, encryptedSenderName: encryptedSenderName,
            encryptedCategory: encryptedCategory, encryptedModelName: encryptedModelName, piiMappings: mappings ?? piiMappings,
            encryptedPIIMappings: encryptedMappings, thinkingContent: thinkingContent, encryptedThinkingContent: encryptedThinkingContent,
            encryptedThinkingSignature: encryptedThinkingSignature, thinkingTokenCount: thinkingTokenCount,
            serverMessageId: serverMessageId, userMessageId: userMessageId, queueRevision: queue.revision,
            queueMode: queue.mode.rawValue, queueDispatchStatus: queue.phase.rawValue, queueDispatchMode: queue.mode.rawValue,
            deliveryStatus: queue.phase == .queued ? "queued" : "synced")
    }
}

/// Serializes optimistic messages_v preparation through remote admission. The
/// lease follows immutable background retries across reconnects and separates
/// account, server, key and Team ownership. Socket-bound receipt checks still
/// precede every transmission; this ordering gate grants no network authority.
@MainActor
final class ChatSavedSendAdmissionGate {
    static let shared = ChatSavedSendAdmissionGate()
    struct Key: Hashable {
        let account: UUID
        let server: String
        let keyGeneration: UUID
        let teamID: String?
        let teamEpoch: UInt64
        let chatID: String
        init(scope: ChatPreparationScope, chatID: String) {
            account = scope.account; server = scope.server; keyGeneration = scope.keyGeneration
            teamID = scope.teamID; teamEpoch = scope.teamEpoch
            self.chatID = chatID
        }
    }
    @MainActor final class Lease {
        private var onRelease: (() -> Void)?
        fileprivate init(_ onRelease: @escaping () -> Void) { self.onRelease = onRelease }
        func release() { let action = onRelease; onRelease = nil; action?() }
    }
    private struct Waiter {
        let id: UUID
        let continuation: CheckedContinuation<Lease, Error>
    }
    private var owned = Set<Key>()
    private var waiters: [Key: [Waiter]] = [:]

    func acquire(_ key: Key) async throws -> Lease {
        try Task.checkCancellation()
        if owned.insert(key).inserted { return lease(for: key) }
        let id = UUID()
        let acquired: Lease = try await withTaskCancellationHandler(operation: {
            try Task.checkCancellation()
            return try await withCheckedThrowingContinuation { continuation in
                waiters[key, default: []].append(Waiter(id: id, continuation: continuation))
            }
        }, onCancel: {
            Task { @MainActor [weak self] in self?.cancel(id, key: key) }
        })
        if Task.isCancelled { acquired.release(); throw CancellationError() }
        return acquired
    }
    private func lease(for key: Key) -> Lease {
        Lease { [weak self] in self?.release(key) }
    }
    private func cancel(_ id: UUID, key: Key) {
        guard let index = waiters[key]?.firstIndex(where: { $0.id == id }),
              let waiter = waiters[key]?.remove(at: index) else { return }
        if waiters[key]?.isEmpty == true { waiters.removeValue(forKey: key) }
        waiter.continuation.resume(throwing: CancellationError())
    }
    private func release(_ key: Key) {
        if var pending = waiters.removeValue(forKey: key), !pending.isEmpty {
            let next = pending.removeFirst()
            if !pending.isEmpty { waiters[key] = pending }
            next.continuation.resume(returning: lease(for: key))
        } else { owned.remove(key) }
    }
}
