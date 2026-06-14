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
    private let pathMonitor = NWPathMonitor()
    private let monitorQueue = DispatchQueue(label: "org.openmates.network-monitor")
    private var isNetworkMonitoringStarted = false
    private var latestPath: NWPath?
    private var offlinePrefetchTask: Task<Void, Never>?
    private var offlinePrefetchCursor = 10

    private let offlinePrefetchChunkSize = 3
    private let offlinePrefetchMaxMessages = 10_000
    private let offlinePrefetchInterChunkDelayNs: UInt64 = 2_000_000_000

    init(chatStore: ChatStore, wsManager: WebSocketManager? = nil) {
        self.chatStore = chatStore
        self.wsManager = wsManager
        self.offlineStore = OfflineStore.shared
    }

    deinit {
        pathMonitor.cancel()
    }

    // MARK: - Network monitoring

    func startNetworkMonitoring() {
        guard !isNetworkMonitoringStarted else { return }
        isNetworkMonitoringStarted = true
        pathMonitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor [weak self] in
                guard let self else { return }
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
        guard offlinePrefetchTask == nil else { return }
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
        if !response.chats.isEmpty {
            offlineStore.persistChats(response.chats)
        }
        if !response.embedKeys.isEmpty {
            EmbedKeyManager.shared.store(response.embedKeys, source: "offlinePrefetch")
            offlineStore.persistEmbedKeys(response.embedKeys)
        }

        let messagesByChat = response.decodedMessagesByChat()
        if !messagesByChat.isEmpty {
            offlineStore.persistMessagesBatch(messagesByChat)
        }

        let embedsByChat = response.groupedEmbedsByChat(messagesByChat: messagesByChat)
        if !embedsByChat.isEmpty {
            offlineStore.persistEmbedsBatch(embedsByChat)
        }
    }

    // MARK: - Cold boot: load from disk before network is available

    func loadFromDisk() {
        chatStore.performWithoutPersistence {
            loadPersistedDataIntoStore()
        }
    }

    private func loadPersistedDataIntoStore() {
        let embedKeys = offlineStore.loadEmbedKeys()
        if !embedKeys.isEmpty {
            EmbedKeyManager.shared.store(embedKeys, source: "offline")
        }

        let chats = offlineStore.loadChats()
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
        offlineStore.persistChats(chats)
    }

    func onMessagesReceived(_ messages: [Message], chatId: String) {
        offlineStore.persistMessages(messages, chatId: chatId)
    }

    func onEmbedsReceived(_ embeds: [EmbedRecord], chatId: String) {
        offlineStore.persistEmbeds(embeds, chatId: chatId)
    }

    func onSyncContentReceived(
        messagesByChat: [String: [Message]],
        embedsByChat: [String: [EmbedRecord]]
    ) {
        if !messagesByChat.isEmpty {
            offlineStore.persistMessagesBatch(messagesByChat)
        }
        if !embedsByChat.isEmpty {
            offlineStore.persistEmbedsBatch(embedsByChat)
        }
    }

    func onChatDeleted(_ chatId: String) {
        offlineStore.deleteChat(chatId)
    }

    // MARK: - Queue offline actions

    func sendMessageOffline(chatId: String, messageId: String, content: String) {
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
        offlineStore.queueOfflineAction(type: "delete_message", payload: [
            "chat_id": chatId,
            "message_id": messageId,
        ])
    }

    func pinChatOffline(chatId: String, isPinned: Bool) {
        offlineStore.queueOfflineAction(type: "pin_chat", payload: [
            "chat_id": chatId,
            "is_pinned": isPinned,
        ])
    }

    func archiveChatOffline(chatId: String) {
        offlineStore.queueOfflineAction(type: "archive_chat", payload: [
            "chat_id": chatId,
        ])
    }

    func hideChatOffline(chatId: String) {
        offlineStore.queueOfflineAction(type: "hide_chat", payload: [
            "chat_id": chatId,
        ])
    }

    // MARK: - Replay pending actions on reconnect

    func replayPendingActions() async {
        let actions = offlineStore.loadPendingActions()
        guard !actions.isEmpty else { return }

        for action in actions {
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
                default:
                    break
                }
                offlineStore.removePendingAction(action.id)
            } catch {
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

    // MARK: - Clear on logout

    func clearOnLogout() {
        cancelOfflinePrefetch()
        offlinePrefetchCursor = 10
        offlineStore.clearAll()
    }
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
