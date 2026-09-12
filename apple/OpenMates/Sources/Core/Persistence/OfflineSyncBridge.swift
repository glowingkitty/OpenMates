// Offline sync bridge — coordinates between the in-memory ChatStore, the persistent
// OfflineStore (SwiftData), and the network SyncManager. Handles:
// 1. Persisting synced data to disk as it arrives
// 2. Loading from disk on cold boot (before WebSocket connects)
// 3. Queuing user actions when offline and replaying them on reconnect
// 4. Network reachability monitoring via NWPathMonitor

import CryptoKit
import Foundation
import Network
import SwiftUI

@MainActor
final class OfflineSyncBridge: ObservableObject {
    @Published private(set) var networkStatus: NetworkStatus = .unknown

    enum NetworkStatus: Equatable {
        case unknown
        case online
        case offline
    }

    private let chatStore: ChatStore
    private weak var wsManager: WebSocketManager?
    private let offlineStore: OfflineStore
    private let scopeGeneration: UUID
    private var isCurrentSession: Bool {
        isSessionActive && scopeGeneration == offlineStore.scopeGeneration
    }
    private let pathMonitor = NWPathMonitor()
    private let monitorQueue = DispatchQueue(label: "org.openmates.network-monitor")
    private var isNetworkMonitoringStarted = false
    private var isSessionActive = true
    private var latestPath: NWPath?
    private var offlinePrefetchTask: Task<Void, Never>?
    private var offlinePrefetchCursor = 10

    private let offlinePrefetchChunkSize = 3
    private let startupRecentChatLimit = 20
    private let offlinePrefetchMaxMessages = 10_000
    private let offlinePrefetchInterChunkDelayNs: UInt64 = 2_000_000_000

    init(chatStore: ChatStore, wsManager: WebSocketManager? = nil, offlineStore: OfflineStore = .shared) {
        self.chatStore = chatStore
        self.wsManager = wsManager
        self.offlineStore = offlineStore
        self.scopeGeneration = offlineStore.scopeGeneration
    }

    deinit {
        pathMonitor.cancel()
    }

    // MARK: - Network monitoring

    func startNetworkMonitoring() {
        guard isCurrentSession else { return }
        guard !isNetworkMonitoringStarted else { return }
        isNetworkMonitoringStarted = true
        pathMonitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor [weak self] in
                guard let self, self.isCurrentSession else { return }
                self.latestPath = path
                let newStatus: NetworkStatus = path.status == .satisfied ? .online : .offline
                let wasOffline = self.networkStatus == .offline
                self.networkStatus = newStatus
                self.offlineStore.setOffline(newStatus == .offline)

                if wasOffline && newStatus == .online {
                    await self.replayPendingActions()
                    self.startOfflinePrefetchIfEligible(reason: "networkRestored")
                }
            }
        }
        pathMonitor.start(queue: monitorQueue)
    }

    // MARK: - Optional offline content prefetch

    func startOfflinePrefetchIfEligible(reason: String) {
        guard isCurrentSession, offlinePrefetchTask == nil else { return }
        guard canRunOfflinePrefetch else {
            NativeSyncPerfLog.info("phase=offlinePrefetch skipped reason=notEligible trigger=\(reason)")
            return
        }

        offlinePrefetchTask = Task { @MainActor [weak self] in
            await self?.runOfflinePrefetch(reason: reason)
        }
    }

    func cancelOfflinePrefetch() {
        offlinePrefetchTask?.cancel()
        offlinePrefetchTask = nil
    }

    private var canRunOfflinePrefetch: Bool {
        guard networkStatus == .online else { return false }
        if let latestPath {
            guard latestPath.status == .satisfied else { return false }
            guard !latestPath.isExpensive && !latestPath.isConstrained else { return false }
        }
        let processInfo = ProcessInfo.processInfo
        guard !processInfo.isLowPowerModeEnabled else { return false }
        switch processInfo.thermalState {
        case .nominal, .fair:
            break
        case .serious, .critical:
            return false
        @unknown default:
            return false
        }
        return offlineStore.persistedMessageCount() < offlinePrefetchMaxMessages
    }

    private func runOfflinePrefetch(reason: String) async {
        defer { offlinePrefetchTask = nil }

        let generation = offlineStore.scopeGeneration
        var cursor = offlinePrefetchCursor
        NativeSyncPerfLog.info("phase=offlinePrefetch start cursor=\(cursor) reason=\(reason)")

        while !Task.isCancelled && canRunOfflinePrefetch {
            do {
                let response: OfflinePrefetchResponse = try await APIClient.shared.request(
                    .post,
                    path: "/v1/sync/offline-prefetch",
                    body: OfflinePrefetchRequest(
                        cursor: cursor,
                        limit: offlinePrefetchChunkSize,
                        includeEmbeds: true
                    )
                )
                guard !Task.isCancelled, isCurrentSession,
                      generation == offlineStore.scopeGeneration else { return }
                persistOfflinePrefetch(response)

                NativeSyncPerfLog.info(
                    "phase=offlinePrefetch chunk cursor=\(cursor) next=\(response.nextCursor.map(String.init) ?? "done") chats=\(response.chats.count) messages=\(response.messagesByChatId.values.reduce(0) { $0 + $1.count }) embeds=\(response.embeds.count) done=\(response.done)"
                )

                guard let nextCursor = response.nextCursor, !response.done else {
                    offlinePrefetchCursor = 10
                    return
                }
                offlinePrefetchCursor = nextCursor
                cursor = nextCursor
                try? await Task.sleep(nanoseconds: offlinePrefetchInterChunkDelayNs)
            } catch {
                NativeSyncPerfLog.warning("phase=offlinePrefetch failed cursor=\(cursor) error=\(error.localizedDescription)")
                return
            }
        }
    }

    private func persistOfflinePrefetch(_ response: OfflinePrefetchResponse) {
        let eligibleChats = response.chats.filter { !$0.isHiddenFromNormalSurfaces }
        let skippedChats = response.chats.count - eligibleChats.count
        let eligibleChatIds = response.chats.isEmpty ? nil : Set(eligibleChats.map(\.id))

        if !eligibleChats.isEmpty {
            offlineStore.persistChats(eligibleChats)
        }
        if !response.embedKeys.isEmpty {
            EmbedKeyManager.shared.store(response.embedKeys, source: "offlinePrefetch")
            offlineStore.persistEmbedKeys(response.embedKeys)
        }

        let messagesByChat = response.decodedMessagesByChat().filter { chatId, _ in
            eligibleChatIds?.contains(chatId) ?? true
        }
        if !messagesByChat.isEmpty {
            offlineStore.persistMessagesBatch(messagesByChat)
        }

        let embedsByChat = response.groupedEmbedsByChat(messagesByChat: messagesByChat).filter { chatId, _ in
            eligibleChatIds?.contains(chatId) ?? true
        }
        if !embedsByChat.isEmpty {
            offlineStore.persistEmbedsBatch(embedsByChat)
        }
        if skippedChats > 0 {
            NativeSyncPerfLog.info("phase=offlinePrefetch skippedHiddenChats=\(skippedChats)")
        }
    }

    // MARK: - Cold boot: load from disk before network is available

    func loadFromDisk(lastOpenedChatId: String? = nil) {
        guard isCurrentSession else { return }
        let start = NativeSyncPerfLog.now()
        let lastOpenedLabel = lastOpenedChatId.map { String($0.prefix(8)) } ?? "none"
        chatStore.performWithoutPersistence {
            loadPersistedDataIntoStore(lastOpenedChatId: lastOpenedChatId)
        }
        NativeSyncPerfLog.info(
            "phase=offlineColdLoad lastOpened=\(lastOpenedLabel) limit=\(startupRecentChatLimit) elapsedMs=\(NativeSyncPerfLog.ms(since: start))"
        )
    }

    private func loadPersistedDataIntoStore(lastOpenedChatId: String?) {
        let embedKeys = offlineStore.loadEmbedKeys()
        if !embedKeys.isEmpty {
            EmbedKeyManager.shared.store(embedKeys, source: "offline")
        }

        let chats = offlineStore.loadStartupChats(
            lastOpenedChatId: lastOpenedChatId,
            limit: startupRecentChatLimit
        )
        for chat in chats {
            chatStore.upsertChat(chat)
        }

        for chat in chats.prefix(5) {
            let messages = offlineStore.loadLatestMessageWindow(chatId: chat.id)
            if !messages.isEmpty {
                chatStore.setMessages(for: chat.id, messages: messages)
            }
            let embeds = offlineStore.loadEmbeds(chatId: chat.id)
            if !embeds.isEmpty {
                chatStore.upsertEmbeds(embeds, for: chat.id)
            }
        }
    }

    // MARK: - Persist data as it arrives from sync

    func onChatsReceived(_ chats: [Chat]) {
        guard isCurrentSession else { return }
        offlineStore.persistChats(chats)
    }

    func onMessagesReceived(_ messages: [Message], chatId: String) {
        guard isCurrentSession else { return }
        offlineStore.persistMessages(messages, chatId: chatId)
    }

    func onEmbedsReceived(_ embeds: [EmbedRecord], chatId: String) {
        guard isCurrentSession else { return }
        offlineStore.persistEmbeds(embeds, chatId: chatId)
    }

    func onSyncContentReceived(
        messagesByChat: [String: [Message]],
        embedsByChat: [String: [EmbedRecord]]
    ) {
        guard isCurrentSession else { return }
        if !messagesByChat.isEmpty {
            offlineStore.persistMessagesBatch(messagesByChat)
        }
        if !embedsByChat.isEmpty {
            offlineStore.persistEmbedsBatch(embedsByChat)
        }
    }

    func onChatDeleted(_ chatId: String) {
        guard isCurrentSession else { return }
        offlineStore.deleteChat(chatId)
    }

    // MARK: - Queue offline actions

    func sendMessageOffline(chatId: String, messageId: String, content: String) {
        guard isCurrentSession else { return }
        let userMessage = Message(
            id: messageId, chatId: chatId, role: .user,
            content: content, encryptedContent: nil,
            createdAt: ISO8601DateFormatter().string(from: Date()),
            updatedAt: nil, appId: nil, isStreaming: nil, embedRefs: nil
        )
        chatStore.appendMessage(userMessage, to: chatId)
        offlineStore.persistMessages([userMessage], chatId: chatId)

        offlineStore.queueOfflineAction(type: "send_message", payload: [
            "chat_id": chatId,
            "message_id": messageId,
            "content": content,
            "created_at": Int(Date().timeIntervalSince1970),
        ])
    }

    func deleteMessageOffline(chatId: String, messageId: String) {
        guard isCurrentSession else { return }
        offlineStore.queueOfflineAction(type: "delete_message", payload: [
            "chat_id": chatId,
            "message_id": messageId,
        ])
    }

    func pinChatOffline(chatId: String, isPinned: Bool) {
        guard isCurrentSession else { return }
        offlineStore.queueOfflineAction(type: "pin_chat", payload: [
            "chat_id": chatId,
            "is_pinned": isPinned,
        ])
    }

    func archiveChatOffline(chatId: String) {
        guard isCurrentSession else { return }
        offlineStore.queueOfflineAction(type: "archive_chat", payload: [
            "chat_id": chatId,
        ])
    }

    func hideChatOffline(chatId: String) {
        guard isCurrentSession else { return }
        offlineStore.queueOfflineAction(type: "hide_chat", payload: [
            "chat_id": chatId,
        ])
    }

    func queueDraftUpdate(_ record: ComposerDraftRecord) {
        guard isCurrentSession else { return }
        offlineStore.queueOfflineAction(type: "update_draft", payload: [
            "chat_id": record.chatId,
            "encrypted_draft_md": record.encryptedMarkdown,
            "encrypted_draft_preview": record.encryptedPreview,
            "revision": record.revision,
            "draft_v": record.draftVersion,
        ])
    }

    func queueDraftDelete(chatId: String) {
        guard isCurrentSession else { return }
        offlineStore.queueOfflineAction(type: "delete_draft", payload: ["chat_id": chatId])
    }

    func cascadeDeleteChat(chatId: String) {
        deleteChat(chatId, preservingDraftTombstone: false)
    }

    func cascadeDeleteDraftOnlyChat(chatId: String) {
        deleteChat(chatId, preservingDraftTombstone: true)
    }

    private func deleteChat(_ chatId: String, preservingDraftTombstone: Bool) {
        guard isCurrentSession else { return }
        offlineStore.deleteChat(chatId, preservingDraftTombstone: preservingDraftTombstone)
        ChatKeyManager.shared.removeKey(for: chatId)
        EmbedKeyManager.shared.removeKeys(for: chatId)
        PendingUploadStore.shared.clearForChat(chatId)
        UnreadMessagesStore.shared.clearUnread(chatId: chatId)
        SpotlightIndexer.shared.removeChat(chatId)
    }

    // MARK: - Replay pending actions on reconnect

    func replayPendingActions() async {
        guard isCurrentSession else { return }
        let generation = offlineStore.scopeGeneration
        let actions = offlineStore.loadPendingActions()
        guard !actions.isEmpty else { return }

        for action in actions {
            guard isCurrentSession, generation == offlineStore.scopeGeneration else { return }
            guard action.retryCount < 3 else {
                offlineStore.removePendingAction(action.id)
                continue
            }

            guard let payloadData = action.payloadJSON,
                  let payload = try? JSONSerialization.jsonObject(with: payloadData) as? [String: Any] else {
                offlineStore.removePendingAction(action.id)
                continue
            }

            do {
                switch action.actionType {
                case "send_message":
                    try await replaySendMessage(payload)
                case "delete_message":
                    try await replayDeleteMessage(payload)
                case "pin_chat":
                    try await replayPinChat(payload)
                case "archive_chat":
                    try await replayArchiveChat(payload)
                case "hide_chat":
                    try await replayHideChat(payload)
                case "update_draft":
                    try await replayDraftUpdate(payload)
                case "delete_draft":
                    try await replayDraftDelete(payload)
                default:
                    break
                }
                guard isCurrentSession, generation == offlineStore.scopeGeneration else { return }
                offlineStore.removePendingAction(action.id)
            } catch {
                guard isCurrentSession, generation == offlineStore.scopeGeneration else { return }
                print("[OfflineSync] Replay failed for \(action.actionType): \(error)")
                offlineStore.incrementRetry(action.id)
            }
        }
    }

    private func replaySendMessage(_ payload: [String: Any]) async throws {
        guard let chatId = payload["chat_id"] as? String,
              let content = payload["content"] as? String else { return }
        guard let chat = chatStore.chat(for: chatId) else { return }
        _ = try await ChatSendPipeline().sendUserMessage(
            content: content,
            in: chat,
            existingMessages: chatStore.messages(for: chatId),
            wsManager: wsManager,
            chatStore: chatStore
        )
    }

    private func replayDeleteMessage(_ payload: [String: Any]) async throws {
        guard let chatId = payload["chat_id"] as? String,
              let messageId = payload["message_id"] as? String else { return }
        let _: Data = try await APIClient.shared.request(
            .delete, path: "/v1/chats/\(chatId)/messages/\(messageId)"
        )
    }

    private func replayPinChat(_ payload: [String: Any]) async throws {
        guard let chatId = payload["chat_id"] as? String else { return }
        let isPinned = payload["is_pinned"] as? Bool ?? true
        let _: Data = try await APIClient.shared.request(
            .patch, path: "/v1/chats/\(chatId)",
            body: ["is_pinned": isPinned]
        )
    }

    private func replayArchiveChat(_ payload: [String: Any]) async throws {
        guard let chatId = payload["chat_id"] as? String else { return }
        let _: Data = try await APIClient.shared.request(
            .patch, path: "/v1/chats/\(chatId)",
            body: ["is_archived": true]
        )
    }

    private func replayHideChat(_ payload: [String: Any]) async throws {
        guard let chatId = payload["chat_id"] as? String else { return }
        let _: Data = try await APIClient.shared.request(
            .post, path: "/v1/chats/\(chatId)/hide"
        )
    }

    private func replayDraftUpdate(_ payload: [String: Any]) async throws {
        guard let chatId = payload["chat_id"] as? String,
              let encryptedMarkdown = payload["encrypted_draft_md"] as? String,
              let encryptedPreview = payload["encrypted_draft_preview"] as? String else {
            throw OfflineDraftReplayError.invalidEncryptedPayload
        }
        guard let wsManager else { throw OfflineDraftReplayError.transportUnavailable }
        try await wsManager.sendDraftSyncMessage(DraftSyncMessage(type: "update_draft", payload: [
            "chat_id": chatId,
            "encrypted_draft_md": encryptedMarkdown,
            "encrypted_draft_preview": encryptedPreview,
        ]))
    }

    private func replayDraftDelete(_ payload: [String: Any]) async throws {
        guard let chatId = payload["chat_id"] as? String else {
            throw OfflineDraftReplayError.invalidEncryptedPayload
        }
        guard let wsManager else { throw OfflineDraftReplayError.transportUnavailable }
        try await wsManager.sendDraftSyncMessage(DraftSyncMessage(
            type: "delete_draft",
            payload: ["chat_id": chatId]
        ))
    }

    // Stop old-session callbacks without deleting its queued offline work.
    func stopSession() {
        isSessionActive = false
        cancelOfflinePrefetch()
        pathMonitor.cancel()
    }

}

extension OfflineSyncBridge: DraftSyncOfflineActions {}

private enum OfflineDraftReplayError: Error {
    case invalidEncryptedPayload
    case transportUnavailable
}

private struct OfflinePrefetchRequest: Encodable {
    let cursor: Int
    let limit: Int
    let includeEmbeds: Bool
}

private struct OfflinePrefetchResponse: Decodable {
    let chats: [Chat]
    let messagesByChatId: [String: [String]]
    let embeds: [EmbedRecord]
    let embedKeys: [EmbedKeyRecord]
    let nextCursor: Int?
    let done: Bool

    func decodedMessagesByChat() -> [String: [Message]] {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return messagesByChatId.mapValues { rawMessages in
            rawMessages.compactMap { raw in
                guard let data = raw.data(using: .utf8) else { return nil }
                return try? decoder.decode(Message.self, from: data)
            }
        }.filter { !$0.value.isEmpty }
    }

    func groupedEmbedsByChat(messagesByChat: [String: [Message]]) -> [String: [EmbedRecord]] {
        var result: [String: [EmbedRecord]] = [:]
        var chatIdsByHash: [String: String] = [:]
        for chat in chats {
            let digest = SHA256.hash(data: Data(chat.id.utf8))
            chatIdsByHash[digest.map { String(format: "%02x", $0) }.joined()] = chat.id
        }

        let embedsById = EmbedRecord.dictionaryById(embeds, context: "offlinePrefetch")
        for chat in chats {
            let referencedIds = Set(messagesByChat[chat.id]?.flatMap { $0.embedRefs?.map(\.id) ?? [] } ?? [])
            if referencedIds.isEmpty {
                let digest = SHA256.hash(data: Data(chat.id.utf8))
                let hashedChatId = digest.map { String(format: "%02x", $0) }.joined()
                let hashedEmbeds = embeds.filter { $0.hashedChatId == hashedChatId }
                if !hashedEmbeds.isEmpty {
                    result[chat.id] = hashedEmbeds
                }
                continue
            }

            var includedIds = referencedIds
            var changed = true
            while changed {
                changed = false
                for embed in embeds {
                    let referencesParent = embed.parentEmbedId.map { includedIds.contains($0) } ?? false
                    let referencesChild = !Set(embed.childEmbedIds).isDisjoint(with: includedIds)
                    if (referencesParent || referencesChild), includedIds.insert(embed.id).inserted {
                        changed = true
                    }
                }
            }
            let related = includedIds.compactMap { embedsById[$0] }
            if !related.isEmpty {
                result[chat.id] = related
            }
        }

        for embed in embeds {
            guard let hashedChatId = embed.hashedChatId, let chatId = chatIdsByHash[hashedChatId] else { continue }
            result[chatId, default: []].append(embed)
        }

        return result.mapValues { EmbedRecord.deduplicatedById($0, context: "offlinePrefetch") }
    }
}
