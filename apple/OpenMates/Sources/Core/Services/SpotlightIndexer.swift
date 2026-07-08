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
    /// This indexes metadata only; message-body indexing is intentionally not part
    /// of startup so encrypted histories are not decrypted before a chat is opened.
    func indexChats(_ chats: [Chat]) {
        guard CSSearchableIndex.isIndexingAvailable() else {
            print("[Spotlight] Indexing unavailable on this device")
            return
        }

        let items = chats.compactMap(metadataOnlySearchableItem(for:))

        guard !items.isEmpty else { return }
        Task { [weak self] in
            await self?.submitItems(items)
        }
    }

    /// Debounced indexing for synced user chats. This keeps login and sync fast while
    /// still making the latest 100 chats searchable shortly after the app settles.
    func scheduleIndexChats(
        _ chats: [Chat],
        reason: String,
        metadataProvider: (@MainActor (Chat) async -> Chat)? = nil
    ) {
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
            await self.indexMetadataOnlyChats(snapshot, metadataProvider: metadataProvider)
            NativeSyncPerfLog.info(
                "phase=spotlightIndex reason=\(reason) mode=metadataOnly chats=\(snapshot.count) indexMs=\(NativeSyncPerfLog.ms(since: start))"
            )
        }
    }

    private func indexMetadataOnlyChats(
        _ chats: [Chat],
        metadataProvider: (@MainActor (Chat) async -> Chat)? = nil
    ) async {
        var items: [CSSearchableItem] = []
        items.reserveCapacity(chats.count)

        for chat in chats {
            if Task.isCancelled { return }
            let searchableChat: Chat
            if let metadataProvider {
                searchableChat = await metadataProvider(chat)
            } else {
                searchableChat = chat
            }
            if let item = metadataOnlySearchableItem(for: searchableChat) {
                items.append(item)
            }
            await Task.yield()
            try? await Task.sleep(nanoseconds: perChatPauseNs)
        }

        guard !items.isEmpty else { return }
        await submitItems(items)
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

    private func metadataOnlySearchableItem(for chat: Chat) -> CSSearchableItem? {
        guard Self.isEligibleForSpotlight(chat) else { return nil }
        guard let title = chat.title?.trimmingCharacters(in: .whitespacesAndNewlines), !title.isEmpty else { return nil }

        let attributes = CSSearchableItemAttributeSet(contentType: .text)
        attributes.title = title
        attributes.displayName = title
        attributes.contentDescription = [chat.category, chat.chatSummary]
            .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: "\n\n")
        attributes.lastUsedDate = chat.lastMessageDate
        attributes.keywords = spotlightKeywords(for: chat)

        #if os(iOS)
        attributes.thumbnailData = UIImage(named: "AppIcon")?.pngData()
        #endif

        return searchableItem(for: chat, attributes: attributes)
    }

    static func isEligibleForSpotlight(_ chat: Chat) -> Bool {
        guard chat.isArchived != true else { return false }
        guard !chat.isHiddenFromNormalSurfaces else { return false }
        guard !isPublicChat(chat.id) else { return false }
        return true
    }

    private static func isPublicChat(_ chatId: String) -> Bool {
        chatId.hasPrefix("demo-") ||
        chatId.hasPrefix("legal-") ||
        chatId.hasPrefix("example-") ||
        chatId.hasPrefix("announcements-")
    }
}
