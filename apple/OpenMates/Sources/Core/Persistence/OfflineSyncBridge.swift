// Offline sync bridge — coordinates between the in-memory ChatStore, the persistent
// OfflineStore (SwiftData), and the network SyncManager. Handles:
// 1. Persisting synced data to disk as it arrives
// 2. Loading from disk on cold boot (before WebSocket connects)
// 3. Queuing user actions when offline and replaying them on reconnect
// 4. Network reachability monitoring via NWPathMonitor

// Specification: specifications/features/apple-recent-offline-chats/specification.yml
// Assertions: apple-offline.recent-cohort, apple-offline.local-first, apple-offline.interruption-isolation, apple-offline.snapshot-integrity

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
    private var offlinePrefetchRunID: UUID?
    private var offlinePrefetchNeedsRefresh = false
    private var completedOfflineSnapshots: [String: String] = [:]
    private var invalidatedOfflineSnapshots = Set<String>()
    private var foregroundNavigationTask: Task<Void, Never>?
    private var isForegroundActive = true
    private var hasCompletedInitialSync = false
    private let contentFetcher: (@MainActor (String) async throws -> Data)?
    private let eligibilityOverride: (@MainActor () -> Bool)?
    private let keyValidator: (@MainActor (Chat, [ChatKeyWrapperRecord]) async throws -> String?)?

    private let startupRecentChatLimit = 20

    init(chatStore: ChatStore, wsManager: WebSocketManager? = nil, offlineStore: OfflineStore = .shared,
         contentFetcher: (@MainActor (String) async throws -> Data)? = nil,
         prefetchEligibility: (@MainActor () -> Bool)? = nil,
         keyValidator: (@MainActor (Chat, [ChatKeyWrapperRecord]) async throws -> String?)? = nil) {
        self.chatStore = chatStore
        self.wsManager = wsManager
        self.offlineStore = offlineStore
        self.scopeGeneration = offlineStore.scopeGeneration
        self.contentFetcher = contentFetcher
        self.eligibilityOverride = prefetchEligibility
        self.keyValidator = keyValidator
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

                if newStatus == .offline { self.cancelOfflinePrefetch() }
                if newStatus == .online {
                    if wasOffline { await self.replayPendingActions() }
                    self.startOfflinePrefetchIfEligible(reason: "networkRestored")
                }
            }
        }
        pathMonitor.start(queue: monitorQueue)
    }

    // MARK: - Recent twenty-chat offline cohort

    @discardableResult
    func startOfflinePrefetchIfEligible(reason: String) -> Task<Void, Never>? {
        guard isCurrentSession else { return nil }
        if reason == "startupSyncComplete" { hasCompletedInitialSync = true }
        offlinePrefetchNeedsRefresh = true
        if let offlinePrefetchTask { return offlinePrefetchTask }
        guard canRunOfflinePrefetch else { return nil }
        let runID = UUID()
        offlinePrefetchRunID = runID
        offlinePrefetchTask = Task(priority: .utility) { @MainActor [weak self] in
            await self?.runOfflinePrefetch(runID: runID)
        }
        return offlinePrefetchTask
    }

    func cancelOfflinePrefetch() {
        offlinePrefetchRunID = nil
        offlinePrefetchTask?.cancel()
        offlinePrefetchTask = nil
    }

    func waitForOfflinePrefetch() async {
        while let task = offlinePrefetchTask { await task.value }
    }

    func setForegroundActive(_ active: Bool) {
        isForegroundActive = active
        if active { startOfflinePrefetchIfEligible(reason: "foreground") }
        else {
            foregroundNavigationTask?.cancel()
            foregroundNavigationTask = nil
            cancelOfflinePrefetch()
        }
    }

    func foregroundDidNavigate() {
        cancelOfflinePrefetch()
        foregroundNavigationTask?.cancel()
        foregroundNavigationTask = Task { @MainActor [weak self] in
            do { try await Task.sleep(for: .seconds(1)) } catch { return }
            guard let self, self.isCurrentSession else { return }
            self.foregroundNavigationTask = nil
            self.startOfflinePrefetchIfEligible(reason: "navigationSettled")
        }
    }

    private var canRunOfflinePrefetch: Bool {
        guard isCurrentSession, hasCompletedInitialSync, isForegroundActive,
              foregroundNavigationTask == nil else { return false }
        if let eligibilityOverride { return eligibilityOverride() }
        guard networkStatus == .online, wsManager?.connectionState == .connected else { return false }
        if let latestPath {
            guard latestPath.status == .satisfied, !latestPath.isExpensive, !latestPath.isConstrained else { return false }
        }
        guard !ProcessInfo.processInfo.isLowPowerModeEnabled else { return false }
        switch ProcessInfo.processInfo.thermalState {
        case .nominal, .fair: return true
        default: return false
        }
    }

    private func isCurrentPrefetch(_ runID: UUID) -> Bool {
        !Task.isCancelled && offlinePrefetchRunID == runID && canRunOfflinePrefetch
    }

    private func runOfflinePrefetch(runID: UUID) async {
        defer {
            if offlinePrefetchRunID == runID {
                offlinePrefetchTask = nil
                offlinePrefetchRunID = nil
            }
        }
        guard let writer = await offlineStore.makeRecentChatCacheWriter(), isCurrentPrefetch(runID) else { return }
        let started = NativeSyncPerfLog.now()
        var cachedCount = 0
        while offlinePrefetchNeedsRefresh && isCurrentPrefetch(runID) {
            offlinePrefetchNeedsRefresh = false
            let cohort = OfflineRecentChatPolicy.cohort(from: chatStore.chats)
            // One request at a time. Neither decoded transcript rows nor embeds
            // are published to ChatStore by this background maintenance pass.
            for chat in cohort {
                guard isCurrentPrefetch(runID) else { return }
                let revision = OfflineRecentChatPolicy.revision(of: chat)
                if !invalidatedOfflineSnapshots.contains(chat.id),
                   completedOfflineSnapshots[chat.id] == revision || offlineStore.hasCompleteOfflineSnapshot(for: chat) { continue }
                let deletionVersion = offlineStore.chatDeletionVersion(chat.id)
                let writeFence = offlineStore.recentContentWriteFence(for: chat.id)
                do {
                    let data: Data
                    if let contentFetcher { data = try await contentFetcher(chat.id) }
                    else {
                        guard let wsManager else { throw OfflineDraftReplayError.transportUnavailable }
                        let response = try await wsManager.requestChatContentBatch(chatId: chat.id, beforeSend: { [weak self] in
                            guard let self, self.isCurrentPrefetch(runID) else { throw CancellationError() }
                        })
                        data = try JSONSerialization.data(withJSONObject: response.fields)
                    }
                    guard isCurrentPrefetch(runID), offlineStore.chatDeletionVersion(chat.id) == deletionVersion,
                          let current = chatStore.chat(for: chat.id),
                          OfflineRecentChatPolicy.revision(of: current) == revision else { continue }
                    let snapshot = try await writer.decode(data, chatId: chat.id)
                    guard isCurrentPrefetch(runID), offlineStore.chatDeletionVersion(chat.id) == deletionVersion else { return }
                    let validatedWrapper = try await validateSnapshotKey(chat: chat, snapshot: snapshot)
                    guard isCurrentPrefetch(runID), offlineStore.chatDeletionVersion(chat.id) == deletionVersion else { return }
                    let pending = pendingUserMessageIds(in: chat.id).union(chatStore.pendingAssistantRecoveryMessageIds(in: chat.id))
                    try await writer.persist(snapshot, chat: chat, validatedWrapper: validatedWrapper, preserving: pending, fence: writeFence)
                    guard isCurrentPrefetch(runID), offlineStore.chatDeletionVersion(chat.id) == deletionVersion else { return }
                    guard writeFence.isCurrent else { continue }
                    EmbedKeyManager.shared.store(snapshot.embedKeys, source: "recentOfflineCohort")
                    completedOfflineSnapshots[chat.id] = revision
                    invalidatedOfflineSnapshots.remove(chat.id)
                    cachedCount += 1
                    await Task.yield()
                } catch is CancellationError {
                    return
                } catch {
                    guard isCurrentPrefetch(runID) else { return }
                    NativeSyncPerfLog.warning("phase=recentOfflineCache result=failed category=\(String(describing: type(of: error)))")
                }
            }
        }
        NativeSyncPerfLog.info("phase=recentOfflineCache cachedChats=\(cachedCount) elapsedMs=\(NativeSyncPerfLog.ms(since: started))")
    }

    private func validateSnapshotKey(chat: Chat, snapshot: OfflineRecentChatSnapshot) async throws -> String? {
        if let keyValidator { return try await keyValidator(chat, snapshot.chatKeyWrappers) }
        let needsKey = snapshot.messages.contains { $0.encryptedContent != nil }
            || snapshot.embeds.contains { $0.encryptedContent != nil || $0.encryptedType != nil }
            || chat.encryptedTitle != nil
        let expectedScope = offlineStore.scopeGeneration
        let userID = await AuthManager.currentUserId()
        guard isCurrentSession, expectedScope == offlineStore.scopeGeneration, !Task.isCancelled else { throw CancellationError() }
        guard let userID, let masterKey = try? await CryptoManager.shared.loadMasterKey(for: userID) else {
            if needsKey { throw OfflineRecentChatCacheError.keyUnavailable }
            return nil
        }
        guard isCurrentSession, expectedScope == offlineStore.scopeGeneration, !Task.isCancelled else { throw CancellationError() }
        let manager = ChatKeyManager.shared
        if !snapshot.chatKeyWrappers.isEmpty {
            guard await manager.loadChatKey(chatId: chat.id, wrappers: snapshot.chatKeyWrappers, masterKey: masterKey) else {
                throw OfflineRecentChatCacheError.keyUnavailable
            }
        } else if let encryptedKey = chat.encryptedChatKey {
            guard await manager.loadChatKey(chatId: chat.id, encryptedChatKey: encryptedKey, masterKey: masterKey) else {
                throw OfflineRecentChatCacheError.keyUnavailable
            }
        } else if needsKey && !manager.hasKey(for: chat.id) {
            throw OfflineRecentChatCacheError.keyUnavailable
        }
        guard isCurrentSession, expectedScope == offlineStore.scopeGeneration, !Task.isCancelled else { throw CancellationError() }
        if needsKey && manager.encryptedKey(for: chat.id) == nil { throw OfflineRecentChatCacheError.keyUnavailable }
        return manager.encryptedKey(for: chat.id)
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
        startOfflinePrefetchIfEligible(reason: "metadataChanged")
    }

    func pendingUserMessageIds(in chatId: String) -> Set<String> {
        guard isCurrentSession else { return [] }
        return Set(offlineStore.loadPendingActions().compactMap { action in
            guard action.actionType == "send_message", let data = action.payloadJSON,
                  let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  payload["chat_id"] as? String == chatId else { return nil }
            return payload["message_id"] as? String
        })
    }

    func onMessagesReceived(_ messages: [Message], chatId: String) {
        guard isCurrentSession else { return }
        offlineStore.persistMessages(messages, chatId: chatId)
        completedOfflineSnapshots.removeValue(forKey: chatId)
        invalidatedOfflineSnapshots.insert(chatId)
        startOfflinePrefetchIfEligible(reason: "messagesChanged")
    }

    func onEmbedsReceived(_ embeds: [EmbedRecord], chatId: String) {
        guard isCurrentSession else { return }
        offlineStore.persistEmbeds(embeds, chatId: chatId)
        completedOfflineSnapshots.removeValue(forKey: chatId)
        invalidatedOfflineSnapshots.insert(chatId)
        startOfflinePrefetchIfEligible(reason: "embedsChanged")
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
        invalidatedOfflineSnapshots.formUnion(messagesByChat.keys)
        invalidatedOfflineSnapshots.formUnion(embedsByChat.keys)
        startOfflinePrefetchIfEligible(reason: "syncedContentChanged")
    }

    func onChatDeleted(_ chatId: String) {
        guard isCurrentSession else { return }
        cancelOfflinePrefetch()
        completedOfflineSnapshots.removeValue(forKey: chatId)
        offlineStore.deleteChat(chatId)
        startOfflinePrefetchIfEligible(reason: "chatDeleted")
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
        foregroundNavigationTask?.cancel()
        foregroundNavigationTask = nil
        cancelOfflinePrefetch()
        pathMonitor.cancel()
    }

}

extension OfflineSyncBridge: DraftSyncOfflineActions {}

private enum OfflineDraftReplayError: Error {
    case invalidEncryptedPayload
    case transportUnavailable
}

// Dedicated cache ordering is independent of sidebar pin/draft presentation.
enum OfflineRecentChatPolicy {
    static let capacity = 20

    static func recency(of chat: Chat) -> String {
        chat.lastEditedOverallTimestamp ?? [chat.updatedAt, chat.lastMessageAt, chat.createdAt].compactMap { $0 }.max() ?? chat.createdAt
    }

    static func revision(of chat: Chat) -> String {
        "\(chat.messagesV ?? 0)|\(recency(of: chat))"
    }

    static func cohort(from chats: [Chat]) -> [Chat] {
        Array(chats.filter {
            $0.parentId == nil && $0.isSubChat != true && !$0.isHiddenFromNormalSurfaces
                && !IncognitoChatSession.isIncognitoChatId($0.id)
                && !$0.id.hasPrefix("demo-") && !$0.id.hasPrefix("example-")
                && !$0.id.hasPrefix("announcements-")
        }.sorted {
            let left = recency(of: $0), right = recency(of: $1)
            return left == right ? $0.id < $1.id : left > right
        }.prefix(capacity))
    }
}
