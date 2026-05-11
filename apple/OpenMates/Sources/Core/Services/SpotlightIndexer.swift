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
    private let index = CSSearchableIndex(name: "OpenMatesChats")
    private let legacyDefaultIndex = CSSearchableIndex.default()
    private var pendingIndexTask: Task<Void, Never>?
    private let chatIdentifierPrefix = "chat-"
    private let chatsDomainIdentifier = "org.openmates.chats"
    private let maxIndexedUserChats = 100
    private let initialIndexDelayNs: UInt64 = 45_000_000_000
    private let perChatPauseNs: UInt64 = 90_000_000

    private init() {}

    /// Index a batch of chats. Called after initial load and on WebSocket updates.
    func indexChats(_ chats: [Chat]) {
        guard CSSearchableIndex.isIndexingAvailable() else {
            print("[Spotlight] Indexing unavailable on this device")
            return
        }

        let items = chats.compactMap { chat -> CSSearchableItem? in
            guard let title = chat.title, !title.isEmpty else { return nil }

            let attributes = CSSearchableItemAttributeSet(contentType: .text)
            attributes.title = title
            attributes.displayName = title
            attributes.contentDescription = "OpenMates chat"
            attributes.lastUsedDate = chat.lastMessageDate
            attributes.keywords = spotlightKeywords(for: chat)

            // Use the app icon as the thumbnail
            #if os(iOS)
            attributes.thumbnailData = UIImage(named: "AppIcon")?.pngData()
            #endif

            return searchableItem(for: chat, attributes: attributes)
        }

        guard !items.isEmpty else { return }
        Task { [weak self] in
            await self?.submitItems(items)
        }
    }

    /// Debounced indexing for synced user chats. This keeps login and sync fast while
    /// still making the latest 100 chats searchable shortly after the app settles.
    func scheduleIndexChats(_ chats: [Chat], reason: String) {
        guard CSSearchableIndex.isIndexingAvailable() else {
            print("[Spotlight] Indexing unavailable on this device")
            return
        }

        let snapshot = Array(chats.prefix(maxIndexedUserChats))
        guard !snapshot.isEmpty else { return }
        pendingIndexTask?.cancel()
        let delay = initialIndexDelayNs
        pendingIndexTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: delay)
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
            if Task.isCancelled { return }
            guard let title = chat.title, !title.isEmpty else { continue }
            let messages = OfflineStore.shared.loadMessages(chatId: chat.id)
            let messageText = await searchableText(from: messages, chatId: chat.id)
            let attributes = CSSearchableItemAttributeSet(contentType: .text)
            attributes.title = title
            attributes.displayName = title
            attributes.contentDescription = [
                chat.category,
                chat.chatSummary,
                messageText
            ]
            .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: "\n\n")
            attributes.lastUsedDate = chat.lastMessageDate
            attributes.keywords = spotlightKeywords(for: chat)

            #if os(iOS)
            attributes.thumbnailData = UIImage(named: "AppIcon")?.pngData()
            #endif

            items.append(searchableItem(for: chat, attributes: attributes))
            await Task.yield()
            try? await Task.sleep(nanoseconds: perChatPauseNs)
        }

        guard !items.isEmpty else { return }
        await submitItems(items)
    }

    private func searchableText(from messages: [Message], chatId: String) async -> String {
        var snippets: [String] = []
        snippets.reserveCapacity(min(messages.count, 80))

        for message in messages.suffix(80) {
            if Task.isCancelled { break }
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
            await Task.yield()
        }

        return snippets.joined(separator: "\n")
    }

    /// Remove a single chat from the Spotlight index (called on delete).
    func removeChat(_ chatId: String) {
        let identifiers = ["\(chatIdentifierPrefix)\(chatId)"]
        index.deleteSearchableItems(withIdentifiers: identifiers) { error in
            if let error {
                print("[Spotlight] Failed to remove chat: \(error)")
            }
        }
        legacyDefaultIndex.deleteSearchableItems(withIdentifiers: identifiers, completionHandler: nil)
    }

    /// Clear all OpenMates items from Spotlight (called on logout).
    func removeAllItems() {
        let domainIdentifiers = [chatsDomainIdentifier]
        index.deleteSearchableItems(withDomainIdentifiers: domainIdentifiers) { error in
            if let error {
                print("[Spotlight] Failed to clear index: \(error)")
            }
        }
        legacyDefaultIndex.deleteSearchableItems(withDomainIdentifiers: domainIdentifiers, completionHandler: nil)
    }

    private func searchableItem(for chat: Chat, attributes: CSSearchableItemAttributeSet) -> CSSearchableItem {
        let item = CSSearchableItem(
            uniqueIdentifier: "\(chatIdentifierPrefix)\(chat.id)",
            domainIdentifier: chatsDomainIdentifier,
            attributeSet: attributes
        )
        item.expirationDate = .distantFuture
        return item
    }

    private func submitItems(_ items: [CSSearchableItem]) async {
        do {
            try await index.indexSearchableItems(items)
            print("[Spotlight] Indexed \(items.count) chats")
        } catch {
            print("[Spotlight] Failed to index chats: \(error)")
        }
    }

    private func spotlightKeywords(for chat: Chat) -> [String] {
        var keywords = ["OpenMates", "chat"]
        if let category = chat.category?.trimmingCharacters(in: .whitespacesAndNewlines), !category.isEmpty {
            keywords.append(category)
        }
        return keywords
    }
}
