// Offline sync bridge — coordinates between the in-memory ChatStore, the persistent
// OfflineStore (SwiftData), and the network SyncManager. Handles:
// 1. Persisting synced data to disk as it arrives
// 2. Loading from disk on cold boot (before WebSocket connects)
// 3. Queuing user actions when offline and replaying them on reconnect
// 4. Network reachability monitoring via NWPathMonitor

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
    private let offlineStore: OfflineStore
    private let pathMonitor = NWPathMonitor()
    private let monitorQueue = DispatchQueue(label: "org.openmates.network-monitor")

    init(chatStore: ChatStore) {
        self.chatStore = chatStore
        self.offlineStore = OfflineStore.shared
        startNetworkMonitoring()
    }

    deinit {
        pathMonitor.cancel()
    }

    // MARK: - Network monitoring

    private func startNetworkMonitoring() {
        pathMonitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor [weak self] in
                guard let self else { return }
                let newStatus: NetworkStatus = path.status == .satisfied ? .online : .offline
                let wasOffline = self.networkStatus == .offline
                self.networkStatus = newStatus
                self.offlineStore.setOffline(newStatus == .offline)

                if wasOffline && newStatus == .online {
                    await self.replayPendingActions()
                }
            }
        }
        pathMonitor.start(queue: monitorQueue)
    }

    // MARK: - Cold boot: load from disk before network is available

    func loadFromDisk() {
        let chats = offlineStore.loadChats()
        for chat in chats {
            chatStore.upsertChat(chat)
        }

        for chat in chats.prefix(5) {
            let messages = offlineStore.loadMessages(chatId: chat.id)
            if !messages.isEmpty {
                chatStore.setMessages(for: chat.id, messages: messages)
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

    func onEmbedsReceived(_ embeds: [EmbedRecord]) {
        offlineStore.persistEmbeds(embeds)
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
              let messageId = payload["message_id"] as? String,
              let content = payload["content"] as? String else { return }

        let body: [String: Any] = [
            "chat_id": chatId,
            "message": [
                "message_id": messageId,
                "role": "user",
                "content": content,
                "created_at": payload["created_at"] ?? Int(Date().timeIntervalSince1970),
                "chat_has_title": true,
            ] as [String: Any],
        ]
        let _: Data = try await APIClient.shared.request(.post, path: "/v1/chat/message", body: body)
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
        offlineStore.clearAll()
    }
}
