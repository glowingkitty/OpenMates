// Web: frontend/packages/ui/src/components/AssistantActivityGroup.svelte
//      frontend/packages/ui/src/components/sub_chats/SubChatBatchPreview.svelte
// Wire: backend/apps/ai/tasks/stream_consumer.py _build_sub_chat_batch_marker,
//       _publish_sub_chat_progress (pinned 78e8d990)
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.rendering.assistant-document-convergence, chats.surface.semantic-parity
import Combine
import Foundation

struct SubChatActivityIdentity: Hashable {
    let parentID: String
    let batchID: String
    let taskID: String?
    let parentMessageID: String?
    init(_ descriptor: SubChatBatchDescriptor, parentID: String) {
        self.parentID = parentID; batchID = descriptor.batchID
        taskID = descriptor.taskID; parentMessageID = descriptor.parentMessageID
    }
}

/// Scoped to one mounted message. Retains only observed terminal authority,
/// never message/child plaintext, and cannot settle an unmatched batch.
struct SubChatActivityCompletionState: Equatable {
    private(set) var terminalStatuses: [SubChatActivityIdentity: String] = [:]
    mutating func observe(_ progress: SubChatProgress?, descriptors: [SubChatBatchDescriptor],
                          parentID: String, messageID: String?) {
        for descriptor in descriptors {
            guard let status = SubChatActivityProvenance.progress(progress, for: descriptor,
                parentID: parentID, messageID: messageID)?.status,
                AssistantActivityProjection.terminal(status) else { continue }
            let identity = SubChatActivityIdentity(descriptor, parentID: parentID)
            guard terminalStatuses[identity] == nil else { continue }
            terminalStatuses[identity] = SubChatActivityProvenance.status(for: descriptor, parentID: parentID,
                messageID: messageID, progress: progress, terminalChildIDs: [])
        }
    }
}

enum SubChatActivityProvenance {
    /// A parent-chat event alone is insufficient. Marker task provenance and a
    /// known assistant identity must agree; an active child must belong to it.
    /// Never infer task identity from the printable batch ID.
    static func progress(_ value: SubChatProgress?, for descriptor: SubChatBatchDescriptor,
                         parentID: String, messageID: String?) -> SubChatProgress? {
        guard let value, value.chatId == parentID, descriptor.parentChatID == parentID,
              let task = descriptor.taskID, !task.isEmpty, value.taskId == task,
              let message = value.messageId, !message.isEmpty else { return nil }
        guard let markerMessage = descriptor.parentMessageID, !markerMessage.isEmpty else { return nil }
        // The current producer can use its task ID as the marker's parent
        // message alias. Only that documented alias may resolve to the row ID.
        let exactMessage = message == markerMessage
        let canonicalAlias = markerMessage == task && message == messageID
        guard exactMessage || canonicalAlias else { return nil }
        if let active = value.activeSubChatId, !active.isEmpty,
           !descriptor.subChatIDs.contains(active) { return nil }
        return value
    }

    static func status(for descriptor: SubChatBatchDescriptor, parentID: String, messageID: String?,
                       progress: SubChatProgress?, terminalChildIDs: Set<String>,
                       retainedTerminalStatuses: [SubChatActivityIdentity: String] = [:]) -> String {
        if let retained = retainedTerminalStatuses[SubChatActivityIdentity(descriptor, parentID: parentID)] { return retained }
        if AssistantActivityProjection.terminal(descriptor.status) { return descriptor.status }
        if !descriptor.subChatIDs.isEmpty && descriptor.subChatIDs.allSatisfy(terminalChildIDs.contains) { return "finished" }
        guard let status = self.progress(progress, for: descriptor, parentID: parentID, messageID: messageID)?.status else {
            return descriptor.status
        }
        switch status {
        case "finished", "completed": return "finished"
        case "failed", "error": return "error"
        case "stopped", "cancelled": return "cancelled"
        default: return descriptor.status
        }
    }

    static func isTerminalChild(_ child: Chat, parentID: String, messages: [Message], pendingRecoveryIDs: Set<String>) -> Bool {
        guard child.parentId == parentID else { return false }
        if child.chatSummary?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false
            || child.encryptedChatSummary?.isEmpty == false { return true }
        guard let last = messages.last, last.chatId == child.id, last.role == .assistant, last.isStreaming != true else { return false }
        let aliases = Set([last.id, last.serverMessageId].compactMap { $0 })
        return aliases.isDisjoint(with: pendingRecoveryIDs)
    }
}

/// Forwards the supplied account-scoped store's observation without copying its
/// plaintext or starting requests. A scope transition invalidates this observer;
/// the existing message render identity creates its replacement in the new scope.
@MainActor
final class SubChatActivityStoreObserver: @MainActor ObservableObject {
    let objectWillChange = ObservableObjectPublisher()
    private weak var store: ChatStore?
    private let scope: UUID
    private let scopeGeneration: @MainActor () -> UUID
    private var subscription: AnyCancellable?

    init(store: ChatStore?, scopeGeneration: @escaping @MainActor () -> UUID = { OfflineStore.shared.scopeGeneration }) {
        self.scopeGeneration = scopeGeneration
        scope = scopeGeneration()
        bind(store)
    }
    func bind(_ store: ChatStore?) {
        guard self.store !== store else { return }
        subscription?.cancel(); self.store = store
        subscription = store?.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }
        objectWillChange.send()
    }
    func terminalChildIDs(descriptors: [SubChatBatchDescriptor], parentID: String) -> Set<String> {
        guard scope == scopeGeneration(), let store else { return [] }
        let referenced = Set(descriptors.filter { $0.accepts(parentID: parentID) }.flatMap(\.subChatIDs))
        return Set(referenced.filter { id in
            guard let child = store.chat(for: id), child.parentId == parentID else { return false }
            return SubChatActivityProvenance.isTerminalChild(child, parentID: parentID,
                messages: store.messages(for: id), pendingRecoveryIDs: store.pendingAssistantRecoveryMessageIds(in: id))
        })
    }
}
