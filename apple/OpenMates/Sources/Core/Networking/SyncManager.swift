// Phased sync manager — implements the bounded startup chat sync protocol.
// Phase 1a: Last-opened/recent metadata for immediate display.
// Phase 1b: Full encrypted content for up to 10 recent parent chats.
// Phase 2: Metadata-only sync for the 100 most recent chats.
// Optional offline content for older parent chats is fetched via REST chunks.

import Foundation
import SwiftUI

@MainActor
final class SyncManager: ObservableObject {
    @Published var syncState: SyncState = .idle
    @Published var totalChatCount: Int = 0

    enum SyncState: Equatable {
        case idle
        case syncing(phase: Int)
        case complete
        case failed(String)

        static func == (lhs: SyncState, rhs: SyncState) -> Bool {
            switch (lhs, rhs) {
            case (.idle, .idle), (.complete, .complete): return true
            case (.syncing(let a), .syncing(let b)): return a == b
            case (.failed(let a), .failed(let b)): return a == b
            default: return false
            }
        }
    }

    private let wsManager: WebSocketManager
    private let chatStore: ChatStore
    private var syncTimeoutTask: Task<Void, Never>?

    private let syncTimeoutSeconds: TimeInterval = 30

    init(wsManager: WebSocketManager, chatStore: ChatStore) {
        self.wsManager = wsManager
        self.chatStore = chatStore
    }

    // MARK: - Initiate sync

    func startSync() async {
        syncState = .syncing(phase: 1)

        do {
            try await wsManager.send(WSOutboundMessage(
                type: "phased_sync_request",
                data: ["phase": "all"]
            ))
        } catch {
            syncState = .failed(error.localizedDescription)
            return
        }

        syncTimeoutTask = Task {
            try? await Task.sleep(for: .seconds(syncTimeoutSeconds))
            if case .syncing = syncState {
                syncState = .complete
            }
        }
    }

    // MARK: - Handle sync events from WebSocket

    func handlePhase1(data: SyncPhase1Data) {
        syncState = .syncing(phase: 1)
        chatStore.upsertChat(data.chat)
    }

    func handlePhase1Content(data: SyncPhase1ContentData) {
        chatStore.upsertChat(data.chat)
        chatStore.setMessages(for: data.chat.id, messages: data.messages)
    }

    func handlePhase2(data: SyncPhase2Data) {
        syncState = .syncing(phase: 2)
        totalChatCount = data.totalChatCount
        for chat in data.chats {
            chatStore.upsertChat(chat)
        }
    }

    func handlePhase3(data: SyncPhase3Data) {
        syncState = .syncing(phase: 3)
        for chat in data.chats {
            chatStore.upsertChat(chat)
        }
        if data.isLastBatch {
            if totalChatCount > 100 {
                syncState = .syncing(phase: 4)
            } else {
                completeSync()
            }
        }
    }

    func handleMetadataSync(data: SyncMetadataData) {
        for chat in data.chats {
            chatStore.upsertChat(chat)
        }
        completeSync()
    }

    func handleSyncComplete() {
        completeSync()
    }

    private func completeSync() {
        syncTimeoutTask?.cancel()
        syncState = .complete
    }
}

// MARK: - Sync data types

struct SyncPhase1Data {
    let chat: Chat
}

struct SyncPhase1ContentData {
    let chat: Chat
    let messages: [Message]
}

struct SyncPhase2Data {
    let chats: [Chat]
    let chatCount: Int
    let totalChatCount: Int
}

struct SyncPhase3Data {
    let chats: [Chat]
    let batchNumber: Int
    let isLastBatch: Bool
}

struct SyncMetadataData {
    let chats: [Chat]
}
