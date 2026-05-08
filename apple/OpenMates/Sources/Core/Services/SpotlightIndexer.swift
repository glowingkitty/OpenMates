// Spotlight indexer — indexes chats into Core Spotlight so users can find
// their conversations from the system search (Spotlight / Cmd-Space).
// Each chat becomes a searchable item with its title and last message date.
// Items are updated incrementally when chats are loaded and removed when deleted.

import CoreSpotlight
import UniformTypeIdentifiers
#if os(iOS)
import UIKit
#endif

@MainActor
final class SpotlightIndexer {
    static let shared = SpotlightIndexer()
    private let index = CSSearchableIndex.default()
    private var pendingIndexTask: Task<Void, Never>?
    private let maxIndexedUserChats = 100

    private init() {}

    /// Index a batch of chats. Called after initial load and on WebSocket updates.
    func indexChats(_ chats: [Chat]) {
        let items = chats.compactMap { chat -> CSSearchableItem? in
            guard let title = chat.title, !title.isEmpty else { return nil }

            let attributes = CSSearchableItemAttributeSet(contentType: .text)
            attributes.title = title
            attributes.contentDescription = "OpenMates chat"
            attributes.lastUsedDate = chat.lastMessageDate

            // Use the app icon as the thumbnail
            #if os(iOS)
            attributes.thumbnailData = UIImage(named: "AppIcon")?.pngData()
            #endif

            return CSSearchableItem(
                uniqueIdentifier: "chat-\(chat.id)",
                domainIdentifier: "org.openmates.chats",
                attributeSet: attributes
            )
        }

        guard !items.isEmpty else { return }

        index.indexSearchableItems(items) { error in
            if let error {
                print("[Spotlight] Failed to index chats: \(error)")
            }
        }
    }

    /// Debounced indexing for synced user chats. This keeps login and sync fast while
    /// still making the latest 100 chats searchable shortly after the app settles.
    func scheduleIndexChats(_ chats: [Chat], reason: String) {
        let snapshot = Array(chats.prefix(maxIndexedUserChats))
        guard !snapshot.isEmpty else { return }
        pendingIndexTask?.cancel()
        pendingIndexTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            guard !Task.isCancelled, let self else { return }
            let start = NativeSyncPerfLog.now()
            await self.indexChatsWithStoredMessages(snapshot)
            NativeSyncPerfLog.info(
                "phase=spotlightIndex reason=\(reason) chats=\(snapshot.count) indexMs=\(NativeSyncPerfLog.ms(since: start))"
            )
        }
    }

    private func indexChatsWithStoredMessages(_ chats: [Chat]) async {
        var items: [CSSearchableItem] = []
        items.reserveCapacity(chats.count)

        for chat in chats {
            guard let title = chat.title, !title.isEmpty else { continue }
            let messages = OfflineStore.shared.loadMessages(chatId: chat.id)
            let messageText = await searchableText(from: messages, chatId: chat.id)
            let attributes = CSSearchableItemAttributeSet(contentType: .text)
            attributes.title = title
            attributes.contentDescription = [
                chat.category,
                chat.chatSummary,
                messageText
            ]
            .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: "\n\n")
            attributes.lastUsedDate = chat.lastMessageDate

            #if os(iOS)
            attributes.thumbnailData = UIImage(named: "AppIcon")?.pngData()
            #endif

            items.append(
                CSSearchableItem(
                    uniqueIdentifier: "chat-\(chat.id)",
                    domainIdentifier: "org.openmates.chats",
                    attributeSet: attributes
                )
            )
            try? await Task.sleep(nanoseconds: 30_000_000)
        }

        guard !items.isEmpty else { return }
        index.indexSearchableItems(items) { error in
            if let error {
                print("[Spotlight] Failed to index chats: \(error)")
            }
        }
    }

    private func searchableText(from messages: [Message], chatId: String) async -> String {
        var snippets: [String] = []
        snippets.reserveCapacity(min(messages.count, 80))

        for message in messages.suffix(80) {
            if let content = message.content, !content.isEmpty {
                snippets.append(content)
            } else if let encryptedContent = message.encryptedContent,
                      let decrypted = await ChatKeyManager.shared.decryptMessageContent(
                          chatId: chatId,
                          encryptedContent: encryptedContent
                      ),
                      !decrypted.isEmpty {
                snippets.append(decrypted)
            }
            if snippets.count >= 80 { break }
        }

        return snippets.joined(separator: "\n")
    }

    /// Remove a single chat from the Spotlight index (called on delete).
    func removeChat(_ chatId: String) {
        index.deleteSearchableItems(withIdentifiers: ["chat-\(chatId)"]) { error in
            if let error {
                print("[Spotlight] Failed to remove chat: \(error)")
            }
        }
    }

    /// Clear all OpenMates items from Spotlight (called on logout).
    func removeAllItems() {
        index.deleteSearchableItems(withDomainIdentifiers: ["org.openmates.chats"]) { error in
            if let error {
                print("[Spotlight] Failed to clear index: \(error)")
            }
        }
    }
}
